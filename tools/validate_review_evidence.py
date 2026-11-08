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
    "evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method",
    "source_reference", "locator", "observation", "reviewer", "reviewed_at",
    "context_reference", "content_basis",
]
SUBJECT_TYPES = {
    "document", "source_candidate", "asset_reference",
    "topic_decision", "title_decision", "empty_body_decision",
}
INSPECTION_METHODS = {"HUMAN_DIRECT", "PROGRAMMATIC_STRUCTURE", "AUTOMATED_EXTRACTION", "SECONDARY_REFERENCE"}
AUTOMATED_METHODS = {"PROGRAMMATIC_STRUCTURE", "AUTOMATED_EXTRACTION"}
HUMAN_ACTOR_METHODS = {"HUMAN_DIRECT", "SECONDARY_REFERENCE"}
EVIDENCE_KINDS = {
    "original_sy", "asset_content", "title_page", "copyright_page",
    "table_of_contents", "body_page", "lecture_record", "audio_timestamp",
    "catalogue_record", "other_primary_source",
}
ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")
OPTIONAL_FIELDS = {"context_reference", "content_basis"}
ASSET_CONTENT_BASES = {
    "VISUAL_CONTENT_AND_NOTE_CONTEXT",
    "TEXT_CONTENT_AND_NOTE_CONTEXT",
    "DOCUMENT_PAGE_AND_NOTE_CONTEXT",
    "MULTIMODAL_CONTENT_AND_NOTE_CONTEXT",
}


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
            if field in OPTIONAL_FIELDS:
                continue
            if not values[field]:
                raise ValueError(f"{evidence_id} 缺少必填字段：{field}")
        if values["subject_type"] not in SUBJECT_TYPES:
            raise ValueError(f"{evidence_id} subject_type 无效：{values['subject_type']}")
        if values["evidence_kind"] not in EVIDENCE_KINDS:
            raise ValueError(f"{evidence_id} evidence_kind 无效：{values['evidence_kind']}")
        if values["inspection_method"] not in INSPECTION_METHODS:
            raise ValueError(f"{evidence_id} inspection_method 无效：{values['inspection_method']}")
        automated_actor = values["reviewer"].startswith(("automated-", "system-"))
        if values["inspection_method"] in AUTOMATED_METHODS and not automated_actor:
            raise ValueError(f"{evidence_id} 非人工检查记录不得伪装为人工核验人")
        if values["inspection_method"] in HUMAN_ACTOR_METHODS and automated_actor:
            raise ValueError(f"{evidence_id} {values['inspection_method']} 不得使用自动化核验人标识")
        source_ref = values["source_reference"].replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", source_ref) or source_ref.startswith(("/", "//")):
            raise ValueError(f"{evidence_id} 不得记录本机绝对路径")
        context_ref = values["context_reference"].replace("\\", "/")
        if context_ref and (
            re.match(r"^[A-Za-z]:/", context_ref)
            or context_ref.startswith(("/", "//"))
            or ".." in context_ref.split("/")
        ):
            raise ValueError(f"{evidence_id} context_reference 不得使用绝对路径或路径穿越")
        if values["content_basis"] and values["content_basis"] not in ASSET_CONTENT_BASES:
            raise ValueError(f"{evidence_id} content_basis 无效：{values['content_basis']}")
        if values["evidence_kind"] == "asset_content":
            if values["subject_type"] != "asset_reference":
                raise ValueError(f"{evidence_id} asset_content 的 subject_type 必须为 asset_reference")
            if values["inspection_method"] != "HUMAN_DIRECT":
                raise ValueError(f"{evidence_id} asset_content 必须来自 HUMAN_DIRECT 检查")
            subject_key = values["subject_key"].replace("\\", "/")
            source_reference = values["source_reference"].replace("\\", "/")
            for label, reference in (("subject_key", subject_key), ("source_reference", source_reference)):
                if (
                    not reference.startswith("assets/")
                    or reference.startswith(("/", "//"))
                    or ".." in reference.split("/")
                ):
                    raise ValueError(
                        f"{evidence_id} asset_content 的 {label} 必须使用 assets/ 下的安全相对附件路径"
                    )
            context_document, separator, context_anchor = context_ref.partition("#")
            if (
                not separator or not context_anchor
                or not context_document.endswith(".sy")
            ):
                raise ValueError(f"{evidence_id} asset_content 缺少原始 .sy 上下文/块定位")
            if values["content_basis"] not in ASSET_CONTENT_BASES:
                raise ValueError(f"{evidence_id} asset_content 缺少有效 content_basis")
        elif values["content_basis"]:
            raise ValueError(f"{evidence_id} 只有 asset_content 可以填写 content_basis")
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
