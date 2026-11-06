#!/usr/bin/env python3
"""Cross-check evidence IDs referenced by human decision tables.

This validates referential integrity and subject ownership only. It cannot prove
that a cited source was actually inspected or that the observation is correct.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

LEDGER_FIELDS = {"evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method", "context_reference", "content_basis"}
DECISION_FIELDS = {
    "document", "title_review_status", "source_status", "source_version_status",
    "collation_status", "topic_review_status", "empty_body_status",
    "evidence_reference",
}
SOURCE_FIELDS = {
    "path", "source_identity_status", "source_identity_evidence_reference",
    "source_version_status", "source_version_evidence_reference",
    "collation_status", "collation_evidence_reference",
}
ASSET_FIELDS = {"reference", "document_paths", "manual_status", "content_evidence_reference"}
DECISION_ACTIVE = {
    "title_review_status": {"CONFIRMED", "RENAME_REQUIRED", "UNRESOLVED"},
    "source_status": {"PARTIAL", "VERIFIED", "CONFLICT", "UNRESOLVED"},
    "source_version_status": {"PARTIAL", "VERIFIED", "CONFLICT", "UNRESOLVED"},
    "collation_status": {"COLLATION_CONFIRMED", "CORRECTION_REQUIRED", "UNRESOLVED"},
    "topic_review_status": {"CONFIRMED", "REMOVE_TOPIC", "ADD_TOPIC", "SPLIT_REQUIRED", "UNRESOLVED"},
    "empty_body_status": {"SOURCE_EMPTY_CONFIRMED", "LOCAL_SOURCE_HAS_CONTENT", "RESTORE_REQUIRED", "UNRESOLVED"},
}
DECISION_EVIDENCE_KINDS = {
    "title_review_status": {"original_sy"},
    "source_status": {"title_page", "copyright_page", "catalogue_record", "lecture_record", "audio_timestamp", "other_primary_source"},
    "source_version_status": {"title_page", "copyright_page", "table_of_contents", "catalogue_record", "lecture_record", "audio_timestamp", "other_primary_source"},
    "collation_status": {"original_sy", "table_of_contents", "body_page", "lecture_record", "audio_timestamp", "other_primary_source"},
    "topic_review_status": {"original_sy"},
    "empty_body_status": {"original_sy"},
}
SOURCE_CONCLUSION_FIELDS = {
    "source_identity_status": ("source_identity_evidence_reference", DECISION_EVIDENCE_KINDS["source_status"]),
    "source_version_status": ("source_version_evidence_reference", DECISION_EVIDENCE_KINDS["source_version_status"]),
    "collation_status": ("collation_evidence_reference", DECISION_EVIDENCE_KINDS["collation_status"]),
}
ASSET_EVIDENCE_KINDS = {"asset_content"}
ASSET_CONTENT_BASES = {
    "VISUAL_CONTENT_AND_NOTE_CONTEXT",
    "TEXT_CONTENT_AND_NOTE_CONTEXT",
    "DOCUMENT_PAGE_AND_NOTE_CONTEXT",
    "MULTIMODAL_CONTENT_AND_NOTE_CONTEXT",
}
DECISION_SUBJECTS = {
    "title_review_status": {"document", "title_decision"},
    "source_status": {"document", "source_candidate"},
    "source_version_status": {"document", "source_candidate"},
    "collation_status": {"document", "source_candidate"},
    "topic_review_status": {"document", "topic_decision"},
    "empty_body_status": {"document", "empty_body_decision"},
}


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} 缺少字段：{', '.join(sorted(missing))}")
        return [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]


def evidence_tokens(value: str, context: str) -> list[str]:
    tokens = [part.strip() for part in value.split(";") if part.strip()]
    if not tokens:
        raise ValueError(f"{context} 缺少 evidence ID（多个 ID 使用分号分隔）")
    if len(tokens) != len(set(tokens)):
        raise ValueError(f"{context} 的 evidence ID 重复")
    return tokens


def validate_references(ledger_path: Path, decisions_path: Path | None = None,
                        sources_path: Path | None = None, assets_path: Path | None = None) -> dict[str, int]:
    ledger_rows = read_csv(ledger_path, LEDGER_FIELDS)
    ledger: dict[str, dict[str, str]] = {}
    for line, row in enumerate(ledger_rows, start=2):
        evidence_id = row["evidence_id"]
        if not evidence_id:
            raise ValueError(f"证据台账第 {line} 行 evidence_id 为空")
        if evidence_id in ledger:
            raise ValueError(f"证据 ID 重复：{evidence_id}")
        ledger[evidence_id] = row

    counts = Counter({
        "validated_evidence_references": 0,
        "decision_conclusions": 0,
        "source_conclusions": 0,
        "asset_conclusions": 0,
    })
    def check(ids: list[str], expected_key: str, allowed_types: set[str],
              allowed_kinds: set[str], context: str,
              context_documents: set[str] | None = None) -> None:
        for evidence_id in ids:
            record = ledger.get(evidence_id)
            if record is None:
                raise ValueError(f"{context} 引用了不存在的证据 ID：{evidence_id}")
            if record["subject_key"] != expected_key:
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 对象不匹配："
                    f"期望 {expected_key!r}，实际 {record['subject_key']!r}"
                )
            if record["subject_type"] not in allowed_types:
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 对象类型不匹配："
                    f"{record['subject_type']} 不属于 {sorted(allowed_types)}"
                )
            if record["evidence_kind"] not in allowed_kinds:
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 证据类型不匹配："
                    f"{record['evidence_kind']} 不属于 {sorted(allowed_kinds)}"
                )
            if record["inspection_method"] != "HUMAN_DIRECT":
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 不是人工直接核验记录："
                    f"{record['inspection_method']}"
                )
            if record["evidence_kind"] == "asset_content":
                context_reference = record["context_reference"].replace("\\", "/")
                context_document, separator, context_anchor = context_reference.partition("#")
                if (
                    not separator or not context_anchor
                    or not context_document.endswith(".sy")
                    or context_reference.startswith(("/", "//"))
                    or ".." in context_reference.split("/")
                ):
                    raise ValueError(f"{context} 的附件内容证据 {evidence_id} 缺少安全的原始 .sy 上下文/块定位")
                if context_documents is not None and context_document not in context_documents:
                    raise ValueError(
                        f"{context} 的附件内容证据 {evidence_id} 上下文文档不属于该附件引用的文档集合："
                        f"{context_document}"
                    )
                source_reference = (record.get("source_reference") or "").replace("\\", "/")
                if (
                    not source_reference.startswith("assets/")
                    or source_reference.startswith(("/", "//"))
                    or ".." in source_reference.split("/")
                ):
                    raise ValueError(
                        f"{context} 的附件内容证据 {evidence_id} 必须引用 assets/ 下的安全相对附件路径"
                    )
                if record["content_basis"] not in ASSET_CONTENT_BASES:
                    raise ValueError(f"{context} 的附件内容证据 {evidence_id} 缺少有效 content_basis")
            counts["validated_evidence_references"] += 1

    def check_decision(ids: list[str], expected_key: str,
                       fields: list[str], context: str) -> None:
        allowed_types = set().union(*(DECISION_SUBJECTS[field] for field in fields))
        allowed_kinds = set().union(*(DECISION_EVIDENCE_KINDS[field] for field in fields))
        records = []
        for evidence_id in ids:
            record = ledger.get(evidence_id)
            if record is None:
                raise ValueError(f"{context} 引用了不存在的证据 ID：{evidence_id}")
            if record["subject_key"] != expected_key:
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 对象不匹配："
                    f"期望 {expected_key!r}，实际 {record['subject_key']!r}"
                )
            if record["subject_type"] not in allowed_types:
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 对象类型不匹配："
                    f"{record['subject_type']} 不属于 {sorted(allowed_types)}"
                )
            if record["evidence_kind"] not in allowed_kinds:
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 证据类型不匹配："
                    f"{record['evidence_kind']} 不属于 {sorted(allowed_kinds)}"
                )
            if record["inspection_method"] != "HUMAN_DIRECT":
                raise ValueError(
                    f"{context} 的证据 {evidence_id} 不是人工直接核验记录："
                    f"{record['inspection_method']}"
                )
            records.append(record)
        for field in fields:
            if not any(
                record["subject_type"] in DECISION_SUBJECTS[field]
                and record["evidence_kind"] in DECISION_EVIDENCE_KINDS[field]
                for record in records
            ):
                raise ValueError(f"{context} {field} 缺少与结论域匹配的 HUMAN_DIRECT 证据")
        counts["validated_evidence_references"] += len(records)

    if decisions_path:
        for line, row in enumerate(read_csv(decisions_path, DECISION_FIELDS), start=2):
            document = row["document"]
            active_fields = [
                field for field, active in DECISION_ACTIVE.items()
                if row[field] in active
            ]
            if not active_fields:
                continue
            ids = evidence_tokens(row["evidence_reference"], f"决策表第 {line} 行 {document}")
            check_decision(ids, document, active_fields, document)
            counts["decision_conclusions"] += len(active_fields)

    if sources_path:
        for line, row in enumerate(read_csv(sources_path, SOURCE_FIELDS), start=2):
            for status_field, (evidence_field, allowed_kinds) in SOURCE_CONCLUSION_FIELDS.items():
                if row[status_field] == "UNVERIFIED":
                    continue
                ids = evidence_tokens(row[evidence_field], f"来源表第 {line} 行 {row['path']} {status_field}")
                check(ids, row["path"], {"source_candidate"}, allowed_kinds, f"{row['path']} {status_field}")
                counts["source_conclusions"] += 1

    if assets_path:
        for line, row in enumerate(read_csv(assets_path, ASSET_FIELDS), start=2):
            if row["manual_status"] not in {"CONFIRMED_MATCH", "NOT_MATCH"}:
                continue
            ids = evidence_tokens(row["content_evidence_reference"], f"附件队列第 {line} 行 {row['reference']}")
            context_documents = {
                item.strip() for item in row["document_paths"].split(";") if item.strip()
            }
            if not context_documents:
                raise ValueError(f"附件队列第 {line} 行 {row['reference']} 缺少关联原始 .sy 文档路径")
            check(
                ids, row["reference"], {"asset_reference"}, ASSET_EVIDENCE_KINDS,
                f"{row['reference']} manual_status", context_documents=context_documents,
            )
            counts["asset_conclusions"] += 1

    counts["evidence_records"] = len(ledger)
    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--assets", type=Path)
    args = parser.parse_args()
    print(validate_references(args.ledger, args.decisions, args.sources, args.assets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
