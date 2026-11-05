#!/usr/bin/env python3
"""Build a heading/section navigation index from actual SiYuan .sy exports."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from build_siyuan_catalog import extract_text


def walk_content_blocks(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from walk_content_blocks(item)
    elif isinstance(value, dict):
        node_type = value.get("Type")
        if node_type in {"NodeHeading", "NodeParagraph"}:
            yield value
        for key, child in value.items():
            if key not in {"Properties", "IAL"} and isinstance(child, (dict, list)):
                yield from walk_content_blocks(child)


def build_sections(root: Any, document: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    preface: dict[str, Any] = {
        "document": document, "section_index": 0, "heading_block_id": "",
        "heading_level": 0, "heading_title": "[未分节正文]",
        "paragraph_count": 0, "body_characters": 0, "body_parts": [],
    }
    current = preface

    for block in walk_content_blocks(root.get("Children", []) if isinstance(root, dict) else []):
        if block.get("Type") == "NodeHeading":
            heading_text = " ".join(extract_text(block).split())
            try:
                level = int(block.get("HeadingLevel", 0))
            except (TypeError, ValueError):
                level = 0
            if current is preface and preface["paragraph_count"]:
                sections.append(preface)
            while stack and (level == 0 or stack[-1]["heading_level"] >= level):
                stack.pop()
            section = {
                "document": document,
                "section_index": len(sections) + len(stack) + 1,
                "heading_block_id": str(block.get("ID", "")),
                "heading_level": level,
                "heading_title": heading_text,
                "paragraph_count": 0,
                "body_characters": 0,
                "body_parts": [],
            }
            sections.append(section)
            stack.append(section)
            current = section
        elif block.get("Type") == "NodeParagraph":
            paragraph = " ".join(extract_text(block).split())
            if paragraph:
                current = stack[-1] if stack else preface
                current["paragraph_count"] += 1
                current["body_characters"] += len(paragraph)
                if len(current["body_parts"]) < 3:
                    current["body_parts"].append(paragraph[:400])

    if current is preface and preface["paragraph_count"] and preface not in sections:
        sections.insert(0, preface)

    rows = []
    for section in sections:
        rows.append({
            "document": section["document"],
            "section_index": section["section_index"],
            "heading_block_id": section["heading_block_id"],
            "heading_level": section["heading_level"],
            "heading_title": section["heading_title"],
            "paragraph_count": section["paragraph_count"],
            "body_characters": section["body_characters"],
            "body_excerpt": " ... ".join(section["body_parts"]),
        })
    return rows


def build(root: Path, output: Path) -> dict[str, int]:
    files = sorted(p for p in root.rglob("*.sy")
                   if p.is_file() and "assets" not in p.parts and output not in p.parents)
    rows = []
    parse_errors = 0
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_errors += 1
            continue
        rows.extend(build_sections(data, path.relative_to(root).as_posix()))

    output.mkdir(parents=True, exist_ok=True)
    with (output / "section_index.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = [
            "document", "section_index", "heading_block_id", "heading_level",
            "heading_title", "paragraph_count", "body_characters", "body_excerpt",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = [
        "# 真实笔记章节级索引", "",
        f"- 扫描文档：{len(files)}",
        f"- JSON 解析失败：{parse_errors}",
        f"- 章节/未分节正文记录：{len(rows)}",
        f"- 含正文段落的章节：{sum(int(row['paragraph_count']) > 0 for row in rows)}",
        "", "## 输出", "",
        "- section_index.csv：按原笔记路径、标题块 ID、标题层级和段落顺序建立章节导航，保留正文摘要。",
        "", "## 判读边界", "",
        "- 该索引只建立可检索的章节定位，不重排或修改原文。",
        "- 表格、HTML、图片、音视频等非 NodeParagraph 内容仍需独立的块类型解析策略。",
        "- 标题层级以导出数据中的 HeadingLevel 为准；缺失层级保留为 0，不推测。",
        "- body_excerpt 仅用于导航，完整内容仍以原始 .sy 为准。",
    ]
    (output / "section_index.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"documents": len(files), "parse_errors": parse_errors, "sections": len(rows)}


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
