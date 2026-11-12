#!/usr/bin/env python3
"""Exhaustively audit SQLite contextual relations against typed candidates and source text."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from audit_report import write_audit_report

from build_contextual_relation_candidates import (
    NEGATION_PREFIX, PREDICATES, RELATION_SCOPE_BREAKS,
    relation_identity, sentence_ranges,
)


def audit(database_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        metadata = dict(connection.execute("SELECT key, value FROM index_metadata"))
        actual = connection.execute(
            "SELECT COUNT(*) FROM contextual_relation_candidates"
        ).fetchone()[0]
        if ("contextual_relation_candidates" not in metadata
            or int(metadata["contextual_relation_candidates"]) != actual):
            raise ValueError(
                "contextual relation metadata count mismatch: "
                f"metadata={metadata.get('contextual_relation_candidates')!r}, actual={actual}"
            )
        expected_types = {
            "SYMPTOM_TO_SYNDROME": ("SYMPTOM", "SYNDROME"),
            "SYNDROME_TO_TREATMENT": ("SYNDROME", "TREATMENT"),
            "TREATMENT_TO_FORMULA": ("TREATMENT", "FORMULA"),
        }
        counts: Counter[str] = Counter()
        seen: set[str] = set()
        query = """
            SELECT r.*, b.content_text
            FROM contextual_relation_candidates r
            LEFT JOIN content_blocks b
              ON b.document=r.document AND b.source_sha256=r.source_sha256
             AND b.tree_position=r.tree_position AND COALESCE(b.block_id,'')=COALESCE(r.block_id,'')
            ORDER BY r.document, r.tree_position, r.sentence_start, r.relation_id
        """
        checked = 0
        for row in connection.execute(query):
            rid = row["relation_id"]
            if not rid or rid in seen:
                raise ValueError(f"missing or duplicate contextual relation_id: {rid!r}")
            seen.add(rid)
            predicate = row["predicate"]
            if predicate not in PREDICATES or predicate not in expected_types:
                raise ValueError(f"unsupported contextual relation predicate: {predicate}")
            if (row["subject_type"], row["object_type"]) != expected_types[predicate]:
                raise ValueError(f"contextual relation endpoint type/direction mismatch: {rid}")
            if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                raise ValueError(f"unsafe contextual relation status: {rid}")
            if row["extraction_rule"] != predicate + "_EXPLICIT_V1":
                raise ValueError(f"contextual relation extraction rule mismatch: {rid}")

            source = row["content_text"]
            start, end = row["sentence_start"], row["sentence_end"]
            if (source is None or start < 0 or end <= start or end > len(source)
                or source[start:end] != row["evidence_text"]):
                raise ValueError(f"contextual relation evidence offset/source mismatch: {rid}")
            if (start, end) not in set(sentence_ranges(source)):
                raise ValueError(f"contextual relation evidence crosses sentence boundary: {rid}")

            ss, se = row["subject_start"], row["subject_end"]
            os, oe = row["object_start"], row["object_end"]
            if not (0 <= start <= ss < se <= os < oe <= end <= len(source)):
                raise ValueError(f"contextual relation endpoint spans invalid: {rid}")
            if (source[ss:se] != row["subject_text"]
                or source[os:oe] != row["object_text"]):
                raise ValueError(f"contextual relation endpoint source text mismatch: {rid}")

            between = source[se:os]
            match = PREDICATES[predicate].search(between)
            if (match is None or match.group(0) != row["predicate_text"]
                or NEGATION_PREFIX.search(between[:match.start()])):
                raise ValueError(f"contextual relation predicate evidence mismatch: {rid}")
            scope_break = RELATION_SCOPE_BREAKS.get(predicate)
            if scope_break and scope_break.search(between):
                raise ValueError(f"contextual relation crosses source-attribution boundary: {rid}")

            endpoint_specs = (
                ("subject", row["subject_candidate_id"], row["subject_text"],
                 row["subject_type"], ss, se),
                ("object", row["object_candidate_id"], row["object_text"],
                 row["object_type"], os, oe),
            )
            for role, candidate_id, term, candidate_type, left, right in endpoint_specs:
                if candidate_type == "FORMULA":
                    endpoint = connection.execute("""
                        SELECT mention_id FROM entity_mentions
                        WHERE mention_id=? AND matched_text=? AND entity_type='FORMULA'
                          AND unit_id=? AND document=? AND source_sha256=?
                          AND tree_position=? AND COALESCE(block_id,'')=COALESCE(?,'')
                          AND character_start=? AND character_end=?
                    """, (candidate_id, term, row["unit_id"], row["document"],
                          row["source_sha256"], row["tree_position"], row["block_id"],
                          left, right)).fetchone()
                else:
                    endpoint = connection.execute("""
                        SELECT candidate_id FROM contextual_term_type_candidates
                        WHERE candidate_id=? AND term=? AND candidate_type=?
                          AND unit_id=? AND evidence_document=? AND source_sha256=?
                          AND tree_position=? AND COALESCE(block_id,'')=COALESCE(?,'')
                          AND character_start=? AND character_end=?
                    """, (candidate_id, term, candidate_type, row["unit_id"],
                          row["document"], row["source_sha256"], row["tree_position"],
                          row["block_id"], left, right)).fetchone()
                if endpoint is None:
                    raise ValueError(f"contextual relation {role} endpoint is not a matching SQLite candidate: {rid}")

            subject = {"candidate_id": row["subject_candidate_id"],
                       "character_start": str(ss), "character_end": str(se)}
            obj = {"candidate_id": row["object_candidate_id"],
                   "character_start": str(os), "character_end": str(oe)}
            expected_id = relation_identity(predicate, subject, obj, row["unit_id"], start, end)
            if rid != expected_id:
                raise ValueError(f"contextual relation ID/endpoint identity mismatch: {rid}")
            counts[predicate] += 1
            checked += 1

        if checked != actual:
            raise ValueError(f"contextual relation scan cardinality mismatch: {checked} != {actual}")
        return {
            "checked_relation_rows": checked,
            "relation_counts_by_predicate": {
                predicate: counts.get(predicate, 0) for predicate in PREDICATES
            },
            "identity_validation": "PASS",
            "endpoint_candidate_validation": "PASS",
            "evidence_source_validation": "PASS",
            "sentence_and_attribution_boundary_validation": "PASS",
        }
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
