#!/usr/bin/env python3
"""Export the lexical entity and evidence-backed relation-candidate graph as JSONL.GZ."""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from build_contextual_relation_candidates import (
    NEGATION_PREFIX,
    PREDICATES,
    RELATION_SCOPE_BREAKS,
    relation_identity,
    sentence_ranges,
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
    )
}
SOURCE_NOTE_RANGE = re.compile(r"[^。！？．\n]+[。！？．]?|\n+")
SOURCE_NOTE_ATTRIBUTION_BOUNDARY = next(iter(RELATION_SCOPE_BREAKS.values()))


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def source_note_ranges(text: str):
    for match in SOURCE_NOTE_RANGE.finditer(text):
        if match.group(0).strip():
            yield match.start(), match.end()


def records(database_path: Path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    entities = connection.execute("""
        SELECT c.entity_id, c.entity_type, c.preferred_label, c.lexical_form,
               c.identity_status, COUNT(m.mention_id) AS mention_count
        FROM entity_catalog c LEFT JOIN entity_mentions m ON m.entity_id = c.entity_id
        GROUP BY c.entity_id, c.entity_type, c.preferred_label, c.lexical_form, c.identity_status
        ORDER BY c.entity_type, c.lexical_form
    """).fetchall()
    relations = connection.execute("""
        SELECT r.relation_id, r.predicate, r.subject_text, r.object_text, r.unit_id,
               r.document, r.source_sha256, r.tree_position, r.block_id,
               r.sentence_start, r.sentence_end, r.evidence_text, r.extraction_rule,
               r.resolution_status,
               s.mention_id AS subject_mention_id, s.entity_id AS subject_entity_id,
               s.entity_type AS subject_entity_type, s.matched_text AS subject_mention_text,
               s.unit_id AS subject_mention_unit_id, s.character_start AS subject_character_start,
               s.character_end AS subject_character_end, s.document AS subject_mention_document,
               s.source_sha256 AS subject_mention_source_sha256,
               s.tree_position AS subject_mention_tree_position, s.block_id AS subject_mention_block_id,
               o.mention_id AS object_mention_id, o.entity_id AS object_entity_id,
               o.entity_type AS object_entity_type, o.matched_text AS object_mention_text,
               o.unit_id AS object_mention_unit_id, o.character_start AS object_character_start,
               o.character_end AS object_character_end, o.document AS object_mention_document,
               o.source_sha256 AS object_mention_source_sha256,
               o.tree_position AS object_mention_tree_position, o.block_id AS object_mention_block_id
        FROM semantic_relation_candidates r
        JOIN entity_mentions s ON s.mention_id = r.subject_mention_id
        JOIN entity_mentions o ON o.mention_id = r.object_mention_id
        ORDER BY r.document, r.tree_position, r.sentence_start, r.relation_id
    """).fetchall()
    contextual_terms = connection.execute("""
        SELECT candidate_id, term, candidate_type, rule_id, evidence_document, source_sha256,
               tree_position, block_id, unit_id, character_start, character_end,
               evidence_start, evidence_text, classification_status
        FROM contextual_term_type_candidates
        ORDER BY evidence_document, tree_position, character_start, candidate_type, rule_id
    """).fetchall()
    contextual_relations = connection.execute("""
        SELECT relation_id, predicate, subject_candidate_id, subject_text, subject_type,
               subject_start, subject_end, object_candidate_id, object_text, object_type,
               object_start, object_end, unit_id, document, source_sha256, tree_position,
               block_id, sentence_start, sentence_end, evidence_text, predicate_text,
               extraction_rule, resolution_status
        FROM contextual_relation_candidates
        ORDER BY document, tree_position, sentence_start, relation_id
    """).fetchall()
    classical_documents = connection.execute("""
        SELECT source_document_id, document, source_work, source_work_label,
               root_document, parent_document, notebook, title, document_depth,
               document_role, chapter_path_json
        FROM classical_source_documents ORDER BY source_work, document
    """).fetchall() if _table_exists(connection, "classical_source_documents") else []
    classical_passages = connection.execute("""
        SELECT passage_id, source_document_id, document, source_work, source_sha256,
               tree_position, block_id, parent_block_id, content_type, section_path,
               character_start, character_end, passage_text, passage_kind
        FROM classical_source_passages ORDER BY document, tree_position, character_start
    """).fetchall() if _table_exists(connection, "classical_source_passages") else []
    classical_mentions = connection.execute("""
        SELECT occurrence_id, passage_id, source_document_id, reference_kind,
               reference_id, entity_id, term_type, term_text, character_start,
               character_end, rule_ids_json, resolution_status
        FROM classical_source_passage_mentions
        ORDER BY passage_id, character_start, character_end, occurrence_id
    """).fetchall() if _table_exists(connection, "classical_source_passage_mentions") else []
    classical_references = connection.execute("""
        SELECT reference_id, source_document_id, target_document_id,
               source_document, target_document, source_sha256, source_tree_position,
               source_block_id, target_block_id, target_subtype, relation_type, resolution
        FROM classical_source_document_references
        ORDER BY source_document, source_block_id, target_document, target_block_id
    """).fetchall() if _table_exists(connection, "classical_source_document_references") else []
    connection.close()
    for row in entities:
        yield {"record_type": "ENTITY", "entity_id": row["entity_id"],
               "entity_type": row["entity_type"], "preferred_label": row["preferred_label"],
               "lexical_form": row["lexical_form"], "identity_status": row["identity_status"],
               "mention_count": row["mention_count"]}
    for row in relations:
        yield {"record_type": "RELATION_CANDIDATE", "relation_id": row["relation_id"],
               "subject_entity_id": row["subject_entity_id"], "subject_text": row["subject_text"],
               "subject_mention": {
                   "mention_id": row["subject_mention_id"], "entity_id": row["subject_entity_id"],
                   "entity_type": row["subject_entity_type"], "matched_text": row["subject_mention_text"],
                   "unit_id": row["subject_mention_unit_id"], "character_start": row["subject_character_start"],
                   "character_end": row["subject_character_end"], "document": row["subject_mention_document"],
                   "source_sha256": row["subject_mention_source_sha256"],
                   "tree_position": row["subject_mention_tree_position"], "block_id": row["subject_mention_block_id"]},
               "predicate": row["predicate"], "object_entity_id": row["object_entity_id"],
               "object_text": row["object_text"],
               "object_mention": {
                   "mention_id": row["object_mention_id"], "entity_id": row["object_entity_id"],
                   "entity_type": row["object_entity_type"], "matched_text": row["object_mention_text"],
                   "unit_id": row["object_mention_unit_id"], "character_start": row["object_character_start"],
                   "character_end": row["object_character_end"], "document": row["object_mention_document"],
                   "source_sha256": row["object_mention_source_sha256"],
                   "tree_position": row["object_mention_tree_position"], "block_id": row["object_mention_block_id"]},
               "evidence": {"unit_id": row["unit_id"], "document": row["document"],
                   "source_sha256": row["source_sha256"], "tree_position": row["tree_position"],
                   "block_id": row["block_id"], "character_start": row["sentence_start"],
                   "character_end": row["sentence_end"], "text": row["evidence_text"]},
               "extraction_rule": row["extraction_rule"], "resolution_status": row["resolution_status"]}
    for row in contextual_terms:
        yield {"record_type": "CONTEXTUAL_TERM_CANDIDATE",
               "candidate_id": row["candidate_id"], "term": row["term"],
               "candidate_type": row["candidate_type"], "rule_id": row["rule_id"],
               "evidence": {"unit_id": row["unit_id"], "document": row["evidence_document"],
                   "source_sha256": row["source_sha256"], "tree_position": row["tree_position"],
                   "block_id": row["block_id"], "character_start": row["character_start"],
                   "character_end": row["character_end"], "evidence_start": row["evidence_start"],
                   "text": row["evidence_text"]},
               "classification_status": row["classification_status"]}
    for row in contextual_relations:
        yield {"record_type": "CONTEXTUAL_RELATION_CANDIDATE",
               "relation_id": row["relation_id"],
               "subject_candidate_id": row["subject_candidate_id"],
               "subject_text": row["subject_text"], "subject_type": row["subject_type"],
               "subject_start": row["subject_start"], "subject_end": row["subject_end"],
               "predicate": row["predicate"], "predicate_text": row["predicate_text"],
               "object_candidate_id": row["object_candidate_id"],
               "object_text": row["object_text"], "object_type": row["object_type"],
               "object_start": row["object_start"], "object_end": row["object_end"],
               "evidence": {"unit_id": row["unit_id"], "document": row["document"],
                   "source_sha256": row["source_sha256"], "tree_position": row["tree_position"],
                   "block_id": row["block_id"], "character_start": row["sentence_start"],
                   "character_end": row["sentence_end"], "text": row["evidence_text"]},
               "extraction_rule": row["extraction_rule"], "resolution_status": row["resolution_status"]}
    for row in classical_documents:
        yield {"record_type": "CLASSICAL_SOURCE_DOCUMENT",
               "source_document_id": row["source_document_id"],
               "document": row["document"], "source_work": row["source_work"],
               "source_work_label": row["source_work_label"],
               "root_document": row["root_document"], "parent_document": row["parent_document"],
               "notebook": row["notebook"], "title": row["title"],
               "document_depth": row["document_depth"], "document_role": row["document_role"],
               "chapter_path_json": row["chapter_path_json"]}
    for row in classical_passages:
        yield {"record_type": "CLASSICAL_SOURCE_PASSAGE",
               "passage_id": row["passage_id"], "source_document_id": row["source_document_id"],
               "document": row["document"], "source_work": row["source_work"],
               "evidence": {"source_sha256": row["source_sha256"],
                   "tree_position": row["tree_position"], "block_id": row["block_id"],
                   "parent_block_id": row["parent_block_id"], "content_type": row["content_type"],
                   "section_path": row["section_path"], "character_start": row["character_start"],
                   "character_end": row["character_end"], "text": row["passage_text"]},
               "passage_kind": row["passage_kind"]}
    for row in classical_mentions:
        yield {"record_type": "CLASSICAL_SOURCE_PASSAGE_MENTION",
               "occurrence_id": row["occurrence_id"], "passage_id": row["passage_id"],
               "source_document_id": row["source_document_id"],
               "reference_kind": row["reference_kind"], "reference_id": row["reference_id"],
               "entity_id": row["entity_id"], "term_type": row["term_type"],
               "term_text": row["term_text"], "character_start": row["character_start"],
               "character_end": row["character_end"], "rule_ids_json": row["rule_ids_json"],
               "resolution_status": row["resolution_status"]}
    for row in classical_references:
        yield {"record_type": "CLASSICAL_SOURCE_DOCUMENT_REFERENCE",
               "reference_id": row["reference_id"],
               "source_document_id": row["source_document_id"],
               "target_document_id": row["target_document_id"],
               "source_document": row["source_document"], "target_document": row["target_document"],
               "source_sha256": row["source_sha256"],
               "source_tree_position": row["source_tree_position"],
               "source_block_id": row["source_block_id"], "target_block_id": row["target_block_id"],
               "target_subtype": row["target_subtype"], "relation_type": row["relation_type"],
               "resolution": row["resolution"]}

def export(database_path: Path, output_path: Path) -> dict[str, int]:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entity_count = relation_count = contextual_term_count = contextual_relation_count = 0
    classical_document_count = classical_passage_count = 0
    classical_mention_count = classical_reference_count = 0
    with output_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            import io
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                for record in records(database_path):
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    if record["record_type"] == "ENTITY":
                        entity_count += 1
                    elif record["record_type"] == "RELATION_CANDIDATE":
                        relation_count += 1
                    elif record["record_type"] == "CONTEXTUAL_TERM_CANDIDATE":
                        contextual_term_count += 1
                    elif record["record_type"] == "CONTEXTUAL_RELATION_CANDIDATE":
                        contextual_relation_count += 1
                    elif record["record_type"] == "CLASSICAL_SOURCE_DOCUMENT":
                        classical_document_count += 1
                    elif record["record_type"] == "CLASSICAL_SOURCE_PASSAGE":
                        classical_passage_count += 1
                    elif record["record_type"] == "CLASSICAL_SOURCE_PASSAGE_MENTION":
                        classical_mention_count += 1
                    elif record["record_type"] == "CLASSICAL_SOURCE_DOCUMENT_REFERENCE":
                        classical_reference_count += 1
    return {"entity_nodes": entity_count, "relation_edges": relation_count,
            "contextual_term_candidates": contextual_term_count,
            "contextual_relation_edges": contextual_relation_count,
            "classical_source_documents": classical_document_count,
            "classical_source_passages": classical_passage_count,
            "classical_source_passage_mentions": classical_mention_count,
            "classical_source_document_references": classical_reference_count}


def validate(database_path: Path, graph_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    expected_entities = {
        row["entity_id"]: (row["entity_type"], row["preferred_label"], row["lexical_form"],
                           row["identity_status"], row["mention_count"])
        for row in connection.execute("""
            SELECT c.entity_id, c.entity_type, c.preferred_label, c.lexical_form,
                   c.identity_status, COUNT(m.mention_id) AS mention_count
            FROM entity_catalog c LEFT JOIN entity_mentions m ON m.entity_id = c.entity_id
            GROUP BY c.entity_id, c.entity_type, c.preferred_label, c.lexical_form, c.identity_status
        """)
    }
    expected_relation_ids = {
        row[0] for row in connection.execute("SELECT relation_id FROM semantic_relation_candidates")
    }
    expected_relations = {
        row["relation_id"]: tuple(row[key] for key in (
            "unit_id", "subject_text", "predicate", "object_text", "document",
            "source_sha256", "tree_position", "block_id", "sentence_start",
            "sentence_end", "evidence_text", "extraction_rule", "resolution_status",
            "subject_entity_id", "object_entity_id", "subject_mention_id",
            "subject_entity_type", "subject_mention_text", "subject_mention_unit_id",
            "subject_character_start", "subject_character_end", "subject_mention_document",
            "subject_mention_source_sha256", "subject_mention_tree_position", "subject_mention_block_id",
            "object_mention_id", "object_entity_type", "object_mention_text", "object_mention_unit_id",
            "object_character_start", "object_character_end", "object_mention_document",
            "object_mention_source_sha256", "object_mention_tree_position", "object_mention_block_id",
        ))
        for row in connection.execute("""
            SELECT r.*,
                   s.mention_id AS subject_mention_id, s.entity_id AS subject_entity_id,
                   s.entity_type AS subject_entity_type, s.matched_text AS subject_mention_text,
                   s.unit_id AS subject_mention_unit_id, s.character_start AS subject_character_start,
                   s.character_end AS subject_character_end, s.document AS subject_mention_document,
                   s.source_sha256 AS subject_mention_source_sha256,
                   s.tree_position AS subject_mention_tree_position, s.block_id AS subject_mention_block_id,
                   o.mention_id AS object_mention_id, o.entity_id AS object_entity_id,
                   o.entity_type AS object_entity_type, o.matched_text AS object_mention_text,
                   o.unit_id AS object_mention_unit_id, o.character_start AS object_character_start,
                   o.character_end AS object_character_end, o.document AS object_mention_document,
                   o.source_sha256 AS object_mention_source_sha256,
                   o.tree_position AS object_mention_tree_position, o.block_id AS object_mention_block_id
            FROM semantic_relation_candidates r
            JOIN entity_mentions s ON s.mention_id = r.subject_mention_id
            JOIN entity_mentions o ON o.mention_id = r.object_mention_id
        """)
    }
    expected_contextual_relations = {row[0] for row in connection.execute("SELECT relation_id FROM contextual_relation_candidates")}
    expected_contextual_terms = {
        tuple(row)
        for row in connection.execute("""
            SELECT candidate_id, term, candidate_type, rule_id, evidence_document, source_sha256,
                   tree_position, block_id, unit_id, character_start, character_end,
                   evidence_start, evidence_text, classification_status
            FROM contextual_term_type_candidates
        """)
    }
    contextual_endpoint_types = {
        "SYMPTOM_TO_SYNDROME": ("SYMPTOM", "SYNDROME"),
        "SYNDROME_TO_TREATMENT": ("SYNDROME", "TREATMENT"),
        "TREATMENT_TO_FORMULA": ("TREATMENT", "FORMULA"),
    }
    seen_entities, seen_relations, seen_contextual_relations, seen_contextual_terms = set(), set(), set(), set()
    edge_count = contextual_edge_count = contextual_term_count = 0
    with gzip.open(graph_path, "rt", encoding="utf-8") as stream:
        for line, raw in enumerate(stream, 1):
            row: dict[str, Any] = json.loads(raw)
            kind = row["record_type"]
            if kind == "ENTITY":
                entity_id = row["entity_id"]
                if entity_id in seen_entities:
                    raise ValueError(f"duplicate entity node at line {line}")
                expected = expected_entities.get(entity_id)
                exported = (row["entity_type"], row["preferred_label"], row["lexical_form"],
                            row["identity_status"], row["mention_count"])
                if expected is None or expected != exported:
                    raise ValueError(f"entity graph/SQLite mismatch at line {line}")
                seen_entities.add(entity_id)
            elif kind == "RELATION_CANDIDATE":
                relation_id = row["relation_id"]
                if relation_id in seen_relations:
                    raise ValueError(f"duplicate relation edge at line {line}")
                evidence = row["evidence"]
                expected = expected_relations.get(relation_id)
                exported = (
                    evidence["unit_id"], row["subject_text"], row["predicate"], row["object_text"],
                    evidence["document"], evidence["source_sha256"], evidence["tree_position"],
                    evidence["block_id"], evidence["character_start"], evidence["character_end"],
                    evidence["text"], row["extraction_rule"], row["resolution_status"],
                    row["subject_entity_id"], row["object_entity_id"],
                    row["subject_mention"]["mention_id"], row["subject_mention"]["entity_type"],
                    row["subject_mention"]["matched_text"], row["subject_mention"]["unit_id"],
                    row["subject_mention"]["character_start"], row["subject_mention"]["character_end"],
                    row["subject_mention"]["document"], row["subject_mention"]["source_sha256"],
                    row["subject_mention"]["tree_position"], row["subject_mention"]["block_id"],
                    row["object_mention"]["mention_id"], row["object_mention"]["entity_type"],
                    row["object_mention"]["matched_text"], row["object_mention"]["unit_id"],
                    row["object_mention"]["character_start"], row["object_mention"]["character_end"],
                    row["object_mention"]["document"], row["object_mention"]["source_sha256"],
                    row["object_mention"]["tree_position"], row["object_mention"]["block_id"],
                )
                if expected is None or expected != exported:
                    raise ValueError(f"relation graph/SQLite mismatch at line {line}")
                if row["subject_entity_id"] not in expected_entities or row["object_entity_id"] not in expected_entities:
                    raise ValueError(f"unknown relation endpoint at line {line}")
                if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                    raise ValueError(f"unsafe relation status at line {line}")
                for role in ("subject_mention", "object_mention"):
                    endpoint = row[role]
                    expected_endpoint_type = "FORMULA" if role == "subject_mention" else "HERB"
                    if (row["predicate"] != "FORMULA_CONTAINS_HERB"
                        or endpoint["entity_id"] not in expected_entities
                        or endpoint["entity_type"] != expected_endpoint_type):
                        raise ValueError(f"invalid {role} relation endpoint direction/type at line {line}")
                    if endpoint["matched_text"] != (row["subject_text"] if role == "subject_mention" else row["object_text"]):
                        raise ValueError(f"{role} text mismatch at line {line}")
                    endpoint_source = connection.execute("""SELECT content_text FROM content_blocks
                        WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=? LIMIT 1""",
                        (endpoint["document"], endpoint["source_sha256"], endpoint["tree_position"], endpoint["block_id"])).fetchone()
                    left, right = endpoint["character_start"], endpoint["character_end"]
                    if (endpoint_source is None or left < 0 or right <= left
                        or right > len(endpoint_source[0])
                        or endpoint_source[0][left:right] != endpoint["matched_text"]):
                        raise ValueError(f"{role} source span mismatch at line {line}")
                if row["subject_mention"]["mention_id"] == row["object_mention"]["mention_id"]:
                    raise ValueError(f"relation endpoints resolve to the same mention at line {line}")
                evidence = row["evidence"]
                start, end = evidence["character_start"], evidence["character_end"]
                source = connection.execute("""SELECT content_text FROM content_blocks
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=? LIMIT 1""",
                    (evidence["document"], evidence["source_sha256"], evidence["tree_position"], evidence["block_id"])).fetchone()
                if (source is None or start < 0 or end <= start
                    or end > len(source[0]) or source[0][start:end] != evidence["text"]):
                    raise ValueError(f"relation evidence mismatch at line {line}")
                seen_relations.add(relation_id)
                edge_count += 1
            elif kind == "CONTEXTUAL_TERM_CANDIDATE":
                evidence = row["evidence"]
                key = (row["candidate_id"], row["term"], row["candidate_type"], row["rule_id"],
                       evidence["document"], evidence["source_sha256"], evidence["tree_position"],
                       evidence["block_id"], evidence["unit_id"], evidence["character_start"],
                       evidence["character_end"], evidence["evidence_start"], evidence["text"],
                       row["classification_status"])
                if key in seen_contextual_terms:
                    raise ValueError(f"duplicate contextual term at line {line}")
                if key not in expected_contextual_terms:
                    raise ValueError(f"contextual term graph/SQLite mismatch at line {line}")
                if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                    raise ValueError(f"unsafe contextual term status at line {line}")
                source = connection.execute("""SELECT content_text FROM content_blocks
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=? LIMIT 1""",
                    (evidence["document"], evidence["source_sha256"], evidence["tree_position"], evidence["block_id"])).fetchone()
                left, right, offset = evidence["character_start"], evidence["character_end"], evidence["evidence_start"]
                if (source is None or offset < 0
                    or offset + len(evidence["text"]) > len(source[0])
                    or evidence["text"] != source[0][offset:offset+len(evidence["text"])]):
                    raise ValueError(f"contextual term evidence mismatch at line {line}")
                if (left < offset or left < 0 or right <= left
                    or right > offset+len(evidence["text"]) or right > len(source[0])):
                    raise ValueError(f"contextual term span invalid at line {line}")
                if evidence["text"][left-offset:right-offset] != row["term"]:
                    raise ValueError(f"contextual term text mismatch at line {line}")
                seen_contextual_terms.add(key)
                contextual_term_count += 1
            elif kind == "CONTEXTUAL_RELATION_CANDIDATE":
                relation_id = row["relation_id"]
                if relation_id in seen_contextual_relations or relation_id not in expected_contextual_relations:
                    raise ValueError(f"duplicate or unknown contextual relation at line {line}")
                if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                    raise ValueError(f"unsafe contextual relation status at line {line}")
                evidence = row["evidence"]
                expected = connection.execute("""
                    SELECT predicate, subject_candidate_id, subject_text, subject_type,
                           subject_start, subject_end, object_candidate_id, object_text,
                           object_type, object_start, object_end, unit_id, document,
                           source_sha256, tree_position, block_id, sentence_start,
                           sentence_end, evidence_text, predicate_text, extraction_rule,
                           resolution_status
                    FROM contextual_relation_candidates WHERE relation_id = ?
                """, (relation_id,)).fetchone()
                exported = (
                    row["predicate"], row["subject_candidate_id"], row["subject_text"],
                    row["subject_type"], row["subject_start"], row["subject_end"],
                    row["object_candidate_id"], row["object_text"], row["object_type"],
                    row["object_start"], row["object_end"], evidence["unit_id"],
                    evidence["document"], evidence["source_sha256"], evidence["tree_position"],
                    evidence["block_id"], evidence["character_start"], evidence["character_end"],
                    evidence["text"], row["predicate_text"], row["extraction_rule"],
                    row["resolution_status"],
                )
                if expected is None or tuple(expected) != exported:
                    raise ValueError(f"contextual relation graph/SQLite mismatch at line {line}")
                source_note_association = row["predicate"] == "SOURCE_NOTE_ASSOCIATES"
                endpoint_types = contextual_endpoint_types.get(row["predicate"])
                if source_note_association:
                    if frozenset((row["subject_type"], row["object_type"])) not in SOURCE_NOTE_ASSOCIATION_PAIRS:
                        raise ValueError(f"source-note association endpoint types invalid at line {line}")
                elif endpoint_types != (row["subject_type"], row["object_type"]):
                    raise ValueError(f"contextual relation endpoint types invalid at line {line}")
                for candidate_id, term, candidate_type, left, right, role in (
                    (row["subject_candidate_id"], row["subject_text"], row["subject_type"],
                     row["subject_start"], row["subject_end"], "subject"),
                    (row["object_candidate_id"], row["object_text"], row["object_type"],
                     row["object_start"], row["object_end"], "object"),
                ):
                    if candidate_type in {"FORMULA", "POINT"}:
                        # Formula and lexicon-backed POINT endpoints originate from
                        # entity_mentions; discovered ACUPOINT/technique terms remain
                        # contextual candidates until the lexicon is reviewed.
                        endpoint = connection.execute("""
                            SELECT 1 FROM entity_mentions
                            WHERE mention_id = ? AND matched_text = ? AND entity_type = ?
                              AND unit_id = ? AND document = ? AND source_sha256 = ?
                              AND tree_position = ? AND block_id = ?
                              AND character_start = ? AND character_end = ?
                            LIMIT 1
                        """, (candidate_id, term, candidate_type, evidence["unit_id"],
                              evidence["document"], evidence["source_sha256"], evidence["tree_position"],
                              evidence["block_id"], left, right)).fetchone()
                    else:
                        endpoint = connection.execute("""
                            SELECT 1 FROM contextual_term_type_candidates
                            WHERE candidate_id = ? AND term = ? AND candidate_type = ?
                              AND unit_id = ? AND evidence_document = ? AND source_sha256 = ?
                              AND tree_position = ? AND block_id = ?
                              AND character_start = ? AND character_end = ?
                            LIMIT 1
                        """, (candidate_id, term, candidate_type, evidence["unit_id"],
                              evidence["document"], evidence["source_sha256"], evidence["tree_position"],
                              evidence["block_id"], left, right)).fetchone()
                    if endpoint is None:
                        raise ValueError(f"contextual relation {role} is not a matching SQLite term candidate at line {line}")
                evidence = row["evidence"]
                start, end = evidence["character_start"], evidence["character_end"]
                source = connection.execute("""SELECT content_text FROM content_blocks
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=? LIMIT 1""",
                    (evidence["document"], evidence["source_sha256"], evidence["tree_position"], evidence["block_id"])).fetchone()
                if (source is None or start < 0 or end <= start
                    or end > len(source[0]) or source[0][start:end] != evidence["text"]):
                    raise ValueError(f"contextual relation evidence mismatch at line {line}")
                ss, se = row["subject_start"], row["subject_end"]
                os, oe = row["object_start"], row["object_end"]
                if not (0 <= start <= ss < se <= os < oe <= end <= len(source[0])):
                    raise ValueError(f"contextual relation endpoint spans invalid at line {line}")
                if source[0][ss:se] != row["subject_text"] or source[0][os:oe] != row["object_text"]:
                    raise ValueError(f"contextual relation endpoint text mismatch at line {line}")
                valid_ranges = (
                    set(source_note_ranges(source[0]))
                    if source_note_association else set(sentence_ranges(source[0]))
                )
                if (start, end) not in valid_ranges:
                    raise ValueError(f"contextual relation evidence crosses a source sentence boundary at line {line}")
                predicate = row["predicate"]
                expected_rule = (
                    "SOURCE_NOTE_ASSOCIATES_LABEL_V1"
                    if source_note_association else predicate + "_EXPLICIT_V1"
                )
                if ((predicate not in PREDICATES and not source_note_association)
                    or row["extraction_rule"] != expected_rule):
                    raise ValueError(f"contextual relation predicate/rule mismatch at line {line}")
                between = source[0][se:os]
                if source_note_association:
                    predicate_match = re.search(r"[:：]", between)
                    if (predicate_match is None or predicate_match.group(0) != row["predicate_text"]
                        or re.search(r"(?:不宜|不应|不可|不能|禁用|禁止|勿用|忌用)", between[predicate_match.end():])):
                        raise ValueError(f"source-note association label evidence mismatch at line {line}")
                    scope_break = SOURCE_NOTE_ATTRIBUTION_BOUNDARY
                else:
                    predicate_match = PREDICATES[predicate].search(between)
                    if (predicate_match is None
                        or predicate_match.group(0) != row["predicate_text"]
                        or NEGATION_PREFIX.search(between[:predicate_match.start()])):
                        raise ValueError(f"contextual relation predicate evidence mismatch at line {line}")
                    scope_break = RELATION_SCOPE_BREAKS.get(predicate)
                if scope_break and scope_break.search(between):
                    raise ValueError(f"contextual relation crosses a source-attribution boundary at line {line}")
                expected_id = relation_identity(
                    predicate,
                    {"candidate_id": row["subject_candidate_id"],
                     "character_start": str(ss), "character_end": str(se)},
                    {"candidate_id": row["object_candidate_id"],
                     "character_start": str(os), "character_end": str(oe)},
                    evidence["unit_id"], start, end,
                )
                if relation_id != expected_id:
                    raise ValueError(f"contextual relation identity mismatch at line {line}")
                seen_contextual_relations.add(relation_id)
                contextual_edge_count += 1
            else:
                raise ValueError(f"unknown graph record type at line {line}")
    connection.close()
    if seen_entities != set(expected_entities):
        raise ValueError("entity node coverage does not match SQLite catalog")
    if seen_relations != expected_relation_ids:
        raise ValueError("relation edge coverage does not match SQLite relation table")
    if seen_contextual_terms != expected_contextual_terms:
        raise ValueError("contextual term coverage does not match SQLite candidates")
    if seen_contextual_relations != expected_contextual_relations:
        raise ValueError("contextual relation coverage does not match SQLite candidates")
    return {"validated_entity_nodes": len(seen_entities), "validated_relation_edges": edge_count,
            "validated_contextual_term_candidates": contextual_term_count,
            "validated_contextual_relation_edges": contextual_edge_count}

def write_validation_report(path: Path, result: dict) -> None:
    report = {"schema_version": 1, **result}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/semantic_graph.jsonl.gz"))
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--report", type=Path,
                        help="Optional JSON file for the graph/SQLite validation summary.")
    args = parser.parse_args()
    if args.validate:
        result = validate(args.db, args.output)
    else:
        export(args.db, args.output)
        result = validate(args.db, args.output)
    if args.report:
        write_validation_report(args.report, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
