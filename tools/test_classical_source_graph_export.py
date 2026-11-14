import csv
import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_siyuan_search_db import CONTENT_FIELDS, ENTITY_FIELDS, ENTITY_REGISTRY_FIELDS, RELATION_FIELDS, build_database
from export_semantic_graph import export, validate


def write_csv_gzip(path, fields, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def create_classical_tables(connection):
    connection.executescript("""
        CREATE TABLE classical_source_documents (
            source_document_id TEXT PRIMARY KEY, document TEXT NOT NULL UNIQUE,
            source_work TEXT NOT NULL, source_work_label TEXT NOT NULL,
            root_document TEXT NOT NULL, parent_document TEXT NOT NULL,
            notebook TEXT NOT NULL, title TEXT NOT NULL, document_depth INTEGER NOT NULL,
            document_role TEXT NOT NULL, chapter_path_json TEXT NOT NULL
        );
        CREATE TABLE classical_source_passages (
            passage_id TEXT PRIMARY KEY, source_document_id TEXT NOT NULL,
            document TEXT NOT NULL, source_work TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            tree_position TEXT NOT NULL, block_id TEXT NOT NULL, parent_block_id TEXT NOT NULL,
            content_type TEXT NOT NULL, section_path TEXT NOT NULL,
            character_start INTEGER NOT NULL, character_end INTEGER NOT NULL,
            passage_text TEXT NOT NULL, passage_kind TEXT NOT NULL
        );
        CREATE TABLE classical_source_passage_mentions (
            occurrence_id TEXT PRIMARY KEY, passage_id TEXT NOT NULL,
            source_document_id TEXT NOT NULL, reference_kind TEXT NOT NULL,
            reference_id TEXT NOT NULL, entity_id TEXT NOT NULL, term_type TEXT NOT NULL,
            term_text TEXT NOT NULL, character_start INTEGER NOT NULL,
            character_end INTEGER NOT NULL, rule_ids_json TEXT NOT NULL,
            resolution_status TEXT NOT NULL
        );
        CREATE TABLE classical_source_document_references (
            reference_id TEXT PRIMARY KEY, source_document_id TEXT NOT NULL,
            target_document_id TEXT NOT NULL, source_document TEXT NOT NULL,
            target_document TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            source_tree_position TEXT NOT NULL, source_block_id TEXT NOT NULL,
            target_block_id TEXT NOT NULL, target_subtype TEXT NOT NULL,
            relation_type TEXT NOT NULL, resolution TEXT NOT NULL
        );
    """)


class ClassicalSourceGraphExportTests(unittest.TestCase):
    def test_exports_and_validates_passages_mentions_and_native_document_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content_path = root / "content.csv.gz"
            mentions_path = root / "mentions.csv.gz"
            registry_path = root / "registry.csv"
            relationships_path = root / "relationships.csv.gz"
            database = root / "search.sqlite3"
            graph = root / "semantic_graph.jsonl.gz"

            source_text = "桂枝汤用桂枝。恶寒。"
            target_text = "阴阳应象大论。"
            write_csv_gzip(content_path, CONTENT_FIELDS, [
                {
                    "document": "shanghan/太阳.sy", "source_sha256": "sha-a",
                    "tree_position": "0.1", "block_id": "a1", "content_type": "PARAGRAPH",
                    "characters": len(source_text), "content_text": source_text,
                },
                {
                    "document": "neijing/阴阳应象大论.sy", "source_sha256": "sha-b",
                    "tree_position": "0.1", "block_id": "b1", "content_type": "PARAGRAPH",
                    "characters": len(target_text), "content_text": target_text,
                },
            ])
            write_csv_gzip(mentions_path, ENTITY_FIELDS, [
                {
                    "mention_id": "f1", "unit_id": "u1", "entity_type": "FORMULA",
                    "matched_text": "桂枝汤", "character_start": 0, "character_end": 3,
                    "document": "shanghan/太阳.sy", "source_sha256": "sha-a",
                    "tree_position": "0.1", "block_id": "a1", "content_type": "PARAGRAPH",
                    "section_path": "太阳", "lexicon_version": "1.3.0",
                    "extraction_method": "EXACT_LEXICON_MATCH",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                },
                {
                    "mention_id": "h1", "unit_id": "u1", "entity_type": "HERB",
                    "matched_text": "桂枝", "character_start": 4, "character_end": 6,
                    "document": "shanghan/太阳.sy", "source_sha256": "sha-a",
                    "tree_position": "0.1", "block_id": "a1", "content_type": "PARAGRAPH",
                    "section_path": "太阳", "lexicon_version": "1.3.0",
                    "extraction_method": "EXACT_LEXICON_MATCH",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                },
            ])
            with registry_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=ENTITY_REGISTRY_FIELDS)
                writer.writeheader()
                writer.writerows([
                    {"entity_id": "ef", "entity_type": "FORMULA", "preferred_label": "桂枝汤",
                     "lexical_form": "桂枝汤", "lexicon_version": "1.3.0",
                     "identity_status": "LEXICAL_ID_ONLY"},
                    {"entity_id": "eh", "entity_type": "HERB", "preferred_label": "桂枝",
                     "lexical_form": "桂枝", "lexicon_version": "1.3.0",
                     "identity_status": "LEXICAL_ID_ONLY"},
                ])
            write_csv_gzip(relationships_path, RELATION_FIELDS, [{
                "source_document": "shanghan/太阳.sy", "source_sha256": "sha-a",
                "source_tree_position": "0.1", "source_block_id": "a1",
                "source_node_type": "NodeTextMark", "relation_type": "BLOCK_REFERENCE",
                "target": "b1", "target_subtype": "d",
                "target_document": "neijing/阴阳应象大论.sy",
                "resolution": "RESOLVED_IN_CORPUS",
            }])

            build_database(
                content_path, relationships_path, database,
                mentions_path, None, registry_path,
            )
            with sqlite3.connect(database) as connection:
                connection.execute("""
                    INSERT INTO contextual_term_type_candidates (
                        candidate_id, term, candidate_type, rule_id, evidence_document,
                        source_sha256, tree_position, block_id, unit_id,
                        character_start, character_end, evidence_start, evidence_text,
                        classification_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "ctx-1", "恶寒", "SYMPTOM", "SYMPTOM_RULE",
                    "shanghan/太阳.sy", "sha-a", "0.1", "a1", "u1",
                    7, 9, 0, source_text, "CONTEXT_RULE_CANDIDATE",
                ))
                create_classical_tables(connection)
                connection.executemany("""
                    INSERT INTO classical_source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    ("sd1", "shanghan/太阳.sy", "SHANG_HAN_LUN", "伤寒论",
                     "shanghan.sy", "shanghan.sy", "倪海厦", "太阳篇", 1,
                     "CLASSICAL_CHAPTER", '["伤寒论","注解伤寒论","太阳篇"]'),
                    ("sd2", "neijing/阴阳应象大论.sy", "HUANG_DI_NEI_JING", "黄帝内经",
                     "neijing.sy", "neijing.sy", "书籍", "第五篇 阴阳应象大论", 1,
                     "CLASSICAL_CHAPTER", '["《黄帝内经》","上卷 素问篇","第五篇 阴阳应象大论"]'),
                ])
                connection.executemany("""
                    INSERT INTO classical_source_passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    ("p1", "sd1", "shanghan/太阳.sy", "SHANG_HAN_LUN", "sha-a",
                     "0.1", "a1", "", "PARAGRAPH", "太阳", 0, 7,
                     "桂枝汤用桂枝。", "SENTENCE_OR_CLAUSE"),
                    ("p2", "sd1", "shanghan/太阳.sy", "SHANG_HAN_LUN", "sha-a",
                     "0.1", "a1", "", "PARAGRAPH", "太阳", 7, 10,
                     "恶寒。", "SENTENCE_OR_CLAUSE"),
                    ("p3", "sd2", "neijing/阴阳应象大论.sy", "HUANG_DI_NEI_JING", "sha-b",
                     "0.1", "b1", "", "PARAGRAPH", "阴阳应象大论", 0, len(target_text),
                     target_text, "SENTENCE_OR_CLAUSE"),
                ])
                connection.executemany("""
                    INSERT INTO classical_source_passage_mentions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    ("occ-formula", "p1", "sd1", "ENTITY_MENTION", "f1", "ef",
                     "FORMULA", "桂枝汤", 0, 3, "[]", "UNRESOLVED_CANDIDATE"),
                    ("occ-herb", "p1", "sd1", "ENTITY_MENTION", "h1", "eh",
                     "HERB", "桂枝", 4, 6, "[]", "UNRESOLVED_CANDIDATE"),
                    ("occ-symptom", "p2", "sd1", "CONTEXTUAL_TERM_CANDIDATE", "ctx-1", "",
                     "SYMPTOM", "恶寒", 7, 9, '["SYMPTOM_RULE"]', "CONTEXT_RULE_CANDIDATE"),
                ])
                connection.execute("""
                    INSERT INTO classical_source_document_references VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "native-ref-1", "sd1", "sd2", "shanghan/太阳.sy",
                    "neijing/阴阳应象大论.sy", "sha-a", "0.1", "a1", "b1",
                    "d", "BLOCK_REFERENCE", "RESOLVED_IN_CORPUS",
                ))

            exported = export(database, graph)
            self.assertEqual(exported, {
                "entity_nodes": 2, "relation_edges": 0,
                "contextual_term_candidates": 1, "contextual_relation_edges": 0,
                "classical_source_documents": 2, "classical_source_passages": 3,
                "classical_source_passage_mentions": 3,
                "classical_source_document_references": 1,
                "classical_source_passage_term_links": 0,
            })
            validated = validate(database, graph)
            self.assertEqual(validated, {
                "validated_entity_nodes": 2, "validated_relation_edges": 0,
                "validated_contextual_term_candidates": 1, "validated_contextual_relation_edges": 0,
                "validated_classical_source_documents": 2, "validated_classical_source_passages": 3,
                "validated_classical_source_passage_mentions": 3,
                "validated_classical_source_document_references": 1,
                "validated_classical_source_passage_term_links": 0,
            })

            with gzip.open(graph, "rt", encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream]
            self.assertEqual(
                {row["record_type"] for row in records} - {
                    "ENTITY", "CONTEXTUAL_TERM_CANDIDATE",
                },
                {
                    "CLASSICAL_SOURCE_DOCUMENT", "CLASSICAL_SOURCE_PASSAGE",
                    "CLASSICAL_SOURCE_PASSAGE_MENTION", "CLASSICAL_SOURCE_DOCUMENT_REFERENCE",
                },
            )

            # A graph cannot silently move an occurrence to a different word.
            occurrence = next(row for row in records
                              if row["record_type"] == "CLASSICAL_SOURCE_PASSAGE_MENTION"
                              and row["occurrence_id"] == "occ-herb")
            occurrence["term_text"] = "芍药"
            with gzip.open(graph, "wt", encoding="utf-8") as stream:
                for row in records:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "classical passage mention graph/SQLite mismatch"):
                validate(database, graph)


if __name__ == "__main__":
    unittest.main()
