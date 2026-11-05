#!/usr/bin/env python3
"""Build a deterministic human-review queue from the locally generated asset candidate report.

Candidate filenames are discovery hints only. This tool never changes asset match
states and never claims that a candidate's contents match a SiYuan reference.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

REQUIRED_FIELDS = {
    "reference", "candidate_class", "occurrence_count", "candidate_status",
    "candidate_count", "candidate_paths", "document_paths", "titles",
    "candidate_basis", "manual_status", "manual_note", "content_evidence_reference",
}
ACTION_BY_STATUS = {
    "ONE_CANDIDATE": "INSPECT_SINGLE_CANDIDATE_CONTENT",
    "MULTIPLE_CANDIDATES": "COMPARE_CANDIDATE_CONTENTS",
    "NO_CANDIDATE": "SEARCH_ASSETS_BY_REFERENCE_AND_CONTEXT",
}
QUEUE_FIELDS = [
    "batch_id", "batch_position", "reference", "candidate_class",
    "occurrence_count", "candidate_status", "candidate_count",
    "candidate_paths", "document_paths", "titles", "recommended_action",
    "manual_status", "manual_note", "candidate_basis", "content_evidence_reference",
]


def read_candidates(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"候选报告缺少字段：{', '.join(sorted(missing))}")
        rows = list(reader)

    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        reference = (row.get("reference") or "").strip()
        if not reference:
            raise ValueError(f"候选报告第 {line} 行缺少 reference")
        if reference in seen:
            raise ValueError(f"候选报告存在重复引用：{reference}")
        seen.add(reference)

        status = row.get("candidate_status", "")
        if status not in ACTION_BY_STATUS:
            raise ValueError(f"{reference} 的 candidate_status 无效：{status}")
        try:
            count = int(row.get("candidate_count", ""))
            occurrences = int(row.get("occurrence_count", ""))
        except ValueError as exc:
            raise ValueError(f"{reference} 的候选数或引用次数不是整数") from exc
        paths = [item for item in row.get("candidate_paths", "").split(";") if item]
        if count < 0 or occurrences < 1 or count != len(paths):
            raise ValueError(f"{reference} 的候选数、路径列表或引用次数不一致")
        expected = "NO_CANDIDATE" if count == 0 else "ONE_CANDIDATE" if count == 1 else "MULTIPLE_CANDIDATES"
        if status != expected:
            raise ValueError(f"{reference} 的 candidate_status 与候选数量不一致")
        manual_status = row.get("manual_status")
        if manual_status not in {"NEEDS_INSPECTION", "CONFIRMED_MATCH", "NOT_MATCH", "UNRESOLVED"}:
            raise ValueError(f"{reference} 的 manual_status 无效：{manual_status}")
        if manual_status in {"CONFIRMED_MATCH", "NOT_MATCH"} and not (row.get("content_evidence_reference") or "").strip():
            raise ValueError(f"{reference} 已有附件内容核验结论但缺少 content_evidence_reference")
    return rows


def build_queue(candidates: list[dict[str, str]], output: Path, batch_size: int = 25) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    ordered = sorted(candidates, key=lambda row: row["reference"])
    for index, row in enumerate(ordered, start=1):
        batch = (index - 1) // batch_size + 1
        row["batch_id"] = f"ASSET-{batch:03d}"
        row["batch_position"] = str(index - (batch - 1) * batch_size)
        row["recommended_action"] = ACTION_BY_STATUS[row["candidate_status"]]

    output.mkdir(parents=True, exist_ok=True)
    with (output / "asset_review_queue.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=QUEUE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)

    counts = Counter(row["candidate_status"] for row in ordered)
    classes = Counter(row["candidate_class"] for row in ordered)
    total_occurrences = sum(int(row["occurrence_count"]) for row in ordered)
    total_candidates = sum(int(row["candidate_count"]) for row in ordered)
    batch_count = (len(ordered) + batch_size - 1) // batch_size
    report = [
        "# 附件候选人工复核队列",
        "",
        f"- 唯一引用数：{len(ordered)}",
        f"- 对应原始引用记录数：{total_occurrences}",
        f"- 候选文件路径总数（允许同一文件对应不同引用）：{total_candidates}",
        f"- 每批：{batch_size} 条；批次数：{batch_count}",
        f"- 单候选：{counts['ONE_CANDIDATE']}",
        f"- 多候选：{counts['MULTIPLE_CANDIDATES']}",
        f"- 无候选：{counts['NO_CANDIDATE']}",
        f"- 无扩展名引用：{classes['NO_EXTENSION_REFERENCE']}",
        f"- 图片引用：{classes['IMAGE_REFERENCE']}",
        "",
        "## 处理规则",
        "",
        "- 单候选：打开候选文件，核对实际图像/内容与引用上下文；文件名相同不构成确认。",
        "- 多候选：逐个比较候选内容，不能按排序或首个候选自动选择。",
        "- 无候选：结合文档上下文在本地 assets 中搜索；无结果也不能仅凭本表判定附件丢失。",
        "- CONFIRMED_MATCH / NOT_MATCH 必须附 content_evidence_reference，定位到内容核验记录；文件名、路径命中和 SHA-256 均不能替代内容核验。",
        "- 本队列按引用路径稳定排序，仅用于分批组织，不表示优先级或错误程度。",
        "",
        "## 候选类别",
        "",
        "| 类别 | 数量 |",
        "|---|---:|",
        f"| 无扩展名引用 | {classes['NO_EXTENSION_REFERENCE']} |",
        f"| 图片引用 | {classes['IMAGE_REFERENCE']} |",
        "",
        "详细项目见 `asset_review_queue.csv`。",
        "",
    ]
    (output / "asset_review_queue.md").write_text("\n".join(report), encoding="utf-8")
    return {
        "references": len(ordered),
        "occurrences": total_occurrences,
        "candidate_paths": total_candidates,
        "batches": batch_count,
        "one_candidate": counts["ONE_CANDIDATE"],
        "multiple_candidates": counts["MULTIPLE_CANDIDATES"],
        "no_candidate": counts["NO_CANDIDATE"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()
    result = build_queue(read_candidates(args.candidates), args.output, args.batch_size)
    print(result)


if __name__ == "__main__":
    main()
