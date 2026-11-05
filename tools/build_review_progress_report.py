#!/usr/bin/env python3
"""Build a conservative, machine-counted human-review progress report."""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

DECISION_COLUMNS = (
    "title_review_status", "source_status", "source_version_status",
    "collation_status", "topic_review_status", "empty_body_status",
)
PENDING_VALUES = {"", "NOT_REVIEWED", "UNVERIFIED", "NEEDS_INSPECTION",
                  "NEEDS_SOURCE_INSPECTION", "PENDING"}
UNRESOLVED_VALUES = {"UNRESOLVED"}
CONFLICT_VALUES = {"CONFLICT"}
ACTIVE_VALUES = {
    "title_review_status": {"CONFIRMED", "RENAME_REQUIRED", "UNRESOLVED"},
    "source_status": {"VERIFIED", "CONFLICT", "UNRESOLVED"},
    "source_version_status": {"VERIFIED", "CONFLICT", "UNRESOLVED"},
    "collation_status": {"COLLATION_CONFIRMED", "CORRECTION_REQUIRED", "UNRESOLVED"},
    "topic_review_status": {"CONFIRMED", "REMOVE_TOPIC", "ADD_TOPIC", "SPLIT_REQUIRED", "UNRESOLVED"},
    "empty_body_status": {"SOURCE_EMPTY_CONFIRMED", "LOCAL_SOURCE_HAS_CONTENT", "RESTORE_REQUIRED", "UNRESOLVED"},
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [{k: (v or "").strip() for k, v in row.items() if k}
                for row in csv.DictReader(stream)]


def count_column(rows: list[dict[str, str]], column: str) -> Counter:
    return Counter((row.get(column) or "").strip() or "NOT_REVIEWED" for row in rows)


def render_report(decisions: Path, sources: Path, assets: Path,
                  evidence: Path, topics: Path | None = None,
                  titles: Path | None = None, empty_body: Path | None = None) -> str:
    decision_rows = read_rows(decisions)
    source_rows = read_rows(sources)
    asset_rows = read_rows(assets)
    evidence_rows = read_rows(evidence)
    topic_rows = read_rows(topics) if topics else []
    title_rows = read_rows(titles) if titles else []
    empty_rows = read_rows(empty_body) if empty_body else []

    lines = [
        "# 人工核验进度报告", "",
        "> 本报告只汇总持久化表格中的状态，不读取原始 .sy 或附件内容，不判定内容真实性。CI 通过不代表人工核验完成。", "",
        "## 人工决策表", "",
        "| 核验域 | 记录数 | 状态分布 |", "|---|---:|---|",
    ]
    for column in DECISION_COLUMNS:
        counts = count_column(decision_rows, column)
        rendered = "；".join(f"{status}: {counts[status]}" for status in sorted(counts))
        lines.append(f"| {column} | {len(decision_rows)} | {rendered} |")

    lines += ["", "## 原始人工复核队列", ""]
    for label, rows, column in (
        ("逐文档—主题审计", topic_rows, "review_status"),
        ("标题风险审计", title_rows, "review_status"),
        ("空正文候选", empty_rows, "review_status"),
    ):
        if rows:
            counts = count_column(rows, column)
            rendered = "；".join(f"{status}: {counts[status]}" for status in sorted(counts))
            lines.append(f"- {label}：{len(rows)} 条；{rendered}")
        else:
            lines.append(f"- {label}：未提供审计队列输入")

    lines += ["", "## 来源候选", "", f"- 候选记录：{len(source_rows)}"]
    for status_field in ("source_identity_status", "source_version_status", "collation_status"):
        counts = count_column(source_rows, status_field)
        lines.append(f"- {status_field}: " + "；".join(
            f"{status}: {counts[status]}" for status in sorted(counts)
        ))

    lines += ["", "## 附件引用", "", f"- 唯一引用记录：{len(asset_rows)}"]
    asset_counts = count_column(asset_rows, "manual_status")
    lines += [f"- {status}: {count}" for status, count in sorted(asset_counts.items())]

    lines += ["", "## 证据台账", "", f"- 证据记录：{len(evidence_rows)}"]
    evidence_counts = count_column(evidence_rows, "evidence_kind") if evidence_rows else Counter()
    method_counts = count_column(evidence_rows, "inspection_method") if evidence_rows else Counter()
    if evidence_counts:
        lines += [f"- 证据类型 {kind}: {count}" for kind, count in sorted(evidence_counts.items())]
        lines += [f"- 检查方式 {method}: {count}" for method, count in sorted(method_counts.items())]
    else:
        lines.append("- 当前没有证据记录。")

    lines += [
        "", "## 状态解释", "",
        "- 空白状态按 NOT_REVIEWED 统计；不得把空白当作通过。",
        "- UNVERIFIED / NOT_REVIEWED / NEEDS_INSPECTION / NEEDS_SOURCE_INSPECTION / PENDING 均属于未完成。",
        "- UNRESOLVED 和 CONFLICT 单独保留，不并入已核验。",
        "- 本报告不把 PARTIAL 等同 VERIFIED，也不将机器扫描状态转换为人工结论。",
        "- 每个有效人工结论仍须通过证据台账结构校验和跨表引用校验，并由复核者确认原始材料确已检查。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--topics", type=Path)
    parser.add_argument("--titles", type=Path)
    parser.add_argument("--empty-body", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = render_report(args.decisions, args.sources, args.assets, args.evidence,
                           args.topics, args.titles, args.empty_body)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Review progress report written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
