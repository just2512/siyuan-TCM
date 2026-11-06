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
        FROM entity_catalog c
        LEFT JOIN entity_mentions m ON m.entity_id = c.entity_id
        GROUP BY c.entity_id, c.entity_type, c.preferred_label,
                 c.lexical_form, c.identity_status
        ORDER BY c.entity_type, c.lexical_form
    """).fetchall()
    relations = connection.execute("""
        SELECT r.relation_id, r.predicate, r.subject_text, r.object_text,
               r.unit_id, r.document, r.source_sha256, r.tree_position,
               r.block_id, r.sentence_start, r.sentence_end, r.evidence_text,
               r.extraction_rule, r.resolution_status,
               s.entity_id AS subject_entity_id, o.entity_id AS object_entity_id
        FROM semantic_relation_candidates r
        JOIN entity_mentions s ON s.mention_id = r.subject_mention_id
        JOIN entity_mentions o ON o.mention_id = r.object_mention_id
        ORDER BY r.document, r.tree_position, r.sentence_start, r.relation_id
    """).fetchall()
    connection.close()
    for row in entities:
        yield {
            "record_type": "ENTITY",
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "preferred_label": row["preferred_label"],
            "lexical_form": row["lexical_form"],
            "identity_status": row["identity_status"],
            "mention_count": row["mention_count"],
        }
    for row in relations:
        yield {
            "record_type": "RELATION_CANDIDATE",
            "relation_id": row["relation_id"],
            "subject_entity_id": row["subject_entity_id"],
            "subject_text": row["subject_text"],
            "predicate": row["predicate"],
            "object_entity_id": row["object_entity_id"],
            "object_text": row["object_text"],
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
        }


def export(database_path: Path, output_path: Path) -> dict[str, int]:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entity_count = relation_count = 0
    with output_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            import io
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                for record in records(database_path):
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                    if record["record_type"] == "ENTITY":
                        entity_count += 1
                    else:
                        relation_count += 1
    return {"entity_nodes": entity_count, "relation_edges": relation_count}


def validate(database_path: Path, graph_path: Path) -> dict[str, int]:
    expected_entities = set()
    expected_relations = set()
    connection = sqlite3.connect(database_path)
    expected_entities.update(row[0] for row in connection.execute("SELECT entity_id FROM entity_catalog"))
    expected_relations.update(row[0] for row in connection.execute(
        "SELECT relation_id FROM semantic_relation_candidates"
    ))
    connection.close()
    seen_entities, seen_relations = set(), set()
    edge_count = 0
    with gzip.open(graph_path, "rt", encoding="utf-8") as stream:
        for line, raw in enumerate(stream, 1):
            row: dict[str, Any] = json.loads(raw)
            if row["record_type"] == "ENTITY":
                entity_id = row["entity_id"]
                if entity_id in seen_entities:
                    raise ValueError(f"duplicate entity node at line {line}")
                seen_entities.add(entity_id)
            elif row["record_type"] == "RELATION_CANDIDATE":
                relation_id = row["relation_id"]
                if relation_id in seen_relations:
                    raise ValueError(f"duplicate relation edge at line {line}")
                if row["subject_entity_id"] not in expected_entities:
                    raise ValueError(f"unknown subject entity at line {line}")
                if row["object_entity_id"] not in expected_entities:
                    raise ValueError(f"unknown object entity at line {line}")
                if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                    raise ValueError(f"unsafe relation status at line {line}")
                evidence = row["evidence"]
                if evidence["character_end"] <= evidence["character_start"]:
                    raise ValueError(f"invalid evidence span at line {line}")
                if len(evidence["text"]) != evidence["character_end"] - evidence["character_start"]:
                    raise ValueError(f"evidence span length mismatch at line {line}")
                seen_relations.add(relation_id)
                edge_count += 1
            else:
                raise ValueError(f"unknown graph record type at line {line}")
    if seen_entities != expected_entities:
        raise ValueError("entity node coverage does not match SQLite catalog")
    if seen_relations != expected_relations:
        raise ValueError("relation edge coverage does not match SQLite relation table")
    return {"validated_entity_nodes": len(seen_entities), "validated_relation_edges": edge_count}


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
