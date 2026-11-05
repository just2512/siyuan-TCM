#!/usr/bin/env python3
"""Build a loss-aware semantic index for typed nodes in exported SiYuan .sy files.

The index preserves source document, source hash, block ID, node type and tree
position. It separates prose, HTML text, table/list structure and media refs;
it never rewrites the original notes or treats resource paths as prose.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
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
MARK_METADATA_FIELDS = {
    "TextMarkType": "MARK_TYPE",
    "TextMarkAHref": "LINK_HREF",
    "TextMarkATitle": "LINK_TITLE",
    "TextMarkBlockRefID": "BLOCK_REFERENCE_ID",
    "TextMarkBlockRefSubtype": "BLOCK_REFERENCE_SUBTYPE",
}
DATA_FIELD_ROLES = {
    "NodeBackslash": "ESCAPE_MARKER",
    "NodeBackslashContent": "ESCAPED_CONTENT",
    "NodeBr": "LINE_BREAK",
    "NodeKramdownSpanIAL": "INLINE_STYLE_METADATA",
    "NodeTableCell": "TABLE_CELL_LAYOUT",
    "NodeTableHead": "TABLE_HEADER_LAYOUT",
    "NodeTableRow": "TABLE_ROW_LAYOUT",
}
META_FIELDS = {"Properties", "IAL", "Type", "ID", "Spec"}
STRUCTURAL_TYPES = {
    "NodeDocument", "NodeParagraph", "NodeHeading", "NodeList",
    "NodeListItem", "NodeTable", "NodeTableHead", "NodeTableRow",
    "NodeTableCell", "NodeBlockquote", "NodeSuperBlock",
}
MEDIA_TYPES = {"NodeAudio", "NodeVideo", "NodeIFrame"}
HTML_TYPES = {"NodeHTMLBlock"}


class VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.suppressed_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.suppressed_depth:
            self.suppressed_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.suppressed_depth:
            return
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
    if node_type in DATA_FIELD_ROLES:
        raw = node.get("Data")
        if isinstance(raw, str) and raw.strip():
            return DATA_FIELD_ROLES[node_type], "", raw.strip()
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
               position: str = "0",
               content_rows: list[dict[str, Any]] | None = None) -> None:
    if isinstance(node, list):
        for index, child in enumerate(node):
            walk_nodes(child, document, source_hash, rows, unknown,
                       parent_id, parent_type, f"{position}.{index}",
                       content_rows=content_rows)
        return
    if not isinstance(node, dict):
        return
    node_type = str(node.get("Type") or "")
    if not node_type:
        for key, value in node.items():
            if key not in META_FIELDS and isinstance(value, (dict, list)):
                walk_nodes(value, document, source_hash, rows, unknown,
                           parent_id, parent_type, position,
                           content_rows=content_rows)
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
        "mark_type": node.get("TextMarkType", "") if node_type == "NodeTextMark" else "",
        "link_href": node.get("TextMarkAHref", "") if node_type == "NodeTextMark" else "",
        "link_title": node.get("TextMarkATitle", "") if node_type == "NodeTextMark" else "",
        "block_ref_id": node.get("TextMarkBlockRefID", "") if node_type == "NodeTextMark" else "",
        "block_ref_subtype": node.get("TextMarkBlockRefSubtype", "") if node_type == "NodeTextMark" else "",
        "text": own_text, "container_text": descendants_text(node)
            if node_type in {"NodeHeading", "NodeTableCell", "NodeListItem"} else "",
        "raw_payload": raw_payload,
    })

    if content_rows is not None and node_type in {
        "NodeParagraph", "NodeHeading", "NodeTableCell", "NodeListItem", "NodeHTMLBlock"
    }:
        content_text = descendants_text(node)
        if content_text:
            content_rows.append({
                "document": document, "source_sha256": source_hash,
                "tree_position": position, "block_id": block_id,
                "parent_block_id": parent_id, "parent_node_type": parent_type,
                "content_type": {
                    "NodeParagraph": "PARAGRAPH",
                    "NodeHeading": "HEADING",
                    "NodeTableCell": "TABLE_CELL",
                    "NodeListItem": "LIST_ITEM",
                    "NodeHTMLBlock": "HTML_BLOCK",
                }[node_type],
                "heading_level": node.get("HeadingLevel", "") if node_type == "NodeHeading" else "",
                "characters": len(content_text), "content_text": content_text,
            })

    mapped = set(TEXT_FIELDS.get(node_type, {}))
    if node_type == "NodeTextMark":
        mapped.update(MARK_METADATA_FIELDS)
    if node_type in MEDIA_TYPES | HTML_TYPES | {"NodeLinkDest", "NodeImage"} | set(DATA_FIELD_ROLES):
        mapped.add("Data")
    for key, value in node.items():
        if key in META_FIELDS or key == "Children" or not isinstance(value, str) or not value.strip():
            continue
        if key not in mapped:
            unknown[f"{node_type}.{key}"] += 1

    for index, child in enumerate(node_children(node)):
        walk_nodes(child, document, source_hash, rows, unknown,
                   block_id, node_type, f"{position}.{index}",
                   content_rows=content_rows)



def build_relationship_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert inline references and resource targets into traceable graph edges."""
    locations: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        block_id = str(row.get("block_id") or "")
        if block_id:
            locations.setdefault(block_id, []).append((
                str(row.get("document") or ""), str(row.get("tree_position") or "")
            ))

    edges: list[dict[str, Any]] = []

    def add(row: dict[str, Any], relation_type: str, target: str,
            subtype: str = "", resolution: str = "NOT_CHECKED",
            target_document: str = "") -> None:
        edges.append({
            "source_document": row["document"],
            "source_sha256": row["source_sha256"],
            "source_tree_position": row["tree_position"],
            "source_block_id": row["block_id"] or row["parent_block_id"],
            "source_node_type": row["node_type"],
            "relation_type": relation_type,
            "target": target,
            "target_subtype": subtype,
            "target_document": target_document,
            "resolution": resolution,
        })

    for row in rows:
        block_ref = str(row.get("block_ref_id") or "").strip()
        if block_ref:
            matches = locations.get(block_ref, [])
            if len(matches) == 1:
                resolution, target_document = "RESOLVED_IN_CORPUS", matches[0][0]
            elif len(matches) > 1:
                resolution, target_document = "AMBIGUOUS_BLOCK_ID", ""
            else:
                resolution, target_document = "NOT_FOUND_IN_CORPUS", ""
            add(row, "BLOCK_REFERENCE", block_ref,
                str(row.get("block_ref_subtype") or ""), resolution, target_document)

        href = str(row.get("link_href") or "").strip()
        if href:
            resolution = "EXTERNAL_URL" if re.match(r"^https?://", href, re.I) else "URI_OR_LOCAL_TARGET"
            add(row, "HYPERLINK", href, str(row.get("link_title") or ""), resolution)

        if row["node_type"] == "NodeLinkDest" and row["raw_payload"]:
            target = str(row["raw_payload"]).strip()
            if target.lower().startswith(("assets/", "../assets/")):
                resolution = "ASSET_REFERENCE"
            elif re.match(r"^https?://", target, re.I):
                resolution = "EXTERNAL_URL"
            else:
                resolution = "LOCAL_OR_UNCLASSIFIED_TARGET"
            add(row, "LINK_DESTINATION", target, "", resolution)

        if row["node_type"] in MEDIA_TYPES and row["raw_payload"]:
            add(row, "MEDIA_REFERENCE", str(row["raw_payload"]).strip(),
                row["node_type"], "REFERENCE_RECORDED_NOT_FILE_VERIFIED")

    return edges



