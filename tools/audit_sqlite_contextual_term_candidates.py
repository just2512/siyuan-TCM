#!/usr/bin/env python3
"""Exhaustively validate SQLite contextual-term evidence against source blocks."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from audit_report import write_audit_report

from build_contextual_term_candidates import RULE_IDS_BY_TYPE
from build_unclassified_term_candidates import candidate_id


def source_unit_id(document: str, source_sha256: str, tree_position: str, block_id: str) -> str:
    raw = "\0".join((document, source_sha256, tree_position, block_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audit(database_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        metadata = dict(connection.execute("SELECT key, value FROM index_metadata"))
        expected_count = connection.execute(
            "SELECT COUNT(*) FROM contextual_term_type_candidates"
        ).fetchone()[0]
        if ("contextual_term_type_candidates" not in metadata
            or int(metadata["contextual_term_type_candidates"]) != expected_count):
            raise ValueError(
                "contextual term metadata count mismatch: "
                f"metadata={metadata.get('contextual_term_type_candidates')!r}, actual={expected_count}"
            )
        query = """
            SELECT t.candidate_id, t.term, t.candidate_type, t.rule_id,
                   t.evidence_document, t.source_sha256, t.tree_position,
                   COALESCE(t.block_id, '') AS block_id, t.unit_id,
                   t.character_start, t.character_end, t.evidence_start,
                   t.evidence_text, t.classification_status,
                   b.content_text
            FROM contextual_term_type_candidates t
            LEFT JOIN content_blocks b
              ON b.document = t.evidence_document
             AND b.source_sha256 = t.source_sha256
             AND b.tree_position = t.tree_position
             AND COALESCE(b.block_id, '') = COALESCE(t.block_id, '')
            ORDER BY t.candidate_id, t.candidate_type, t.rule_id, t.unit_id,
                     t.character_start, t.character_end
        """
        counts: Counter[str] = Counter()
        checked = 0
        for row in connection.execute(query):
            key = (row["candidate_id"], row["candidate_type"], row["rule_id"],
                   row["unit_id"], row["character_start"], row["character_end"])
            if not all((row["candidate_id"], row["term"], row["candidate_type"],
                        row["rule_id"], row["evidence_document"], row["source_sha256"],
                        row["tree_position"], row["unit_id"], row["evidence_text"])):
                raise ValueError(f"contextual term candidate has empty identity/provenance: {key}")
            if row["candidate_id"] != candidate_id(row["term"]):
                raise ValueError(f"contextual term candidate ID/term identity mismatch: {key}")
            if row["candidate_type"] not in RULE_IDS_BY_TYPE:
                raise ValueError(f"unsupported contextual term type: {row['candidate_type']}")
            if row["rule_id"] not in RULE_IDS_BY_TYPE[row["candidate_type"]]:
                raise ValueError(f"contextual term rule/type mismatch: {key}")
            if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                raise ValueError(f"unsafe contextual term classification status: {key}")
            expected_unit = source_unit_id(
                row["evidence_document"], row["source_sha256"], row["tree_position"], row["block_id"]
            )
            if row["unit_id"] != expected_unit:
                raise ValueError(f"contextual term unit_id/source locator mismatch: {key}")
            if row["content_text"] is None:
                raise ValueError(f"contextual term source locator cannot be resolved: {key}")
            source_text = row["content_text"]
            start, end = row["character_start"], row["character_end"]
            evidence_start = row["evidence_start"]
            evidence_end = evidence_start + len(row["evidence_text"])
            if (start < 0 or end <= start or end > len(source_text)
                or source_text[start:end] != row["term"]):
                raise ValueError(f"contextual term source span mismatch: {key}")
            expected_evidence_start = max(0, start - 12)
            expected_evidence_end = min(len(source_text), end + 12)
            if (evidence_start != expected_evidence_start
                or evidence_end != expected_evidence_end
                or source_text[evidence_start:evidence_end] != row["evidence_text"]
                or not (evidence_start <= start < end <= evidence_end)):
                raise ValueError(f"contextual term evidence offset/text mismatch: {key}")
            counts[row["candidate_type"]] += 1
            checked += 1
        if checked != expected_count:
            raise ValueError(
                f"contextual term scan cardinality mismatch: expected={expected_count}, checked={checked}"
            )
        return {"checked_contextual_term_candidates": checked,
                "candidate_counts_by_type": dict(sorted(counts.items()))}
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    parser.add_argument("--output", type=Path,
                        help="Optional JSON path for the source-audit result.")
    args = parser.parse_args()
    result = audit(args.db)
    if args.output:
        write_audit_report(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
