#!/usr/bin/env python3
"""Run real-data query smoke checks against the completed SQLite search index."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from build_contextual_relation_candidates import PREDICATES, RELATION_SCOPE_BREAKS
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



CONTEXTUAL_PREDICATE_TYPES = {
    "SYMPTOM_TO_SYNDROME": ("SYMPTOM", "SYNDROME"),
    "SYNDROME_TO_TREATMENT": ("SYNDROME", "TREATMENT"),
    "TREATMENT_TO_FORMULA": ("TREATMENT", "FORMULA"),
}



def validate_full_text_index_count(
    connection: sqlite3.Connection, backend: str, content_block_count: int,
) -> int | None:
    """Require one FTS row per source block when the FTS5 backend is active."""
    if backend == "sqlite-instr-fallback":
        return None
    if backend != "fts5-trigram":
        raise AssertionError(f"unsupported full-text search backend: {backend!r}")
    try:
        indexed_count = connection.execute("SELECT COUNT(*) FROM content_fts").fetchone()[0]
    except sqlite3.Error as exc:
        raise AssertionError("FTS5 backend is declared but content_fts is unavailable") from exc
    if indexed_count != content_block_count:
        raise AssertionError(
            f"full-text index row count mismatch: content_blocks={content_block_count}, "
            f"content_fts={indexed_count}"
        )
    return indexed_count




def validate_contextual_predicate_queries(database_path: Path, predicate_counts: dict[str, int]) -> None:
    """Exercise all supported predicate queries, including audited zero-row results."""
    for predicate, (expected_subject, expected_object) in CONTEXTUAL_PREDICATE_TYPES.items():
        rows = search_contextual_relation_candidates(database_path, predicate, limit=20)
        if predicate_counts[predicate] == 0 and rows:
            raise AssertionError(f"zero-row contextual predicate query returned records: {predicate}")
        if predicate_counts[predicate] > 0 and not rows:
            raise AssertionError(f"contextual predicate query returned no records: {predicate}")
        if any(
            row["predicate"] != predicate
            or row["subject_type"] != expected_subject
            or row["object_type"] != expected_object
            for row in rows
        ):
            raise AssertionError(f"contextual relation predicate/direction query failed: {predicate}")

def validate_all_formula_herb_relation_rows(connection: sqlite3.Connection) -> int:
    """Validate every indexed formula-herb edge, not just a sampled search result."""
    rows = connection.execute("""
        SELECT r.relation_id, r.predicate, r.subject_mention_id, r.subject_text,
               r.object_mention_id, r.object_text, r.unit_id,
               r.document AS evidence_document, r.source_sha256 AS evidence_source_sha256,
               r.tree_position AS evidence_tree_position, r.block_id AS evidence_block_id,
               r.sentence_start, r.sentence_end, r.evidence_text,
               s.entity_type AS subject_type, s.matched_text AS subject_matched_text,
               s.character_start AS subject_start, s.character_end AS subject_end,
               s.document AS subject_document, s.source_sha256 AS subject_source_sha256,
               s.tree_position AS subject_tree_position, s.block_id AS subject_block_id,
               o.entity_type AS object_type, o.matched_text AS object_matched_text,
               o.character_start AS object_start, o.character_end AS object_end,
               o.unit_id AS object_unit_id, o.document AS object_document,
               o.source_sha256 AS object_source_sha256, o.tree_position AS object_tree_position,
               o.block_id AS object_block_id
        FROM semantic_relation_candidates r
        LEFT JOIN entity_mentions s ON s.mention_id = r.subject_mention_id
        LEFT JOIN entity_mentions o ON o.mention_id = r.object_mention_id
        ORDER BY r.relation_id
    """).fetchall()
    expected_count = connection.execute(
        "SELECT COUNT(*) FROM semantic_relation_candidates"
    ).fetchone()[0]
    if len(rows) != expected_count:
        raise AssertionError("formula-herb relation scan did not cover every indexed row")
    for row in rows:
        if (row["predicate"] != "FORMULA_CONTAINS_HERB"
            or row["subject_type"] != "FORMULA" or row["object_type"] != "HERB"
            or row["subject_matched_text"] != row["subject_text"]
            or row["object_matched_text"] != row["object_text"]):
            raise AssertionError(f"formula-herb relation endpoint identity mismatch: {row['relation_id']}")
        if (not row["subject_mention_id"] or not row["object_mention_id"]
            or row["subject_document"] != row["evidence_document"]
            or row["subject_source_sha256"] != row["evidence_source_sha256"]
            or row["object_document"] != row["evidence_document"]
            or row["object_source_sha256"] != row["evidence_source_sha256"]
            or row["object_unit_id"] != row["unit_id"]
            or row["object_tree_position"] != row["evidence_tree_position"]
            or row["object_block_id"] != row["evidence_block_id"]):
            raise AssertionError(f"formula-herb relation source locator mismatch: {row['relation_id']}")
        for role in ("subject", "object"):
            source = connection.execute(
                "SELECT content_text FROM content_blocks WHERE document=? AND source_sha256=? "
                "AND tree_position=? AND block_id=? LIMIT 1",
                (row[f"{role}_document"], row[f"{role}_source_sha256"],
                 row[f"{role}_tree_position"], row[f"{role}_block_id"]),
            ).fetchone()
            left, right = row[f"{role}_start"], row[f"{role}_end"]
            if (source is None or left < 0 or right <= left
                or right > len(source["content_text"])
                or source["content_text"][left:right] != row[f"{role}_matched_text"]):
                raise AssertionError(f"formula-herb relation {role} mention span mismatch: {row['relation_id']}")
        evidence_source = connection.execute(
            "SELECT content_text FROM content_blocks WHERE document=? AND source_sha256=? "
            "AND tree_position=? AND block_id=? LIMIT 1",
            (row["evidence_document"], row["evidence_source_sha256"],
             row["evidence_tree_position"], row["evidence_block_id"]),
        ).fetchone()
        start, end = row["sentence_start"], row["sentence_end"]
        if (evidence_source is None or start < 0 or end <= start
            or end > len(evidence_source["content_text"])
            or evidence_source["content_text"][start:end] != row["evidence_text"]):
            raise AssertionError(f"formula-herb relation evidence offset mismatch: {row['relation_id']}")
    return len(rows)


def validate_all_contextual_relation_rows(connection: sqlite3.Connection) -> int:
    """Validate every contextual relation row against its exact source block and predicate contract."""
    rows = connection.execute("""
        SELECT relation_id, predicate, subject_candidate_id, subject_text, subject_type,
               subject_start, subject_end, object_candidate_id, object_text, object_type,
               object_start, object_end, unit_id, document, source_sha256, tree_position,
               block_id, sentence_start, sentence_end, evidence_text, predicate_text
        FROM contextual_relation_candidates
        ORDER BY relation_id
    """).fetchall()
    expected_count = connection.execute(
        "SELECT COUNT(*) FROM contextual_relation_candidates"
    ).fetchone()[0]
    if len(rows) != expected_count:
        raise AssertionError("contextual relation scan did not cover every indexed row")

    contracts = {
        "SYMPTOM_TO_SYNDROME": ("SYMPTOM", "SYNDROME"),
        "SYNDROME_TO_TREATMENT": ("SYNDROME", "TREATMENT"),
        "TREATMENT_TO_FORMULA": ("TREATMENT", "FORMULA"),
    }
    for row in rows:
        contract = contracts.get(row["predicate"])
        if contract is None:
            raise AssertionError(f"unsupported contextual relation predicate: {row['predicate']}")
        if (row["subject_type"], row["object_type"]) != contract:
            raise AssertionError(f"contextual relation endpoint direction mismatch: {row['relation_id']}")
        if not row["subject_candidate_id"] or not row["object_candidate_id"]:
            raise AssertionError(f"contextual relation endpoint identity missing: {row['relation_id']}")

        for endpoint, candidate_id, term, candidate_type, start, end in (
            ("subject", row["subject_candidate_id"], row["subject_text"], row["subject_type"],
             row["subject_start"], row["subject_end"]),
            ("object", row["object_candidate_id"], row["object_text"], row["object_type"],
             row["object_start"], row["object_end"]),
        ):
            if candidate_type == "FORMULA":
                matches = connection.execute("""
                    SELECT mention_id FROM entity_mentions
                    WHERE mention_id=? AND matched_text=? AND entity_type=? AND unit_id=?
                      AND document=? AND source_sha256=? AND tree_position=?
                      AND COALESCE(block_id, '')=COALESCE(?, '')
                      AND character_start=? AND character_end=?
                """, (
                    candidate_id, term, candidate_type, row["unit_id"], row["document"],
                    row["source_sha256"], row["tree_position"], row["block_id"], start, end,
                )).fetchall()
            else:
                matches = connection.execute("""
                    SELECT candidate_id FROM contextual_term_type_candidates
                    WHERE candidate_id=? AND candidate_type=? AND term=? AND unit_id=?
                      AND character_start=? AND character_end=? AND evidence_document=?
                      AND source_sha256=? AND tree_position=? AND COALESCE(block_id, '')=COALESCE(?, '')
                """, (
                    candidate_id, candidate_type, term, row["unit_id"], start, end,
                    row["document"], row["source_sha256"], row["tree_position"], row["block_id"],
                )).fetchall()
            if not matches:
                raise AssertionError(
                    f"contextual relation {endpoint} candidate identity/source mismatch: {row['relation_id']}"
                )

        source = connection.execute(
            "SELECT content_text FROM content_blocks WHERE document=? AND source_sha256=? "
            "AND tree_position=? AND block_id=? LIMIT 1",
            (row["document"], row["source_sha256"], row["tree_position"], row["block_id"]),
        ).fetchone()
        if source is None:
            raise AssertionError(f"contextual relation source locator missing: {row['relation_id']}")
        text = source["content_text"]
        sentence_start, sentence_end = row["sentence_start"], row["sentence_end"]
        subject_start, subject_end = row["subject_start"], row["subject_end"]
        object_start, object_end = row["object_start"], row["object_end"]
        if (sentence_start < 0 or sentence_end <= sentence_start or sentence_end > len(text)
            or text[sentence_start:sentence_end] != row["evidence_text"]):
            raise AssertionError(f"contextual relation evidence offset mismatch: {row['relation_id']}")
        if not (sentence_start <= subject_start < subject_end <= sentence_end
                and sentence_start <= object_start < object_end <= sentence_end
                and subject_end <= object_start):
            raise AssertionError(f"contextual relation endpoint outside ordered evidence: {row['relation_id']}")
        if (text[subject_start:subject_end] != row["subject_text"]
            or text[object_start:object_end] != row["object_text"]):
            raise AssertionError(f"contextual relation endpoint text/offset mismatch: {row['relation_id']}")
        between = text[subject_end:object_start]
        predicate_match = PREDICATES[row["predicate"]].search(between)
        if predicate_match is None or predicate_match.group(0) != row["predicate_text"]:
            raise AssertionError(f"contextual relation predicate is outside endpoint scope: {row['relation_id']}")
        scope_break = RELATION_SCOPE_BREAKS.get(row["predicate"])
        if scope_break and scope_break.search(between):
            raise AssertionError(f"contextual relation crosses source-attribution boundary: {row['relation_id']}")
    return len(rows)


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
    fts_count = validate_full_text_index_count(
        connection, metadata.get("search_backend", ""), counts["content_blocks"]
    )
    if fts_count is not None:
        checks["full_text_index_rows"] = "PASS"
    if counts["semantic_relation_candidates"]:
        validate_all_formula_herb_relation_rows(connection)
        checks["formula_herb_all_rows_provenance"] = "PASS"

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

    validate_contextual_predicate_queries(database_path, contextual_predicates)
    validate_all_contextual_relation_rows(connection)
    checks["contextual_relation_all_rows_provenance"] = "PASS"
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