def assign_section_context(content_rows: list[dict[str, Any]]) -> None:
    """Attach the active heading ancestry to each searchable content block."""
    active_document = ""
    stack: list[tuple[int, str, str]] = []
    for row in content_rows:
        document = str(row["document"])
        if document != active_document:
            active_document = document
            stack = []
        if row["content_type"] == "HEADING":
            try:
                level = int(row.get("heading_level") or 0)
            except (TypeError, ValueError):
                level = 0
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, row["content_text"], row["block_id"]))
        row["section_path"] = " / ".join(item[1] for item in stack)
        row["section_heading_block_ids"] = ";".join(item[2] for item in stack if item[2])


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        with path.open("wb") as raw_stream:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_stream, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path, output: Path) -> dict[str, int]:
    files = sorted(path for path in root.rglob("*.sy")
                   if path.is_file() and "assets" not in path.parts
                   and output not in path.parents)
    rows: list[dict[str, Any]] = []
    content_rows: list[dict[str, Any]] = []
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
                         "content_block_count": 0, "searchable_block_count": 0,
                         "content_characters": 0, "error": type(exc).__name__})
            continue
        before = len(rows)
        content_before = len(content_rows)
        walk_nodes(data, relative, digest, rows, unknown, content_rows=content_rows)
        doc_nodes = rows[before:]
        doc_content = content_rows[content_before:]
        text_nodes = [row for row in doc_nodes if row["text"]]
        docs.append({
            "document": relative, "source_sha256": digest, "parse_status": "PARSED",
            "node_count": len(doc_nodes), "text_node_count": len(text_nodes),
            "text_characters": sum(len(row["text"]) for row in text_nodes),
            "table_count": sum(row["node_type"] == "NodeTable" for row in doc_nodes),
            "list_count": sum(row["node_type"] == "NodeList" for row in doc_nodes),
            "html_block_count": sum(row["node_type"] in HTML_TYPES for row in doc_nodes),
            "media_node_count": sum(row["node_type"] in MEDIA_TYPES for row in doc_nodes),
            "content_block_count": len(doc_content),
            "searchable_block_count": sum(bool(row["content_text"]) for row in doc_content),
            "content_characters": sum(len(row["content_text"]) for row in doc_content),
            "error": "",
        })
    assign_section_context(content_rows)
    output.mkdir(parents=True, exist_ok=True)
    fields = ["document", "source_sha256", "tree_position", "block_id",
              "parent_block_id", "parent_node_type", "node_type", "semantic_role",
              "heading_level", "list_type", "child_count", "property_keys",
              "mark_type", "link_href", "link_title", "block_ref_id",
              "block_ref_subtype", "text", "container_text", "raw_payload"]
    write_csv(output / "node_semantic_index.csv.gz", rows, fields)
    relationships = build_relationship_rows(rows)
    write_csv(output / "node_relationship_index.csv.gz", relationships, [
        "source_document", "source_sha256", "source_tree_position",
        "source_block_id", "source_node_type", "relation_type", "target",
        "target_subtype", "target_document", "resolution",
    ])
    write_csv(output / "content_block_index.csv.gz", content_rows, [
        "document", "source_sha256", "tree_position", "block_id",
        "parent_block_id", "parent_node_type", "content_type", "heading_level",
        "section_path", "section_heading_block_ids", "characters", "content_text",
    ])
    write_csv(output / "document_semantic_summary.csv", docs, [
        "document", "source_sha256", "parse_status", "node_count", "text_node_count",
        "text_characters", "table_count", "list_count", "html_block_count",
        "media_node_count", "content_block_count", "searchable_block_count",
        "content_characters", "error",
    ])
    unknown_rows = [{"node_field": key, "occurrences": count}
                    for key, count in sorted(unknown.items())]
    write_csv(output / "unmapped_node_fields.csv", unknown_rows,
              ["node_field", "occurrences"])
    field_mapping = []
    for node_type, field_roles in TEXT_FIELDS.items():
        field_mapping.extend({
            "node_type": node_type, "field": field, "semantic_role": role,
            "indexed_as_text": "YES",
        } for field, role in field_roles.items())
    field_mapping.extend({
        "node_type": "NodeTextMark", "field": field, "semantic_role": role,
        "indexed_as_text": "NO",
    } for field, role in MARK_METADATA_FIELDS.items())
    field_mapping.extend({
        "node_type": node_type, "field": "Data", "semantic_role": role,
        "indexed_as_text": "NO",
    } for node_type, role in DATA_FIELD_ROLES.items())
    field_mapping.extend([
        {"node_type": "NodeHTMLBlock", "field": "Data",
         "semantic_role": "HTML_VISIBLE_TEXT", "indexed_as_text": "YES"},
        *[{"node_type": node_type, "field": "Data",
           "semantic_role": "MEDIA_REFERENCE", "indexed_as_text": "NO"}
          for node_type in sorted(MEDIA_TYPES)],
        {"node_type": "NodeImage", "field": "Data",
         "semantic_role": "IMAGE_LAYOUT", "indexed_as_text": "NO"},
        {"node_type": "NodeLinkDest", "field": "Data",
         "semantic_role": "LINK_TARGET", "indexed_as_text": "NO"},
    ])
    write_csv(output / "node_field_mapping.csv", field_mapping,
              ["node_type", "field", "semantic_role", "indexed_as_text"])
    counts = Counter(row["node_type"] for row in rows)
    relation_counts = Counter(row["relation_type"] for row in relationships)
    resolution_counts = Counter(row["resolution"] for row in relationships)
    report = [
        "# SiYuan 节点语义索引",
        "",
        f"- 扫描文档：{len(files)}",
        f"- JSON 解析失败：{parse_errors}",
        f"- 节点记录：{len(rows)}",
        f"- 可检索内容块：{len(content_rows)}",
        f"- 可追溯关系边：{len(relationships)}",
        f"- 节点类型：{len(counts)}",
        f"- 有直接文本载荷的节点：{sum(bool(row['text']) for row in rows)}",
        f"- 已定义字段语义映射：{len(field_mapping)}",
        f"- 未映射字符串字段：{len(unknown_rows)}",
        "",
        "## 节点类型分布",
        "",
        *[f"- {kind}: {count}" for kind, count in sorted(counts.items())],
        "",
        "## 关系类型分布",
        "",
        *[f"- {kind}: {count}" for kind, count in sorted(relation_counts.items())],
        "",
        "## 关系解析状态",
        "",
        *[f"- {kind}: {count}" for kind, count in sorted(resolution_counts.items())],
        "",
        "## 生成文件",
        "",
        "- node_semantic_index.csv.gz：gzip 压缩的逐节点语义索引；解压后为 UTF-8 CSV，保留块 ID、父节点、树位置、文本及非正文资源字段。",
        "- content_block_index.csv.gz：gzip 压缩的段落/标题/表格单元格/列表项/HTML 块全文索引，附带当前标题路径和标题块 ID，可直接用于检索和定位。",
        "- node_relationship_index.csv.gz：gzip 压缩的块引用、超链接、附件目标和媒体引用关系边。",
        "- document_semantic_summary.csv：逐文档节点覆盖、文本载荷、表格/列表/HTML/媒体节点和可检索内容块统计。",
        "- node_field_mapping.csv：已知节点字段到语义角色的映射及是否进入正文索引。",
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
            "nodes": len(rows), "content_blocks": len(content_rows),
            "relationships": len(relationships), "node_types": len(counts),
            "mapped_fields": len(field_mapping), "unmapped_fields": len(unknown_rows)}


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
