#!/usr/bin/env python3
"""Exhaustively audit SQLite contextual relations against typed candidates and source text."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from audit_report import write_audit_report

from build_contextual_relation_candidates import (
    NEGATION_PREFIX, PREDICATES, RELATION_SCOPE_BREAKS,
    relation_identity, sentence_ranges,
)

SOURCE_NOTE_ASSOCIATION_PAIRS = {
    frozenset(pair) for pair in (
        ("SYMPTOM", "FORMULA"), ("SYMPTOM", "POINT"),
        ("SYMPTOM", "ACUPOINT"), ("SYMPTOM", "ACUPUNCTURE_TECHNIQUE"),
        ("SYNDROME", "FORMULA"), ("SYNDROME", "POINT"),
        ("SYNDROME", "ACUPOINT"), ("SYNDROME", "ACUPUNCTURE_TECHNIQUE"),
        ("FORMULA", "SYMPTOM"), ("FORMULA", "SYNDROME"),
        ("POINT", "SYMPTOM"), ("POINT", "SYNDROME"),
        ("POINT", "ACUPUNCTURE_TECHNIQUE"),
        ("ACUPOINT", "SYMPTOM"), ("ACUPOINT", "SYNDROME"),
        ("ACUPOINT", "ACUPUNCTURE_TECHNIQUE"),
        ("CLASSICAL_SOURCE", "CLASSICAL_THEORY"),
    )
}
CLASSICAL_ATTRIBUTION_MARKER = re.compile(r"(?:有言|说|曰|云|记载|指出)")
SOURCE_NOTE_LABEL_MARKER = re.compile(r"[\\s、，,）)】』」]?[：:]")
SOURCE_NOTE_RANGE = re.compile(r"[^。！？．\n]+[。！？．]?|\n+")
SOURCE_NOTE_ATTRIBUTION_BOUNDARY = next(iter(RELATION_SCOPE_BREAKS.values()))


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
            source_note = predicate == "SOURCE_NOTE_ASSOCIATES"
            classical_attribution = (
                source_note
                and row["subject_type"] == "CLASSICAL_SOURCE"
                and row["object_type"] == "CLASSICAL_THEORY"
            )
            expected_rule = (
                "SOURCE_NOTE_ASSOCIATES_CLASSICAL_ATTRIBUTION_V1"
                if classical_attribution
                else "SOURCE_NOTE_ASSOCIATES_LABEL_V1"
                if source_note else predicate + "_EXPLICIT_V1"
            )
            if (not source_note and (predicate not in PREDICATES or predicate not in expected_types)):
                raise ValueError(f"unsupported contextual relation predicate: {predicate}")
            if source_note:
                if frozenset((row["subject_type"], row["object_type"])) not in SOURCE_NOTE_ASSOCIATION_PAIRS:
                    raise ValueError(f"contextual source-note endpoint pair mismatch: {rid}")
            elif (row["subject_type"], row["object_type"]) != expected_types[predicate]:
                raise ValueError(f"contextual relation endpoint type/direction mismatch: {rid}")
            if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                raise ValueError(f"unsafe contextual relation status: {rid}")
            if row["extraction_rule"] != expected_rule:
                raise ValueError(f"contextual relation extraction rule mismatch: {rid}")

            source = row["content_text"]
            start, end = row["sentence_start"], row["sentence_end"]
            if (source is None or start < 0 or end <= start or end > len(source)
                or source[start:end] != row["evidence_text"]):
                raise ValueError(f"contextual relation evidence offset/source mismatch: {rid}")
            valid_ranges = (
                { (match.start(), match.end()) for match in SOURCE_NOTE_RANGE.finditer(source) if match.group(0).strip() }
                if source_note else set(sentence_ranges(source))
            )
            if (start, end) not in valid_ranges:
                raise ValueError(f"contextual relation evidence crosses sentence boundary: {rid}")

            ss, se = row["subject_start"], row["subject_end"]
            os, oe = row["object_start"], row["object_end"]
            if not (0 <= start <= ss < se <= os < oe <= end <= len(source)):
                raise ValueError(f"contextual relation endpoint spans invalid: {rid}")
            if (source[ss:se] != row["subject_text"]
                or source[os:oe] != row["object_text"]):
                raise ValueError(f"contextual relation endpoint source text mismatch: {rid}")

            between = source[se:os]
            if source_note:
                match = (
                    CLASSICAL_ATTRIBUTION_MARKER.match(between)
                    if classical_attribution else SOURCE_NOTE_LABEL_MARKER.match(between)
                )
                if (match is None or match.group(0).strip() != row["predicate_text"]
                    or (not classical_attribution and
                        re.search(r"(?:不宜|不应|不可|不能|禁用|禁止|勿用|忌用)", between[match.end():]))):
                    raise ValueError(f"contextual source-note marker evidence mismatch: {rid}")
                scope_break = SOURCE_NOTE_ATTRIBUTION_BOUNDARY
            else:
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
                if candidate_type in {"FORMULA", "POINT"}:
                    endpoint = connection.execute("""
                        SELECT mention_id FROM entity_mentions
                        WHERE mention_id=? AND matched_text=? AND entity_type=?
                          AND unit_id=? AND document=? AND source_sha256=?
                          AND tree_position=? AND COALESCE(block_id,'')=COALESCE(?,'')
                          AND character_start=? AND character_end=?
                    """, (candidate_id, term, candidate_type, row["unit_id"], row["document"],
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
                **{predicate: counts.get(predicate, 0) for predicate in PREDICATES},
                "SOURCE_NOTE_ASSOCIATES": counts.get("SOURCE_NOTE_ASSOCIATES", 0),
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
