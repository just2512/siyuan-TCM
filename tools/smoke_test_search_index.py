#!/usr/bin/env python3
"""Run real-data query smoke checks against the completed SQLite search index."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from build_siyuan_search_db import (
    search_contextual_relation_candidates,
    search_contextual_term_candidates,
    search_database,
    search_entity_mentions,
    search_relation_candidates,
    search_unclassified_terms,
)


TABLES = (
    "content_blocks",
    "node_relationships",
    "entity_mentions",
    "entity_catalog",
    "semantic_relation_candidates",
    "unclassified_term_candidates",
    "contextual_term_type_candidates",
    "contextual_relation_candidates",
)


def smoke(database_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    metadata = dict(connection.execute("SELECT key, value FROM index_metadata"))
    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in TABLES
    }

    formula_herb_predicates = dict(connection.execute(
        "SELECT predicate, COUNT(*) FROM semantic_relation_candidates GROUP BY predicate ORDER BY predicate"
    ))
    contextual_predicate_types = {
        "SYMPTOM_TO_SYNDROME": ("SYMPTOM", "SYNDROME"),
        "SYNDROME_TO_TREATMENT": ("SYNDROME", "TREATMENT"),
        "TREATMENT_TO_FORMULA": ("TREATMENT", "FORMULA"),
    }
    contextual_predicates = {
        predicate: connection.execute(
            "SELECT COUNT(*) FROM contextual_relation_candidates WHERE predicate=?",
            (predicate,),
        ).fetchone()[0]
        for predicate in contextual_predicate_types
    }
    unknown_contextual_predicates = {
        row[0] for row in connection.execute(
            "SELECT DISTINCT predicate FROM contextual_relation_candidates"
        )
    } - set(contextual_predicate_types)
    if unknown_contextual_predicates:
        raise AssertionError(
            "unsupported contextual relation predicates: "
            + ", ".join(sorted(unknown_contextual_predicates))
        )
    metadata_keys = {
        "content_blocks": "content_blocks",
        "node_relationships": "relationships",
        "entity_mentions": "entity_mentions",
        "entity_catalog": "lexical_entities",
        "semantic_relation_candidates": "relation_candidates",
        "unclassified_term_candidates": "unclassified_term_candidates",
        "contextual_term_type_candidates": "contextual_term_type_candidates",
        "contextual_relation_candidates": "contextual_relation_candidates",
    }
    for table, key in metadata_keys.items():
        if key not in metadata or int(metadata[key]) != counts[table]:
            raise AssertionError(
                f"{table} count mismatch: metadata={metadata.get(key)!r}, actual={counts[table]}"
            )

    checks: dict[str, str] = {}

    source = connection.execute(
        "SELECT document, content_text FROM content_blocks "
        "WHERE length(trim(content_text)) >= 3 ORDER BY document LIMIT 1"
    ).fetchone()
    if source is None:
        raise AssertionError("search index contains no queryable source text")
    query = source["content_text"].strip()[:3]
    text_hits = search_database(database_path, query, limit=20)
    if not any(query in row["content_text"] for row in text_hits):
        raise AssertionError("full-text query did not return its source text")
    checks["full_text"] = "PASS"

    if counts["entity_mentions"]:
        entity = connection.execute(
            "SELECT matched_text FROM entity_mentions "
            "WHERE length(matched_text) >= 2 ORDER BY document, tree_position LIMIT 1"
        ).fetchone()
        if entity is None:
            raise AssertionError("entity mention table has no searchable term")
        mentions = search_entity_mentions(database_path, entity["matched_text"], limit=20)
        grounded = [
            row for row in mentions
            if row["content_text"] is not None
            and row["content_text"][row["character_start"]:row["character_end"]] == row["matched_text"]
        ]
        if not grounded:
            raise AssertionError("entity query returned no exact source-span match")
        checks["entity_span_and_source"] = "PASS"

    if counts["semantic_relation_candidates"]:
        relation = connection.execute(
            "SELECT subject_text FROM semantic_relation_candidates ORDER BY document, tree_position LIMIT 1"
        ).fetchone()
        rows = search_relation_candidates(database_path, relation["subject_text"], limit=20)
        if not rows:
            raise AssertionError("formula-herb relation query returned no rows")
        for row in rows:
            if (not row["subject_mention_id"] or not row["object_mention_id"]
                or row["subject_type"] != "FORMULA" or row["object_type"] != "HERB"
                or row["subject_matched_text"] != row["subject_text"]
                or row["object_matched_text"] != row["object_text"]):
                raise AssertionError("formula-herb relation query has untraceable or mismatched mention endpoints")
            if (row["subject_document"] != row["evidence_document"]
                or row["subject_source_sha256"] != row["evidence_source_sha256"]
                or row["object_document"] != row["evidence_document"]
                or row["object_source_sha256"] != row["evidence_source_sha256"]
                or row["object_unit_id"] != row["unit_id"]
                or row["object_tree_position"] != row["evidence_tree_position"]
                or row["object_block_id"] != row["evidence_block_id"]):
                raise AssertionError("formula-herb relation query endpoint source locator mismatch")
            for role in ("subject", "object"):
                source = connection.execute(
                    "SELECT content_text FROM content_blocks WHERE document=? AND source_sha256=? "
                    "AND tree_position=? AND block_id=? LIMIT 1",
                    (row[f"{role}_document"], row[f"{role}_source_sha256"],
                     row[f"{role}_tree_position"], row[f"{role}_block_id"]),
                ).fetchone()
                left, right = row[f"{role}_character_start"], row[f"{role}_character_end"]
                if (source is None or right <= left
                    or source["content_text"][left:right] != row[f"{role}_matched_text"]):
                    raise AssertionError(f"formula-herb relation query {role} mention span cannot be resolved")
            evidence_source = connection.execute(
                "SELECT content_text FROM content_blocks WHERE document=? AND source_sha256=? "
                "AND tree_position=? AND block_id=? LIMIT 1",
                (row["evidence_document"], row["evidence_source_sha256"],
                 row["evidence_tree_position"], row["evidence_block_id"]),
            ).fetchone()
            start, end = row["sentence_start"], row["sentence_end"]
            if (evidence_source is None or end <= start
                or evidence_source["content_text"][start:end] != row["evidence_text"]):
                raise AssertionError("formula-herb relation query evidence offset does not match source text")
        checks["formula_herb_relation"] = "PASS"

    if counts["unclassified_term_candidates"]:
        term = connection.execute(
            "SELECT term FROM unclassified_term_candidates ORDER BY document_count DESC, occurrence_count DESC LIMIT 1"
        ).fetchone()
        if not search_unclassified_terms(database_path, term["term"], limit=20):
            raise AssertionError("unclassified term query returned no result")
        checks["unclassified_terms"] = "PASS"

    if counts["contextual_term_type_candidates"]:
        term = connection.execute(
            "SELECT term FROM contextual_term_type_candidates ORDER BY candidate_type, term LIMIT 1"
        ).fetchone()
        candidates = search_contextual_term_candidates(database_path, term["term"], limit=20)
        if not candidates or not any(row["evidence_text"] and row["source_sha256"] for row in candidates):
            raise AssertionError("contextual term query lacks source evidence")
        checks["contextual_term_candidates"] = "PASS"

    if counts["contextual_relation_candidates"]:
        relation = connection.execute(
            "SELECT subject_text FROM contextual_relation_candidates "
            "ORDER BY document, tree_position, sentence_start LIMIT 1"
        ).fetchone()
        rows = search_contextual_relation_candidates(database_path, relation["subject_text"], limit=20)
        grounded = False
        for row in rows:
            source_row = connection.execute(
                "SELECT content_text FROM content_blocks WHERE document=? AND source_sha256=? "
                "AND tree_position=? AND block_id=? LIMIT 1",
                (row["document"], row["source_sha256"], row["tree_position"], row["block_id"]),
            ).fetchone()
            if source_row is None:
                continue
            text = source_row["content_text"]
            start, end = row["sentence_start"], row["sentence_end"]
            if start < 0 or end <= start or text[start:end] != row["evidence_text"]:
                continue
            if text[row["subject_start"]:row["subject_end"]] != row["subject_text"]:
                continue
            if text[row["object_start"]:row["object_end"]] != row["object_text"]:
                continue
            between = text[row["subject_end"]:row["object_start"]]
            if row["predicate_text"] not in between:
                continue
            grounded = True
            break
        if not grounded:
            raise AssertionError("contextual relation query failed source/endpoint/predicate evidence checks")
        checks["contextual_relation_evidence"] = "PASS"

    # Query every supported predicate even when the corpus currently has zero
    # candidates. Empty results are a valid audited outcome; the query path itself
    # must still execute and must never leak a different predicate's rows.
    contracts = {
        "SYMPTOM_TO_SYNDROME": ("SYMPTOM", "SYNDROME"),
        "SYNDROME_TO_TREATMENT": ("SYNDROME", "TREATMENT"),
        "TREATMENT_TO_FORMULA": ("TREATMENT", "FORMULA"),
    }
    for predicate, (expected_subject, expected_object) in contracts.items():
        rows = search_contextual_relation_candidates(database_path, predicate, limit=20)
        if contextual_predicates[predicate] == 0 and rows:
            raise AssertionError(f"zero-row contextual predicate query returned records: {predicate}")
        if contextual_predicates[predicate] > 0 and not rows:
            raise AssertionError(f"contextual predicate query returned no records: {predicate}")
        if any(
            row["predicate"] != predicate
            or row["subject_type"] != expected_subject
            or row["object_type"] != expected_object
            for row in rows
        ):
            raise AssertionError(f"contextual relation predicate/direction query failed: {predicate}")
    checks["contextual_relation_predicate_queries"] = "PASS"

    if counts["contextual_relation_candidates"]:
        contracts = {
            "SYMPTOM_TO_SYNDROME": ("SYMPTOM", "SYNDROME"),
            "SYNDROME_TO_TREATMENT": ("SYNDROME", "TREATMENT"),
            "TREATMENT_TO_FORMULA": ("TREATMENT", "FORMULA"),
        }
        predicates = [
            row[0] for row in connection.execute(
                "SELECT DISTINCT predicate FROM contextual_relation_candidates ORDER BY predicate"
            )
        ]
        for predicate in predicates:
            if predicate not in contracts:
                raise AssertionError(f"unsupported contextual relation predicate: {predicate}")
            rows = search_contextual_relation_candidates(database_path, predicate, limit=20)
            expected_subject, expected_object = contracts[predicate]
            if not rows or any(
                row["predicate"] != predicate
                or row["subject_type"] != expected_subject
                or row["object_type"] != expected_object
                for row in rows
            ):
                raise AssertionError(f"contextual relation predicate/direction query failed: {predicate}")
        checks["contextual_relation_predicate_direction"] = "PASS"

    connection.close()
    return {
        "schema_version": 1,
        "database_bytes": database_path.stat().st_size,
        "search_backend": metadata.get("search_backend"),
        "table_counts": counts,
        "relation_predicate_counts": {
            "FORMULA_CONTAINS_HERB": formula_herb_predicates.get("FORMULA_CONTAINS_HERB", 0),
            **contextual_predicates,
        },
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/search_index_smoke.json"))
    args = parser.parse_args()
    result = smoke(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
