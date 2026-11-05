#!/usr/bin/env python3
"""Build a loss-aware semantic index for typed nodes in exported SiYuan .sy files.

The index preserves source document, source hash, block ID, node type and tree
position. It separates prose, HTML text, table/list structure and media refs;
it never rewrites the original notes or treats resource paths as prose.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

TEXT_FIELDS = {
    "NodeText": {"Data": "TEXT"},
    "NodeLinkText": {"Data": "LINK_TEXT"},
    "NodeTextMark": {
        "TextMarkTextContent": "MARKED_TEXT",
        "TextMarkInlineMathContent": "INLINE_MATH",
    },
}
META_FIELDS = {"Properties", "IAL", "Type", "ID", "Spec"}
STRUCTURAL_TYPES = {
    "NodeDocument", "NodeParagraph", "NodeHeading", "NodeList",
    "NodeListItem", "NodeTable", "NodeTableHead", "NodeTableRow",
    "NodeTableCell", "NodeBlockquote", "NodeSuperBlock",
}
MEDIA_TYPES = {"NodeImage", "NodeAudio", "NodeVideo", "NodeIFrame"}
HTML_TYPES = {"NodeHTMLBlock"}


class VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def node_children(node: dict[str, Any]):
    children = node.get("Children", [])
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                yield child


def direct_payload(node: dict[str, Any]) -> tuple[str, str, str]:
    """Return payload role, searchable text and non-prose raw value."""
    node_type = str(node.get("Type") or "")
    values = []
    roles = []
    raw_values = []
    for field, role in TEXT_FIELDS.get(node_type, {}).items():
        value = node.get(field)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
            roles.append(role)
    if node_type in HTML_TYPES:
        raw = node.get("Data")
        if isinstance(raw, str) and raw.strip():
            parser = VisibleHTML()
            parser.feed(raw)
            parser.close()
            return "HTML", " ".join(parser.parts), raw
    if node_type in MEDIA_TYPES:
        raw = node.get("Data")
        if isinstance(raw, str) and raw.strip():
            return "MEDIA_REFERENCE", "", raw.strip()
    if node_type == "NodeLinkDest":
        raw = node.get("Data")
        if isinstance(raw, str) and raw.strip():
            return "LINK_TARGET", "", raw.strip()
    if node_type == "NodeImage":
        raw = node.get("Data")
        if isinstance(raw, str) and raw.strip():
            return "IMAGE_LAYOUT", "", raw.strip()
    if values:
        return "+".join(roles), " ".join(values), ""
    return ("STRUCTURE" if node_type in STRUCTURAL_TYPES else "NON_TEXT"), "", ""


def descendants_text(node: dict[str, Any]) -> str:
    parts = []
    role, text, _ = direct_payload(node)
    if text:
        parts.append(text)
    for child in node_children(node):
        value = descendants_text(child)
        if value:
            parts.append(value)
    return " ".join(parts)


def walk_nodes(node: Any, document: str, source_hash: str,
               rows: list[dict[str, Any]], unknown: Counter[str],
               parent_id: str = "", parent_type: str = "",
               position: str = "0") -> None:
    if isinstance(node, list):
        for index, child in enumerate(node):
            walk_nodes(child, document, source_hash, rows, unknown,
                       parent_id, parent_type, f"{position}.{index}")
        return
    if not isinstance(node, dict):
        return
    node_type = str(node.get("Type") or "")
    if not node_type:
        for key, value in node.items():
            if key not in META_FIELDS and isinstance(value, (dict, list)):
                walk_nodes(value, document, source_hash, rows, unknown,
                           parent_id, parent_type, position)
        return

    block_id = str(node.get("ID") or "")
    role, own_text, raw_payload = direct_payload(node)
    child_count = sum(1 for _ in node_children(node))
    properties = node.get("Properties")
    property_keys = sorted(properties) if isinstance(properties, dict) else []
    rows.append({
        "document": document, "source_sha256": source_hash,
        "tree_position": position, "block_id": block_id,
        "parent_block_id": parent_id, "parent_node_type": parent_type,
        "node_type": node_type, "semantic_role": role,
        "heading_level": node.get("HeadingLevel", "") if node_type == "NodeHeading" else "",
        "list_type": node.get("ListType", "") if node_type == "NodeList" else "",
        "child_count": child_count, "property_keys": ";".join(map(str, property_keys)),
        "text": own_text, "container_text": descendants_text(node)
            if node_type in {"NodeParagraph", "NodeHeading", "NodeTableCell", "NodeListItem"} else "",
        "raw_payload": raw_payload,
    })

    mapped = set(TEXT_FIELDS.get(node_type, {}))
    if node_type in MEDIA_TYPES | HTML_TYPES | {"NodeLinkDest", "NodeImage"}:
        mapped.add("Data")
    for key, value in node.items():
        if key in META_FIELDS or key == "Children" or not isinstance(value, str) or not value.strip():
            continue
        if key not in mapped:
            unknown[f"{node_type}.{key}"] += 1

    for index, child in enumerate(node_children(node)):
        walk_nodes(child, document, source_hash, rows, unknown,
                   block_id, node_type, f"{position}.{index}")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path, output: Path) -> dict[str, int]:
    files = sorted(path for path in root.rglob("*.sy")
                   if path.is_file() and "assets" not in path.parts
                   and output not in path.parents)
    rows: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    unknown: Counter[str] = Counter()
    parse_errors = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        raw_bytes = path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        try:
            data = json.loads(raw_bytes.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_errors += 1
            docs.append({"document": relative, "source_sha256": digest,
                         "parse_status": "PARSE_ERROR", "node_count": 0,
                         "text_node_count": 0, "text_characters": 0,
                         "table_count": 0, "list_count": 0,
                         "html_block_count": 0, "media_node_count": 0,
                         "error": type(exc).__name__})
            continue
        before = len(rows)
        walk_nodes(data, relative, digest, rows, unknown)
        doc_nodes = rows[before:]
        text_nodes = [row for row in doc_nodes if row["text"]]
        docs.append({
            "document": relative, "source_sha256": digest, "parse_status": "PARSED",
            "node_count": len(doc_nodes), "text_node_count": len(text_nodes),
            "text_characters": sum(len(row["text"]) for row in text_nodes),
            "table_count": sum(row["node_type"] == "NodeTable" for row in doc_nodes),
            "list_count": sum(row["node_type"] == "NodeList" for row in doc_nodes),
            "html_block_count": sum(row["node_type"] in HTML_TYPES for row in doc_nodes),
            "media_node_count": sum(row["node_type"] in MEDIA_TYPES for row in doc_nodes),
            "error": "",
        })
    output.mkdir(parents=True, exist_ok=True)
    fields = ["document", "source_sha256", "tree_position", "block_id",
              "parent_block_id", "parent_node_type", "node_type", "semantic_role",
              "heading_level", "list_type", "child_count", "property_keys",
              "text", "container_text", "raw_payload"]
    write_csv(output / "node_semantic_index.csv", rows, fields)
    write_csv(output / "document_semantic_summary.csv", docs, [
        "document", "source_sha256", "parse_status", "node_count", "text_node_count",
        "text_characters", "table_count", "list_count", "html_block_count",
        "media_node_count", "error",
    ])
    unknown_rows = [{"node_field": key, "occurrences": count}
                    for key, count in sorted(unknown.items())]
    write_csv(output / "unmapped_node_fields.csv", unknown_rows,
              ["node_field", "occurrences"])
    counts = Counter(row["node_type"] for row in rows)
    report = [
        "# SiYuan 节点语义索引",
        "",
        f"- 扫描文档：{len(files)}",
        f"- JSON 解析失败：{parse_errors}",
        f"- 节点记录：{len(rows)}",
        f"- 节点类型：{len(counts)}",
        f"- 有直接文本载荷的节点：{sum(bool(row['text']) for row in rows)}",
        f"- 未映射字符串字段：{len(unknown_rows)}",
        "",
        "## 节点类型分布",
        "",
        *[f"- {kind}: {count}" for kind, count in sorted(counts.items())],
        "",
        "## 生成文件",
        "",
        "- node_semantic_index.csv：逐节点语义角色、块 ID、父节点、树位置、文本及非正文资源字段。",
        "- document_semantic_summary.csv：逐文档节点覆盖、文本载荷、表格/列表/HTML/媒体节点统计。",
        "- unmapped_node_fields.csv：尚未映射的字符串字段，供继续扩展解析器。",
        "",
        "## 解析边界",
        "",
        "- 原始 .sy 文件只读；所有索引记录包含原文件 SHA-256、相对路径和块定位。",
        "- HTML 同时保留原始值和剥离标签后的可见文字；媒体地址、附件目标、图片布局不混入正文。",
        "- 表格、列表和标题保留节点层级及父子关系；容器聚合文本只作导航，不能替代单元格/列表项节点记录。",
        "- 未映射字段不会自动拼入正文，避免把样式、资源路径或内部元数据污染为可检索文本。",
    ]
    (output / "node_semantic_index.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"documents": len(files), "parse_errors": parse_errors,
            "nodes": len(rows), "node_types": len(counts),
            "unmapped_fields": len(unknown_rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    output = (args.output or root / "catalog" / "generated").expanduser().resolve()
    if not root.is_dir() or output == root or root not in output.parents:
        parser.error("扫描根目录必须存在，输出目录必须位于根目录内")
    result = build(root, output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["parse_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
