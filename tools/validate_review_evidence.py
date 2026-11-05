#!/usr/bin/env python3
"""Validate the shared human-review evidence ledger.

An evidence row is a locator and an audit record, not proof that the underlying
source is authentic. Reviewers must inspect the referenced original material.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

FIELDS = [
    "evidence_id", "subject_type", "subject_key", "evidence_kind",
    "source_reference", "locator", "observation", "reviewer", "reviewed_at",
]
SUBJECT_TYPES = {
    "document", "source_candidate", "asset_reference",
    "topic_decision", "title_decision", "empty_body_decision",
}
EVIDENCE_KINDS = {
    "original_sy", "asset_content", "title_page", "copyright_page",
    "table_of_contents", "body_page", "lecture_record", "audio_timestamp",
    "catalogue_record", "other_primary_source",
}
ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")


def validate_ledger(path: Path) -> dict[str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"证据台账缺少字段：{', '.join(sorted(missing))}")
        rows = list(reader)

    seen: set[str] = set()
    subjects: set[tuple[str, str]] = set()
    kinds = Counter()
    for line, row in enumerate(rows, start=2):
        values = {field: (row.get(field) or "").strip() for field in FIELDS}
        evidence_id = values["evidence_id"]
        if not ID_PATTERN.fullmatch(evidence_id):
            raise ValueError(f"第 {line} 行 evidence_id 格式无效：{evidence_id!r}")
        if evidence_id in seen:
            raise ValueError(f"证据 ID 重复：{evidence_id}")
        seen.add(evidence_id)
        for field in FIELDS[1:]:
            if not values[field]:
                raise ValueError(f"{evidence_id} 缺少必填字段：{field}")
        if values["subject_type"] not in SUBJECT_TYPES:
            raise ValueError(f"{evidence_id} subject_type 无效：{values['subject_type']}")
        if values["evidence_kind"] not in EVIDENCE_KINDS:
            raise ValueError(f"{evidence_id} evidence_kind 无效：{values['evidence_kind']}")
        source_ref = values["source_reference"].replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", source_ref) or source_ref.startswith(("/", "//")):
            raise ValueError(f"{evidence_id} 不得记录本机绝对路径")
        try:
            date.fromisoformat(values["reviewed_at"])
        except ValueError as exc:
            raise ValueError(f"{evidence_id} reviewed_at 必须为 YYYY-MM-DD") from exc
        subject = (values["subject_type"], values["subject_key"])
        subjects.add(subject)
        kinds[values["evidence_kind"]] += 1

    return {"evidence_rows": len(rows), "unique_subjects": len(subjects), **dict(kinds)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    print(validate_ledger(args.ledger))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
