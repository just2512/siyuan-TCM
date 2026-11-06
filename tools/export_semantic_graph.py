#!/usr/bin/env python3
"""Export the lexical entity and evidence-backed relation-candidate graph as JSONL.GZ."""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from pathlib import Path
from typing import Any


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
               r.resolution_status, s.entity_id AS subject_entity_id, o.entity_id AS object_entity_id
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
    connection.close()
    for row in entities:
        yield {"record_type": "ENTITY", "entity_id": row["entity_id"],
               "entity_type": row["entity_type"], "preferred_label": row["preferred_label"],
               "lexical_form": row["lexical_form"], "identity_status": row["identity_status"],
               "mention_count": row["mention_count"]}
    for row in relations:
        yield {"record_type": "RELATION_CANDIDATE", "relation_id": row["relation_id"],
               "subject_entity_id": row["subject_entity_id"], "subject_text": row["subject_text"],
               "predicate": row["predicate"], "object_entity_id": row["object_entity_id"],
               "object_text": row["object_text"],
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

def export(database_path: Path, output_path: Path) -> dict[str, int]:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entity_count = relation_count = contextual_term_count = contextual_relation_count = 0
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
    return {"entity_nodes": entity_count, "relation_edges": relation_count,
            "contextual_term_candidates": contextual_term_count,
            "contextual_relation_edges": contextual_relation_count}


def validate(database_path: Path, graph_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(database_path)
    expected_entities = {row[0] for row in connection.execute("SELECT entity_id FROM entity_catalog")}
    expected_relations = {row[0] for row in connection.execute("SELECT relation_id FROM semantic_relation_candidates")}
    expected_contextual_relations = {row[0] for row in connection.execute("SELECT relation_id FROM contextual_relation_candidates")}
    expected_contextual_terms = connection.execute("SELECT COUNT(*) FROM contextual_term_type_candidates").fetchone()[0]
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
                seen_entities.add(entity_id)
            elif kind == "RELATION_CANDIDATE":
                relation_id = row["relation_id"]
                if relation_id in seen_relations:
                    raise ValueError(f"duplicate relation edge at line {line}")
                if row["subject_entity_id"] not in expected_entities or row["object_entity_id"] not in expected_entities:
                    raise ValueError(f"unknown relation endpoint at line {line}")
                if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                    raise ValueError(f"unsafe relation status at line {line}")
                evidence = row["evidence"]
                start, end = evidence["character_start"], evidence["character_end"]
                source = connection.execute("""SELECT content_text FROM content_blocks
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=? LIMIT 1""",
                    (evidence["document"], evidence["source_sha256"], evidence["tree_position"], evidence["block_id"])).fetchone()
                if source is None or end <= start or source[0][start:end] != evidence["text"]:
                    raise ValueError(f"relation evidence mismatch at line {line}")
                seen_relations.add(relation_id)
                edge_count += 1
            elif kind == "CONTEXTUAL_TERM_CANDIDATE":
                evidence = row["evidence"]
                key = (row["candidate_id"], row["candidate_type"], row["rule_id"], evidence["unit_id"], evidence["character_start"], evidence["character_end"])
                if key in seen_contextual_terms:
                    raise ValueError(f"duplicate contextual term at line {line}")
                if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                    raise ValueError(f"unsafe contextual term status at line {line}")
                source = connection.execute("""SELECT content_text FROM content_blocks
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=? LIMIT 1""",
                    (evidence["document"], evidence["source_sha256"], evidence["tree_position"], evidence["block_id"])).fetchone()
                left, right, offset = evidence["character_start"], evidence["character_end"], evidence["evidence_start"]
                if source is None or evidence["text"] != source[0][offset:offset+len(evidence["text"])]:
                    raise ValueError(f"contextual term evidence mismatch at line {line}")
                if left < offset or right <= left or right > offset+len(evidence["text"]):
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
                endpoint_types = contextual_endpoint_types.get(row["predicate"])
                if endpoint_types != (row["subject_type"], row["object_type"]):
                    raise ValueError(f"contextual relation endpoint types invalid at line {line}")
                for candidate_id, term, candidate_type, left, right, role in (
                    (row["subject_candidate_id"], row["subject_text"], row["subject_type"],
                     row["subject_start"], row["subject_end"], "subject"),
                    (row["object_candidate_id"], row["object_text"], row["object_type"],
                     row["object_start"], row["object_end"], "object"),
                ):
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
                if source is None or end <= start or source[0][start:end] != evidence["text"]:
                    raise ValueError(f"contextual relation evidence mismatch at line {line}")
                ss, se = row["subject_start"], row["subject_end"]
                os, oe = row["object_start"], row["object_end"]
                if not (start <= ss < se <= os < oe <= end):
                    raise ValueError(f"contextual relation endpoint spans invalid at line {line}")
                if source[0][ss:se] != row["subject_text"] or source[0][os:oe] != row["object_text"]:
                    raise ValueError(f"contextual relation endpoint text mismatch at line {line}")
                if row["predicate_text"] not in source[0][se:os]:
                    raise ValueError(f"contextual relation predicate mismatch at line {line}")
                seen_contextual_relations.add(relation_id)
                contextual_edge_count += 1
            else:
                raise ValueError(f"unknown graph record type at line {line}")
    connection.close()
    if seen_entities != expected_entities:
        raise ValueError("entity node coverage does not match SQLite catalog")
    if seen_relations != expected_relations:
        raise ValueError("relation edge coverage does not match SQLite relation table")
    if len(seen_contextual_terms) != expected_contextual_terms:
        raise ValueError("contextual term coverage does not match SQLite candidates")
    if seen_contextual_relations != expected_contextual_relations:
        raise ValueError("contextual relation coverage does not match SQLite candidates")
    return {"validated_entity_nodes": len(seen_entities), "validated_relation_edges": edge_count,
            "validated_contextual_term_candidates": contextual_term_count,
            "validated_contextual_relation_edges": contextual_edge_count}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/semantic_graph.jsonl.gz"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        result = validate(args.db, args.output)
    else:
        result = export(args.db, args.output)
        validate(args.db, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
