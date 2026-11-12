#!/usr/bin/env python3
"""Audit text-extraction coverage across the real exported SiYuan .sy corpus.

This is a diagnostic inventory, not a semantic or medical-content validator.
Only TextMarkTextContent and Data string payloads are treated as extracted by
the current catalogue parser. Other string fields are surfaced for inspection.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

EXTRACTED_FIELDS = {
    "NodeText": {"Data"},
    "NodeLinkText": {"Data"},
    "NodeTextMark": {"TextMarkTextContent", "TextMarkInlineMathContent"},
}
METADATA_FIELDS = {"Properties", "IAL", "Type", "ID", "Spec"}


def iter_typed_nodes(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from iter_typed_nodes(item)
    elif isinstance(value, dict):
        if value.get("Type"):
            yield value
        for key, item in value.items():
            if key not in METADATA_FIELDS and isinstance(item, (dict, list)):
                yield from iter_typed_nodes(item)


def inspect_tree(value: Any, type_counts: Counter[str],
                 type_stats: dict[str, Counter[str]],
                 unclassified_fields: Counter[str]) -> tuple[int, int]:
    """Return extracted payload count and character count for this subtree."""
    if isinstance(value, list):
        totals = [inspect_tree(item, type_counts, type_stats, unclassified_fields) for item in value]
        return sum(item[0] for item in totals), sum(item[1] for item in totals)
    if not isinstance(value, dict):
        return 0, 0

    node_type = str(value.get("Type") or "UNTYPED")
    if value.get("Type"):
        type_counts[node_type] += 1
    payload_count = 0
    char_count = 0
    for key, item in value.items():
        if key in EXTRACTED_FIELDS.get(node_type, set()) and isinstance(item, str) and item.strip():
            payload_count += 1
            char_count += len(item.strip())
            type_stats[node_type]["extracted_payloads"] += 1
        elif key not in METADATA_FIELDS and isinstance(item, str) and item.strip():
            unclassified_fields[key] += 1
            type_stats[node_type][f"other_string_field:{key}"] += 1
        elif isinstance(item, (dict, list)):
            child_payloads, child_chars = inspect_tree(
                item, type_counts, type_stats, unclassified_fields
            )
            payload_count += child_payloads
            char_count += child_chars

    if value.get("Type"):
        type_stats[node_type]["nodes"] += 1
        if payload_count == 0:
            type_stats[node_type]["nodes_without_extracted_payload"] += 1
    return payload_count, char_count


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(root: Path, output: Path) -> dict[str, int]:
    files = sorted(
        p for p in root.rglob("*.sy")
        if p.is_file() and "assets" not in p.parts and output not in p.parents
    )
    doc_rows: list[dict[str, Any]] = []
    type_counts: Counter[str] = Counter()
    type_stats: dict[str, Counter[str]] = defaultdict(Counter)
    unclassified_fields: Counter[str] = Counter()
    parse_errors = 0

    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_errors += 1
            doc_rows.append({
                "document": rel, "parse_status": "PARSE_ERROR",
                "typed_node_count": 0, "extracted_payload_count": 0,
                "extracted_char_count": 0, "unclassified_string_fields": "",
                "error": type(exc).__name__,
            })
            continue

        before = unclassified_fields.copy()
        payload_count, char_count = inspect_tree(
            raw, type_counts, type_stats, unclassified_fields
        )
        other = sorted(k for k, v in (unclassified_fields - before).items() if v)
        doc_rows.append({
            "document": rel, "parse_status": "PARSED",
            "typed_node_count": sum(1 for _ in iter_typed_nodes(raw)),
            "extracted_payload_count": payload_count,
            "extracted_char_count": char_count,
            "unclassified_string_fields": ";".join(other),
            "error": "",
        })

    type_rows = []
    for node_type in sorted(type_counts):
        stats = type_stats[node_type]
        other_fields = sorted(
            key.split(":", 1)[1] for key in stats if key.startswith("other_string_field:")
        )
        type_rows.append({
            "node_type": node_type,
            "node_count": stats["nodes"],
            "nodes_without_extracted_payload": stats["nodes_without_extracted_payload"],
            "extracted_payload_count": stats["extracted_payloads"],
            "unclassified_string_fields": ";".join(other_fields),
        })

    write_csv(output / "content_integrity_audit.csv", doc_rows, [
        "document", "parse_status", "typed_node_count", "extracted_payload_count",
        "extracted_char_count", "unclassified_string_fields", "error",
    ])
    write_csv(output / "block_type_inventory.csv", type_rows, [
        "node_type", "node_count", "nodes_without_extracted_payload",
        "extracted_payload_count", "unclassified_string_fields",
    ])

    parsed = len(files) - parse_errors
    lines = [
        "# 真实思源笔记正文提取覆盖审计", "",
        "> 本报告扫描仓库内真实导出的 .sy 文件。它统计当前解析器识别的文本载荷字段和块类型；不判断医学内容真伪，也不把其他字符串字段自动认定为漏提取正文。", "",
        "## 扫描结果", "",
        f"- .sy 文件：{len(files)}",
        f"- JSON 可解析：{parsed}",
        f"- JSON 解析失败：{parse_errors}",
        f"- 识别到的块类型：{len(type_rows)}",
        f"- 当前解析器提取的文本载荷：{sum(int(r['extracted_payload_count']) for r in doc_rows)}",
        f"- 当前解析器提取的字符数：{sum(int(r['extracted_char_count']) for r in doc_rows)}",
        f"- 出现的非当前提取字段字符串键：{len(unclassified_fields)}",
        "", "## 块类型检查入口", "",
        "详见 block_type_inventory.csv。nodes_without_extracted_payload 仅表示该节点子树中没有被当前规则识别的可见文本载荷（NodeText/NodeLinkText.Data、NodeTextMark.TextMarkTextContent/NodeTextMark.TextMarkInlineMathContent）；它可能是容器、图片、附件、布局或其他非文本节点，不能直接判定为丢失内容。",
        "", "## 逐篇定位", "",
        "详见 content_integrity_audit.csv。unclassified_string_fields 列出该文档中出现的、当前提取器未作为正文处理的字符串字段名，供后续按块类型检查其语义。",
        "", "## 判读限制", "",
        "- PARSED 只表示 JSON 语法有效，不代表正文提取无损。",
        "- 没有提取文本的节点不一定是错误；必须结合块类型和原始笔记上下文判断。",
        "- Data 字段在 SiYuan AST 中存在多种语义：NodeText/NodeLinkText 是可检索文字；NodeImage 的 span 和 NodeLinkDest 的资源路径不是正文。NodeTextMark 的 TextMarkInlineMathContent 也是笔记可见内容，已纳入提取。其他字段必须先建立块类型语义映射，不能直接拼进正文。",
        "- 本报告不修改任何原始 .sy 文件。",
    ]
    (output / "content_integrity_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"documents": len(files), "parsed": parsed, "parse_errors": parse_errors,
            "block_types": len(type_rows), "unclassified_string_fields": len(unclassified_fields)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    output = (args.output or root / "catalog" / "generated").expanduser().resolve()
    if not root.is_dir():
        parser.error(f"扫描根目录不存在：{root}")
    if output == root or root not in output.parents:
        parser.error("输出目录必须位于扫描根目录内，且不能等于根目录")
    result = build(root, output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["parse_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
