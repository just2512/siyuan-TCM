#!/usr/bin/env python3
"""Build independent evidence queues for source identity, edition, and collation."""
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
ALLOWED_STATUSES = {"UNVERIFIED", "PARTIAL", "VERIFIED", "CONFLICT", "UNRESOLVED"}
STATUS_FIELDS = {
    "source_identity_status": "source_identity_evidence_reference",
    "source_version_status": "source_version_evidence_reference",
    "collation_status": "collation_evidence_reference",
}
REQUIRED_FIELDS = {
    "candidate_category", "path", "candidate_note",
    *STATUS_FIELDS.keys(), *STATUS_FIELDS.values(),
}

UNVERIFIED_IDENTITY_CLAIMS = (
    "身份可从文件名确认",
    "身份可确认",
    "身份已经确认",
    "身份已确认",
)
QUEUE_FIELDS = [
    "batch_id", "batch_position", "candidate_category", "path", "candidate_note",
    "source_identity_status", "source_identity_evidence_reference",
    "source_version_status", "source_version_evidence_reference",
    "collation_status", "collation_evidence_reference",
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
        if row.get("source_identity_status") == "UNVERIFIED" and any(
            claim in (row.get("candidate_note") or "")
            for claim in UNVERIFIED_IDENTITY_CLAIMS
        ):
            raise ValueError(
                f"{key} 的 candidate_note 将文件名/关键词候选线索表述为已确认来源身份，"
                "但 source_identity_status 仍为 UNVERIFIED"
            )
        for status_field, evidence_field in STATUS_FIELDS.items():
            status = (row.get(status_field) or "").strip()
            if status not in ALLOWED_STATUSES:
                raise ValueError(f"{key} 的 {status_field} 无效：{status}")
            if status != "UNVERIFIED" and not (row.get(evidence_field) or "").strip():
                raise ValueError(f"{key} 的 {status_field} 已有结论但缺少 {evidence_field}")
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
            "asset_file": "来源身份：书名页/版权页；版本：版次/印次/目录；校勘：明确版本的对应正文页",
            "huangdi_neijing_chapter": "来源身份：所据底本；版本：卷篇目录/版本页；校勘：对应正文页码及异文",
            "nihongxia_lecture": "来源身份：原始课程载体/讲者依据；版本：期次/日期；校勘：原始录音时间戳或原文定位",
        }[row["candidate_category"]]

    output.mkdir(parents=True, exist_ok=True)
    with (output / "source_review_queue.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=QUEUE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)

    lines = ["# 来源资料候选核验队列", "", f"- 候选总数：{len(ordered)}",
             f"- 每批：{batch_size} 条；批次数：{(len(ordered) + batch_size - 1) // batch_size}"]
    totals: dict[str, int] = {"candidates": len(ordered), "batches": (len(ordered) + batch_size - 1) // batch_size}
    for field in STATUS_FIELDS:
        counts = Counter(row[field] for row in ordered)
        lines += ["", f"## {field}", ""]
        for status in sorted(ALLOWED_STATUSES):
            lines.append(f"- {status}: {counts[status]}")
            totals[f"{field}_{status.lower()}"] = counts[status]
    lines += [
        "", "## 核验边界", "",
        "- 来源身份、版本身份、文本校勘是三个独立结论，必须分别填写状态和证据引用。",
        "- 来源身份 VERIFIED 不代表版本 VERIFIED；版本 VERIFIED 不代表校勘完成。",
        "- PARTIAL 仅用于已直接检查原始材料且有页码/段落/期次/时间戳定位的部分核验。",
        "- 文件名、标题、关键词和自动提取片段不能支撑任何 VERIFIED 结论。",
        "- 只有 HUMAN_DIRECT 类型证据可以通过人工结论交叉校验。",
        "- 冲突和未解决状态必须保留，不得为了清零而强行统一。",
        "", "详细项目见 `source_review_queue.csv`。", "",
    ]
    (output / "source_review_queue.md").write_text("\n".join(lines), encoding="utf-8")
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()
    print(build_queue(read_candidates(args.candidates), args.output, args.batch_size))


if __name__ == "__main__":
    main()
