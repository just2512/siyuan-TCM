#!/usr/bin/env python3
"""Extract dosage-like expressions from real notes as review candidates only.

No dose is normalized, interpreted, recommended, or judged medically correct.
Each match is tied to the source .sy path, paragraph ordinal, and character span.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from build_siyuan_catalog import extract_text

NUMERAL = r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万两半]+)"
UNIT = r"(?:毫克|毫升|克|公斤|千克|斤|两|钱|分|枚|片|粒|滴|升|合|盅|碗|杯|g|mg|ml|kg)"
DOSE_RE = re.compile(NUMERAL + r"\\s*" + UNIT, re.IGNORECASE)
# A bare number+unit is too noisy; require nearby medicinal/prescription context.
DOSE_CONTEXT_RE = re.compile(
    r"(?:药|方|煎|服|汤|丸|散|剂|煮|药材|药味|药物|剂量|每次|每日|一剂|桂枝|芍药|甘草|大枣|附子|人参|黄芪|当归|白术|茯苓|半夏|柴胡|麻黄|石膏|干姜|细辛|大黄|黄连|黄芩|陈皮|川芎)",
    re.IGNORECASE,
)
SPACE_RE = re.compile(r"\\s+")


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


def extract_paragraphs(root: Any):
    for node in walk_nodes(root):
        if node.get("Type") == "NodeParagraph":
            text = SPACE_RE.sub(" ", extract_text(node)).strip()
            if text:
                yield text


def build(root: Path, output: Path) -> dict[str, int]:
    files = sorted(p for p in root.rglob("*.sy")
                   if p.is_file() and "assets" not in p.parts and output not in p.parents)
    rows = []
    parse_errors = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_errors += 1
            continue
        for paragraph_index, paragraph in enumerate(extract_paragraphs(raw), start=1):
            for match in DOSE_RE.finditer(paragraph):
                left, right = max(0, match.start() - 80), min(len(paragraph), match.end() + 80)
                context = paragraph[left:right]
                if not DOSE_CONTEXT_RE.search(context):
                    continue
                rows.append({
                    "document": relative,
                    "paragraph_index": paragraph_index,
                    "character_start": match.start(),
                    "character_end": match.end(),
                    "matched_expression": match.group(0),
                    "context_excerpt": context,
                    "review_status": "NOT_REVIEWED",
                    "evidence_reference": "",
                    "review_note": "",
                })

    output.mkdir(parents=True, exist_ok=True)
    with (output / "dosage_expression_candidates.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        fields = [
            "document", "paragraph_index", "character_start", "character_end",
            "matched_expression", "context_excerpt", "review_status",
            "evidence_reference", "review_note",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = [
        "# 中医笔记剂量表达候选索引", "",
        f"- 扫描 .sy 文档：{len(files)}",
        f"- JSON 解析失败：{parse_errors}",
        f"- 剂量样式表达候选：{len(rows)}",
        "", "## 输出", "",
        "- dosage_expression_candidates.csv：每条表达保留原始笔记路径、段落序号、字符区间和上下文。",
        "", "## 使用边界", "",
        "- 先按数字+计量单位识别，再要求邻近上下文出现药物、方剂、煎服或剂量语境；仍然只是字符串模式初筛，不代表该表达就是药物剂量。",
        "- 古今单位、炮制、煎服法、剂型、体积/重量换算和上下文语义必须分别核验。",
        "- 不自动换算单位、不自动修改原文、不生成处方建议。",
        "- 所有记录初始状态为 NOT_REVIEWED；没有原始依据时不得填写已核验结论。",
    ]
    (output / "dosage_expression_candidates.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"documents": len(files), "parse_errors": parse_errors, "candidates": len(rows)}


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
