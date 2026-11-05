#!/usr/bin/env python3
"""Find content-quality anomalies in the actual exported SiYuan .sy notes.

Signals are conservative review candidates, not confirmed errors. Original files
are read-only; every paragraph-level finding retains its document and ordinal.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from build_siyuan_catalog import extract_text

REPLACEMENT = "\ufffd"
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
SPACE_RE = re.compile(r"\s+")


def walk_nodes(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from walk_nodes(item)
    elif isinstance(value, dict):
        if value.get("Type"):
            yield value
        for key, child in value.items():
            if key not in {"Properties", "IAL"} and isinstance(child, (dict, list)):
                yield from walk_nodes(child)


def paragraph_rows(root: Any, document: str) -> list[dict[str, Any]]:
    rows = []
    for node in walk_nodes(root):
        if node.get("Type") != "NodeParagraph":
            continue
        text = SPACE_RE.sub(" ", extract_text(node)).strip()
        if text:
            rows.append({
                "document": document,
                "paragraph_index": len(rows) + 1,
                "characters": len(text),
                "normalized_text": text,
            })
    return rows


def build(root: Path, output: Path) -> dict[str, int]:
    files = sorted(p for p in root.rglob("*.sy")
                   if p.is_file() and "assets" not in p.parts and output not in p.parents)
    doc_rows = []
    paragraph_findings = []
    parse_errors = 0
    total_chars = 0

    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            parse_errors += 1
            doc_rows.append({
                "document": relative, "parse_status": "PARSE_ERROR",
                "text_characters": 0, "paragraph_count": 0,
                "anomaly_flags": "PARSE_ERROR", "error": type(exc).__name__,
            })
            continue

        text = extract_text(raw)
        paragraphs = paragraph_rows(raw, relative)
        flags = []
        if len(text) < 20:
            flags.append("VERY_SHORT_EXTRACTED_TEXT")
        if len(text) > 50000:
            flags.append("VERY_LONG_EXTRACTED_TEXT")
        if REPLACEMENT in text:
            flags.append("UNICODE_REPLACEMENT_CHARACTER")
        if CONTROL_RE.search(text):
            flags.append("CONTROL_CHARACTER_IN_TEXT")

        seen: dict[str, int] = {}
        for paragraph in paragraphs:
            value = paragraph["normalized_text"]
            if len(value) >= 30:
                if value in seen:
                    paragraph_findings.append({
                        **paragraph,
                        "finding": "EXACT_DUPLICATE_PARAGRAPH",
                        "first_occurrence_index": seen[value],
                        "excerpt": value[:240],
                    })
                else:
                    seen[value] = paragraph["paragraph_index"]
            if len(value) > 3000:
                paragraph_findings.append({
                    **paragraph,
                    "finding": "VERY_LONG_PARAGRAPH",
                    "first_occurrence_index": "",
                    "excerpt": value[:240],
                })
        if any(row["document"] == relative and row["finding"] == "EXACT_DUPLICATE_PARAGRAPH"
               for row in paragraph_findings):
            flags.append("EXACT_DUPLICATE_PARAGRAPH")
        if any(row["document"] == relative and row["finding"] == "VERY_LONG_PARAGRAPH"
               for row in paragraph_findings):
            flags.append("VERY_LONG_PARAGRAPH")

        total_chars += len(text)
        doc_rows.append({
            "document": relative, "parse_status": "PARSED",
            "text_characters": len(text), "paragraph_count": len(paragraphs),
            "anomaly_flags": ";".join(flags) if flags else "NO_STATIC_SIGNAL",
            "error": "",
        })

    output.mkdir(parents=True, exist_ok=True)
    with (output / "content_anomaly_audit.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "document", "parse_status", "text_characters", "paragraph_count",
            "anomaly_flags", "error",
        ])
        writer.writeheader()
        writer.writerows(doc_rows)
    with (output / "paragraph_anomaly_audit.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "document", "paragraph_index", "characters", "finding",
            "first_occurrence_index", "excerpt",
        ])
        writer.writeheader()
        writer.writerows(paragraph_findings)

    flag_counts = Counter(
        flag for row in doc_rows for flag in row["anomaly_flags"].split(";")
        if flag not in {"", "NO_STATIC_SIGNAL"}
    )
    report = [
        "# 真实笔记内容异常初筛", "",
        f"- 扫描文档：{len(files)}",
        f"- JSON 解析失败：{parse_errors}",
        f"- 提取文本总字符数：{total_chars}",
        f"- 有异常信号的文档：{sum(row['anomaly_flags'] != 'NO_STATIC_SIGNAL' for row in doc_rows)}",
        f"- 段落级候选：{len(paragraph_findings)}",
        "", "## 信号分布", "",
        *[f"- {name}: {count}" for name, count in sorted(flag_counts.items())],
        "", "## 输出", "",
        "- content_anomaly_audit.csv：逐篇文本长度、段落数和异常信号。",
        "- paragraph_anomaly_audit.csv：重复段落和超长段落，保留原笔记路径及段落序号。",
        "", "## 判读边界", "",
        "- 很短/很长文本不自动等于内容缺失或异常；容器文档、图片笔记、长篇讲义都可能合理。",
        "- 完全重复段落可能来自原文引用、重复章节或导出结构，必须回到原始笔记核实。",
        "- 本工具不做语义相似度判断、不改写笔记，也不将候选标记为错误。",
    ]
    (output / "content_anomaly_audit.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"documents": len(files), "parse_errors": parse_errors,
            "paragraph_findings": len(paragraph_findings),
            "flagged_documents": sum(row["anomaly_flags"] != "NO_STATIC_SIGNAL" for row in doc_rows)}


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
