#!/usr/bin/env python3
"""Query source-grounded TCM knowledge paths without inventing clinical relations.

A search result is an exact occurrence in a classical-source passage. Its
same-passage links are navigation-only co-occurrences; formula/herb and
contextual edges remain unresolved evidence-backed candidates.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

REQUIRED_TABLES = (
    "classical_source_documents",
    "classical_source_passages",
    "classical_source_passage_mentions",
    "classical_source_passage_term_links",
)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _mention(row: sqlite3.Row, passage_start: int, passage_text: str) -> dict[str, Any]:
    start = int(row["character_start"])
    end = int(row["character_end"])
    relative_start = start - passage_start
    relative_end = end - passage_start
    span_is_valid = 0 <= relative_start <= relative_end <= len(passage_text)
    span_text = passage_text[relative_start:relative_end] if span_is_valid else None
    return {
        "occurrence_id": row["occurrence_id"],
        "reference_kind": row["reference_kind"],
        "reference_id": row["reference_id"],
        "entity_id": row["entity_id"],
        "term_type": row["term_type"],
        "term_text": row["term_text"],
        "block_character_start": start,
        "block_character_end": end,
        "passage_character_start": relative_start if span_is_valid else None,
        "passage_character_end": relative_end if span_is_valid else None,
        "source_span_text": span_text,
        "source_span_matches_term": span_text == row["term_text"],
        "rule_ids": _json_value(row["rule_ids_json"]),
        "resolution_status": row["resolution_status"],
    }


def _in_clause(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def search_classical_knowledge_paths(
    database_path: Path,
    query: str,
    limit: int = 100,
    *,
    source_work: str | None = None,
    document_role: str | None = None,
    term_type: str | None = None,
) -> dict[str, Any]:
    """Find exact lexical occurrences and all source-backed paths around them.

    The limit caps matched occurrences, not links. Repeated occurrences remain
    separate results. Matching is substring-based and does not merge aliases.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    if not database_path.is_file():
        raise FileNotFoundError(database_path)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        missing = [table for table in REQUIRED_TABLES if not _table_exists(connection, table)]
        if missing:
            raise ValueError(
                "database is missing classical-source tables: " + ", ".join(missing)
            )

        filters = ["instr(m.term_text, ?) > 0"]
        params: list[Any] = [query]
        for column, value in (
            ("d.source_work", source_work),
            ("d.document_role", document_role),
            ("m.term_type", term_type),
        ):
            if value is not None:
                filters.append(f"{column} = ?")
                params.append(value)
        params.append(limit)

        matches = connection.execute(
            f"""
            SELECT
                m.occurrence_id, m.reference_kind, m.reference_id, m.entity_id,
                m.term_type, m.term_text, m.character_start, m.character_end,
                m.rule_ids_json, m.resolution_status,
                p.passage_id, p.source_document_id, p.document, p.source_work,
                p.source_sha256, p.tree_position, p.block_id, p.parent_block_id,
                p.content_type, p.section_path, p.character_start AS passage_start,
                p.character_end AS passage_end, p.passage_text, p.passage_kind,
                d.source_work_label, d.title AS source_title, d.document_role,
                d.chapter_path_json
            FROM classical_source_passage_mentions m
            JOIN classical_source_passages p ON p.passage_id = m.passage_id
            JOIN classical_source_documents d
              ON d.source_document_id = p.source_document_id
            WHERE {" AND ".join(filters)}
            ORDER BY p.source_work, p.document, p.tree_position,
                     p.character_start, m.character_start, m.character_end,
                     m.occurrence_id
            LIMIT ?
            """,
            params,
        ).fetchall()

        results: list[dict[str, Any]] = []
        for matched in matches:
            passage_id = matched["passage_id"]
            source_document_id = matched["source_document_id"]
            passage_start = int(matched["passage_start"])
            passage_text = matched["passage_text"]

            mention_rows = connection.execute(
                """
                SELECT occurrence_id, reference_kind, reference_id, entity_id,
                       term_type, term_text, character_start, character_end,
                       rule_ids_json, resolution_status
                FROM classical_source_passage_mentions
                WHERE passage_id = ?
                ORDER BY character_start, character_end, occurrence_id
                """,
                (passage_id,),
            ).fetchall()
            passage_terms = [
                _mention(row, passage_start, passage_text) for row in mention_rows
            ]
            passage_mentions_by_id = {
                row["occurrence_id"]: _mention(row, passage_start, passage_text)
                for row in mention_rows
            }
            entity_mention_ids = sorted({
                row["reference_id"] for row in mention_rows
                if row["reference_kind"] == "ENTITY_MENTION" and row["reference_id"]
            })
            contextual_candidate_ids = sorted({
                row["reference_id"] for row in mention_rows
                if row["reference_kind"] == "CONTEXTUAL_TERM_CANDIDATE" and row["reference_id"]
            })

            link_rows = connection.execute(
                """
                SELECT l.link_id, l.pair_key, l.relation_type,
                       l.subject_occurrence_id, l.object_occurrence_id,
                       s.term_type AS subject_type, s.term_text AS subject_text,
                       s.character_start AS subject_start, s.character_end AS subject_end,
                       o.term_type AS object_type, o.term_text AS object_text,
                       o.character_start AS object_start, o.character_end AS object_end
                FROM classical_source_passage_term_links l
                JOIN classical_source_passage_mentions s
                  ON s.occurrence_id = l.subject_occurrence_id
                JOIN classical_source_passage_mentions o
                  ON o.occurrence_id = l.object_occurrence_id
                WHERE l.passage_id = ?
                  AND (l.subject_occurrence_id = ? OR l.object_occurrence_id = ?)
                ORDER BY l.pair_key, s.character_start, o.character_start, l.link_id
                """,
                (passage_id, matched["occurrence_id"], matched["occurrence_id"]),
            ).fetchall()
            navigational_links = [
                {
                    "link_id": row["link_id"],
                    "pair_key": row["pair_key"],
                    "relation_type": row["relation_type"],
                    "relation_semantics": "NAVIGATION_ONLY",
                    "subject": {
                        "occurrence_id": row["subject_occurrence_id"],
                        "term_type": row["subject_type"],
                        "term_text": row["subject_text"],
                        "block_character_start": row["subject_start"],
                        "block_character_end": row["subject_end"],
                    },
                    "object": {
                        "occurrence_id": row["object_occurrence_id"],
                        "term_type": row["object_type"],
                        "term_text": row["object_text"],
                        "block_character_start": row["object_start"],
                        "block_character_end": row["object_end"],
                    },
                }
                for row in link_rows
            ]

            formula_herb_candidates: list[dict[str, Any]] = []
            if entity_mention_ids and _table_exists(connection, "semantic_relation_candidates"):
                ids = _in_clause(entity_mention_ids)
                relation_rows = connection.execute(
                    f"""
                    SELECT relation_id, predicate, subject_mention_id, subject_text,
                           object_mention_id, object_text, document, source_sha256,
                           tree_position, block_id, sentence_start, sentence_end,
                           evidence_text, extraction_rule, resolution_status
                    FROM semantic_relation_candidates
                    WHERE subject_mention_id IN ({ids})
                       OR object_mention_id IN ({ids})
                    ORDER BY document, tree_position, sentence_start, relation_id
                    """,
                    entity_mention_ids + entity_mention_ids,
                ).fetchall()
                for row in relation_rows:
                    formula_herb_candidates.append({
                        "relation_id": row["relation_id"],
                        "predicate": row["predicate"],
                        "relation_semantics": "UNRESOLVED_SEMANTIC_CANDIDATE",
                        "subject_mention_id": row["subject_mention_id"],
                        "subject_text": row["subject_text"],
                        "subject_occurrence": next(
                            (passage_mentions_by_id[item["occurrence_id"]]
                             for item in mention_rows
                             if item["reference_kind"] == "ENTITY_MENTION"
                             and item["reference_id"] == row["subject_mention_id"]),
                            None,
                        ),
                        "object_mention_id": row["object_mention_id"],
                        "object_text": row["object_text"],
                        "object_occurrence": next(
                            (passage_mentions_by_id[item["occurrence_id"]]
                             for item in mention_rows
                             if item["reference_kind"] == "ENTITY_MENTION"
                             and item["reference_id"] == row["object_mention_id"]),
                            None,
                        ),
                        "evidence": {
                            "document": row["document"],
                            "source_sha256": row["source_sha256"],
                            "tree_position": row["tree_position"],
                            "block_id": row["block_id"],
                            "character_start": row["sentence_start"],
                            "character_end": row["sentence_end"],
                            "text": row["evidence_text"],
                        },
                        "extraction_rule": row["extraction_rule"],
                        "resolution_status": row["resolution_status"],
                    })

            contextual_relation_candidates: list[dict[str, Any]] = []
            if contextual_candidate_ids and _table_exists(
                connection, "contextual_relation_candidates"
            ):
                ids = _in_clause(contextual_candidate_ids)
                relation_rows = connection.execute(
                    f"""
                    SELECT relation_id, predicate, subject_candidate_id, subject_text,
                           subject_type, subject_start, subject_end, object_candidate_id,
                           object_text, object_type, object_start, object_end, unit_id,
                           document, source_sha256, tree_position, block_id,
                           sentence_start, sentence_end, evidence_text, predicate_text,
                           extraction_rule, resolution_status
                    FROM contextual_relation_candidates
                    WHERE subject_candidate_id IN ({ids})
                       OR object_candidate_id IN ({ids})
                    ORDER BY document, tree_position, sentence_start, relation_id
                    """,
                    contextual_candidate_ids + contextual_candidate_ids,
                ).fetchall()
                contextual_relation_candidates = [
                    {
                        "relation_id": row["relation_id"],
                        "predicate": row["predicate"],
                        "subject": {
                            "candidate_id": row["subject_candidate_id"],
                            "term": row["subject_text"],
                            "term_type": row["subject_type"],
                            "character_start": row["subject_start"],
                            "character_end": row["subject_end"],
                        },
                        "object": {
                            "candidate_id": row["object_candidate_id"],
                            "term": row["object_text"],
                            "term_type": row["object_type"],
                            "character_start": row["object_start"],
                            "character_end": row["object_end"],
                        },
                        "predicate_text": row["predicate_text"],
                        "evidence": {
                            "unit_id": row["unit_id"],
                            "document": row["document"],
                            "source_sha256": row["source_sha256"],
                            "tree_position": row["tree_position"],
                            "block_id": row["block_id"],
                            "character_start": row["sentence_start"],
                            "character_end": row["sentence_end"],
                            "text": row["evidence_text"],
                        },
                        "extraction_rule": row["extraction_rule"],
                        "resolution_status": row["resolution_status"],
                        "relation_semantics": "UNRESOLVED_EXPLICIT_PREDICATE_CANDIDATE",
                    }
                    for row in relation_rows
                ]

            document_references: list[dict[str, Any]] = []
            if _table_exists(connection, "classical_source_document_references"):
                reference_rows = connection.execute(
                    """
                    SELECT reference_id, source_document_id, target_document_id,
                           source_document, target_document, source_sha256,
                           source_tree_position, source_block_id, target_block_id,
                           target_subtype, relation_type, resolution
                    FROM classical_source_document_references
                    WHERE source_document_id = ? OR target_document_id = ?
                    ORDER BY source_document, source_block_id, target_document,
                             target_block_id, reference_id
                    """,
                    (source_document_id, source_document_id),
                ).fetchall()
                document_references = [
                    {
                        **dict(row),
                        "relation_semantics": "NATIVE_SIYUAN_REFERENCE",
                    }
                    for row in reference_rows
                ]

            match = _mention(matched, passage_start, passage_text)
            results.append({
                "match": match,
                "source": {
                    "source_document_id": source_document_id,
                    "source_work": matched["source_work"],
                    "source_work_label": matched["source_work_label"],
                    "document_role": matched["document_role"],
                    "source_title": matched["source_title"],
                    "document": matched["document"],
                    "source_sha256": matched["source_sha256"],
                    "tree_position": matched["tree_position"],
                    "block_id": matched["block_id"],
                    "section_path": matched["section_path"],
                    "chapter_path": _json_value(matched["chapter_path_json"]),
                    "passage_id": passage_id,
                    "passage_character_start": passage_start,
                    "passage_character_end": matched["passage_end"],
                    "passage_kind": matched["passage_kind"],
                    "passage_text": passage_text,
                },
                "passage_terms": passage_terms,
                "navigational_links": navigational_links,
                "formula_herb_candidates": formula_herb_candidates,
                "contextual_relation_candidates": contextual_relation_candidates,
                "document_references": document_references,
            })

        return {
            "schema_version": 1,
            "query": query,
            "query_semantics": "LEXICAL_SUBSTRING; no alias or clinical-equivalence expansion",
            "filters": {
                "source_work": source_work,
                "document_role": document_role,
                "term_type": term_type,
            },
            "matched_occurrences": len(results),
            "matches": results,
            "relation_policy": {
                "navigational_links": (
                    "same-passage co-occurrence only; not a treatment, efficacy, "
                    "diagnosis, or theory assertion"
                ),
                "formula_herb_candidates": (
                    "source-evidenced unresolved candidates; inspect their own evidence"
                ),
                "contextual_relation_candidates": (
                    "explicit-predicate unresolved candidates; not confirmed facts"
                ),
                "document_references": "existing native SiYuan block references",
            },
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3")
    )
    parser.add_argument("--query", required=True, help="symptom, formula, herb, theory, or point")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--source-work", help="e.g. SHANG_HAN_LUN or JIN_GUI_YAO_LUE")
    parser.add_argument("--document-role", help="e.g. CLASSICAL_CHAPTER or FORMULA_REFERENCE")
    parser.add_argument("--term-type", help="e.g. SYMPTOM, FORMULA, HERB, CLASSICAL_THEORY")
    args = parser.parse_args()
    result = search_classical_knowledge_paths(
        args.db,
        args.query,
        args.limit,
        source_work=args.source_work,
        document_role=args.document_role,
        term_type=args.term_type,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
