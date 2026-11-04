#!/usr/bin/env python3
"""Build an evidence-oriented work queue for bibliographic/source candidates.

This tool organizes review work only. It does not infer authorship, publication,
edition, source identity, or textual collation from filenames or candidate labels.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

ACTIONS = {
    "asset_file": "INSPECT_TITLE_PAGE_COPYRIGHT_PAGE_AND_PUBLICATION_DATA",
    "huangdi_neijing_chapter": "VERIFY_CHAPTER_AGAINST_IDENTIFIED_EDITION_AND_PAGE",
    "nihongxia_lecture": "VERIFY_ORIGINAL_LECTURE_SOURCE_AND_METADATA",
}
ALLOWED_STATUSES = {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"}
REQUIRED_FIELDS = {
    "candidate_category", "path", "candidate_note",
    "verification_status", "evidence_reference",
}
QUEUE_FIELDS = [
    "batch_id", "batch_position", "candidate_category", "path",
    "candidate_note", "verification_status", "evidence_reference",
    "required_evidence", "recommended_action",
]


def read_candidates(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"来源候选表缺少字段：{', '.join(sorted(missing))}")
        rows = list(reader)

    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        key = (row.get("path") or "").strip()
        if not key:
            raise ValueError(f"来源候选表第 {line} 行缺少 path")
        if key in seen:
            raise ValueError(f"来源候选表存在重复 path：{key}")
        seen.add(key)
        category = row.get("candidate_category", "")
        if category not in ACTIONS:
            raise ValueError(f"{key} 的候选类别无效：{category}")
        status = row.get("verification_status", "")
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"{key} 的 verification_status 无效：{status}")
        if status != "UNVERIFIED" and not (row.get("evidence_reference") or "").strip():
            raise ValueError(f"{key} 已有核验结论但缺少 evidence_reference")
    return rows


def build_queue(rows: list[dict[str, str]], output: Path, batch_size: int = 20) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    ordered = sorted(rows, key=lambda row: (row["candidate_category"], row["path"]))
    for index, row in enumerate(ordered, start=1):
        batch = (index - 1) // batch_size + 1
        row["batch_id"] = f"SOURCE-{batch:03d}"
        row["batch_position"] = str(index - (batch - 1) * batch_size)
        row["recommended_action"] = ACTIONS[row["candidate_category"]]
        row["required_evidence"] = {
            "asset_file": "扉页/版权页/目录页/出版信息/版本页及可定位页码",
            "huangdi_neijing_chapter": "明确版本的书名页、卷篇目录、对应正文页码",
            "nihongxia_lecture": "原始课程/讲座记录、讲者身份依据、日期或期次、可定位原文",
        }[row["candidate_category"]]

    output.mkdir(parents=True, exist_ok=True)
    with (output / "source_review_queue.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=QUEUE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)

    categories = Counter(row["candidate_category"] for row in ordered)
    statuses = Counter(row["verification_status"] for row in ordered)
    batch_count = (len(ordered) + batch_size - 1) // batch_size
    report = [
        "# 来源资料候选核验队列",
        "",
        f"- 候选总数：{len(ordered)}",
        f"- 每批：{batch_size} 条；批次数：{batch_count}",
        f"- 当前 UNVERIFIED：{statuses['UNVERIFIED']}",
        f"- 已核验 VERIFIED：{statuses['VERIFIED']}",
        f"- 存在冲突 CONFLICT：{statuses['CONFLICT']}",
        f"- 尚无法确定 UNRESOLVED：{statuses['UNRESOLVED']}",
        "",
        "## 候选类别",
        "",
        "| 类别 | 数量 |",
        "|---|---:|",
        f"| 本地附件文件 | {categories['asset_file']} |",
        f"| 《黄帝内经》篇章候选 | {categories['huangdi_neijing_chapter']} |",
        f"| 课程/讲座来源候选 | {categories['nihongxia_lecture']} |",
        "",
        "## 核验边界",
        "",
        "- 候选类别和文件名不是书目证据，不据此推断作者、讲者、出版机构、版本或底本。",
        "- 只有能定位到具体原始材料及页码/期次的证据，才允许更新为 VERIFIED。",
        "- 来源身份确认与版本确认、文本校勘是不同结论；确认来源不代表已经完成校勘。",
        "- 缺少证据或证据冲突时，分别保留 UNVERIFIED、UNRESOLVED 或 CONFLICT。",
        "- 队列按类别和路径稳定排序，仅用于分批，不表示优先级或结论。",
        "",
        "详细项目见 `source_review_queue.csv`。",
        "",
    ]
    (output / "source_review_queue.md").write_text("\n".join(report), encoding="utf-8")
    return {
        "candidates": len(ordered),
        "batches": batch_count,
        "unverified": statuses["UNVERIFIED"],
        "verified": statuses["VERIFIED"],
        "conflict": statuses["CONFLICT"],
        "unresolved": statuses["UNRESOLVED"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    print(build_queue(read_candidates(args.candidates), args.output, args.batch_size))


if __name__ == "__main__":
    main()
