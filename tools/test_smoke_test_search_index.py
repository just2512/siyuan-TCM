import sqlite3
import tempfile
import unittest
from pathlib import Path

from smoke_test_search_index import smoke


class SearchIndexSmokeTests(unittest.TestCase):
    def test_smoke_checks_real_sqlite_text_and_entity_source_spans(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "search.sqlite3"
            connection = sqlite3.connect(db)
            connection.executescript("""
                CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE content_blocks (
                    document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                    content_type TEXT, section_path TEXT, content_text TEXT
                );
                CREATE TABLE node_relationships (id INTEGER);
                CREATE TABLE entity_mentions (
                    entity_id TEXT, entity_type TEXT, matched_text TEXT,
                    character_start INTEGER, character_end INTEGER, document TEXT,
                    source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                    section_path TEXT, lexicon_version TEXT, resolution_status TEXT, unit_id TEXT
                );
                CREATE TABLE entity_catalog (
                    entity_id TEXT, entity_type TEXT, preferred_label TEXT,
                    lexical_form TEXT, identity_status TEXT
                );
                CREATE TABLE semantic_relation_candidates (id INTEGER, predicate TEXT);
                CREATE TABLE unclassified_term_candidates (id INTEGER);
                CREATE TABLE contextual_term_type_candidates (id INTEGER);
                CREATE TABLE contextual_relation_candidates (
                    relation_id TEXT, predicate TEXT, subject_candidate_id TEXT,
                    subject_text TEXT, subject_type TEXT, subject_start INTEGER, subject_end INTEGER,
                    object_candidate_id TEXT, object_text TEXT, object_type TEXT,
                    object_start INTEGER, object_end INTEGER, unit_id TEXT, document TEXT,
                    source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                    sentence_start INTEGER, sentence_end INTEGER, evidence_text TEXT,
                    predicate_text TEXT, extraction_rule TEXT, resolution_status TEXT
                );
            """)
            text = "桂枝汤治疗太阳中风"
            connection.execute(
                "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("book/a.sy", "sha-a", "0.0", "p1", "PARAGRAPH", "", text),
            )
            connection.execute(
                "INSERT INTO entity_catalog VALUES (?, ?, ?, ?, ?)",
                ("entity-gui-zhi", "FORMULA", "桂枝汤", "桂枝汤", "LEXICAL_ID_ONLY"),
            )
            connection.execute(
                "INSERT INTO entity_mentions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("entity-gui-zhi", "FORMULA", "桂枝汤", 0, 3, "book/a.sy", "sha-a",
                 "0.0", "p1", "", "1.0", "UNRESOLVED_CANDIDATE", "u1"),
            )
            counts = {
                "content_blocks": 1, "relationships": 0, "entity_mentions": 1,
                "lexical_entities": 1, "relation_candidates": 0,
                "unclassified_term_candidates": 0, "contextual_term_type_candidates": 0,
                "contextual_relation_candidates": 0,
            }
            connection.executemany(
                "INSERT INTO index_metadata(key, value) VALUES (?, ?)",
                [("search_backend", "sqlite-instr-fallback")] +
                [(key, str(value)) for key, value in counts.items()],
            )
            connection.commit()
            connection.close()

            result = smoke(db)
            self.assertEqual(result["checks"]["full_text"], "PASS")
            self.assertEqual(result["checks"]["entity_span_and_source"], "PASS")
            self.assertEqual(result["table_counts"]["content_blocks"], 1)
            self.assertEqual(result["relation_predicate_counts"], {
                "FORMULA_CONTAINS_HERB": 0,
                "SYMPTOM_TO_SYNDROME": 0,
                "SYNDROME_TO_TREATMENT": 0,
                "TREATMENT_TO_FORMULA": 0,
            })
            self.assertEqual(result["checks"]["contextual_relation_predicate_queries"], "PASS")


    def test_smoke_checks_contextual_relation_predicate_and_direction(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "search.sqlite3"
            connection = sqlite3.connect(db)
            connection.executescript("""
                CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE content_blocks (
                    document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                    content_type TEXT, section_path TEXT, content_text TEXT
                );
                CREATE TABLE node_relationships (id INTEGER);
                CREATE TABLE entity_mentions (id INTEGER);
                CREATE TABLE entity_catalog (id INTEGER);
                CREATE TABLE semantic_relation_candidates (id INTEGER, predicate TEXT);
                CREATE TABLE unclassified_term_candidates (id INTEGER);
                CREATE TABLE contextual_term_type_candidates (id INTEGER);
                CREATE TABLE contextual_relation_candidates (
                    relation_id TEXT, predicate TEXT, subject_candidate_id TEXT,
                    subject_text TEXT, subject_type TEXT, subject_start INTEGER, subject_end INTEGER,
                    object_candidate_id TEXT, object_text TEXT, object_type TEXT,
                    object_start INTEGER, object_end INTEGER, unit_id TEXT, document TEXT,
                    source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                    sentence_start INTEGER, sentence_end INTEGER, evidence_text TEXT,
                    predicate_text TEXT, extraction_rule TEXT, resolution_status TEXT
                );
            """)
            source = "头痛辨证为太阳中风"
            connection.execute(
                "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("book/a.sy", "sha-a", "0.0", "p1", "PARAGRAPH", "", source),
            )
            connection.execute(
                "INSERT INTO contextual_relation_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("r1", "SYMPTOM_TO_SYNDROME", "s1", "头痛", "SYMPTOM", 0, 2,
                 "z1", "太阳中风", "SYNDROME", 5, 9, "u1", "book/a.sy", "sha-a",
                 "0.0", "p1", 0, 9, source, "辨证为",
                 "SYMPTOM_TO_SYNDROME_EXPLICIT_V1", "UNRESOLVED_CANDIDATE"),
            )
            counts = {
                "content_blocks": 1, "relationships": 0, "entity_mentions": 0,
                "lexical_entities": 0, "relation_candidates": 0,
                "unclassified_term_candidates": 0, "contextual_term_type_candidates": 0,
                "contextual_relation_candidates": 1,
            }
            connection.executemany(
                "INSERT INTO index_metadata(key, value) VALUES (?, ?)",
                [("search_backend", "sqlite-instr-fallback")] +
                [(key, str(value)) for key, value in counts.items()],
            )
            connection.commit()
            connection.close()

            result = smoke(db)
            self.assertEqual(result["checks"]["contextual_relation_evidence"], "PASS")
            self.assertEqual(result["checks"]["contextual_relation_predicate_direction"], "PASS")
            self.assertEqual(result["checks"]["contextual_relation_predicate_queries"], "PASS")
            self.assertEqual(result["relation_predicate_counts"]["SYMPTOM_TO_SYNDROME"], 1)


if __name__ == "__main__":
    unittest.main()
