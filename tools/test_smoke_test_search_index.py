import sqlite3
import smoke_test_search_index as smoke_module
import tempfile
import unittest
from pathlib import Path

from smoke_test_search_index import smoke


class SearchIndexSmokeTests(unittest.TestCase):
    def test_fts_index_schema_and_content_match_every_source_block(self):
        connection = sqlite3.connect(":memory:")
        columns = (
            "document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT, "
            "content_type TEXT, section_path TEXT, content_text TEXT"
        )
        connection.execute("CREATE TABLE content_blocks (" + columns + ")")
        connection.execute("CREATE TABLE content_fts (" + columns + ")")
        rows = [
            ("book/a.sy", "sha-a", "0.0", "p1", "PARAGRAPH", "经方", "桂枝汤治疗太阳中风"),
            ("book/b.sy", "sha-b", "0.1", "p2", "PARAGRAPH", "中药", "麻黄用于发汗"),
        ]
        connection.executemany("INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        connection.executemany("INSERT INTO content_fts VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        smoke_module.validate_full_text_index_schema(connection)
        self.assertEqual(smoke_module.validate_full_text_index_count(connection, "fts5-trigram", 2), 2)
        smoke_module.validate_full_text_index_content_parity(connection)

        connection.execute(
            "UPDATE content_fts SET content_text=? WHERE document=?",
            ("错误索引文本", "book/b.sy"),
        )
        with self.assertRaisesRegex(AssertionError, "content/source mismatch"):
            smoke_module.validate_full_text_index_content_parity(connection)
        connection.close()

        incomplete = sqlite3.connect(":memory:")
        incomplete.execute(
            "CREATE TABLE content_fts (content_text TEXT, document TEXT, block_id TEXT, "
            "content_type TEXT, section_path TEXT)"
        )
        with self.assertRaisesRegex(AssertionError, "schema is incomplete"):
            smoke_module.validate_full_text_index_schema(incomplete)
        incomplete.close()


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
                CREATE TABLE contextual_term_type_candidates (
                    id INTEGER PRIMARY KEY, candidate_id TEXT, term TEXT, candidate_type TEXT,
                    rule_id TEXT, evidence_document TEXT, source_sha256 TEXT, tree_position TEXT,
                    block_id TEXT, unit_id TEXT, character_start INTEGER, character_end INTEGER,
                    evidence_start INTEGER, evidence_text TEXT, classification_status TEXT
                );
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
                "SOURCE_NOTE_ASSOCIATES": 0,
            })
            self.assertEqual(result["checks"]["contextual_relation_predicate_queries"], "PASS")


    def test_smoke_checks_source_note_association_edges_and_acupoint_sources(self):
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
                CREATE TABLE contextual_term_type_candidates (
                    id INTEGER PRIMARY KEY, candidate_id TEXT, term TEXT, candidate_type TEXT,
                    rule_id TEXT, evidence_document TEXT, source_sha256 TEXT, tree_position TEXT,
                    block_id TEXT, unit_id TEXT, character_start INTEGER, character_end INTEGER,
                    evidence_start INTEGER, evidence_text TEXT, classification_status TEXT
                );
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
            source = "月经痛：针灸关元穴。"
            connection.execute(
                "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("note/a.sy", "sha-a", "0.1", "b1", "PARAGRAPH", "", source),
            )
            candidates = [
                ("s1", "月经痛", "SYMPTOM", "RULE_S", 0, 3),
                ("t1", "针灸", "ACUPUNCTURE_TECHNIQUE", "RULE_T", 4, 6),
                ("p1", "关元穴", "ACUPOINT", "RULE_P", 6, 9),
            ]
            connection.executemany(
                "INSERT INTO contextual_term_type_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (i + 1, cid, term, typ, rule, "note/a.sy", "sha-a", "0.1", "b1",
                     "u1", start, end, 0, source, "CONTEXT_RULE_CANDIDATE")
                    for i, (cid, term, typ, rule, start, end) in enumerate(candidates)
                ],
            )
            connection.execute(
                "INSERT INTO contextual_relation_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("r1", "SOURCE_NOTE_ASSOCIATES", "s1", "月经痛", "SYMPTOM", 0, 3,
                 "p1", "关元穴", "ACUPOINT", 6, 9, "u1", "note/a.sy", "sha-a",
                 "0.1", "b1", 0, len(source), source, "：",
                 "SOURCE_NOTE_ASSOCIATES_LABEL_V1", "UNRESOLVED_CANDIDATE"),
            )
            counts = {
                "content_blocks": 1, "relationships": 0, "entity_mentions": 0,
                "lexical_entities": 0, "relation_candidates": 0,
                "unclassified_term_candidates": 0, "contextual_term_type_candidates": 3,
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
            self.assertEqual(result["checks"]["contextual_relation_all_rows_provenance"], "PASS")
            self.assertEqual(result["checks"]["contextual_relation_predicate_queries"], "PASS")
            self.assertEqual(result["relation_predicate_counts"]["SOURCE_NOTE_ASSOCIATES"], 1)

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
                CREATE TABLE contextual_term_type_candidates (
                    id INTEGER PRIMARY KEY, candidate_id TEXT, term TEXT, candidate_type TEXT,
                    rule_id TEXT, evidence_document TEXT, source_sha256 TEXT, tree_position TEXT,
                    block_id TEXT, unit_id TEXT, character_start INTEGER, character_end INTEGER,
                    evidence_start INTEGER, evidence_text TEXT, classification_status TEXT
                );
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
            connection.executemany(
                "INSERT INTO contextual_term_type_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (1, "s1", "头痛", "SYMPTOM", "RULE_S", "book/a.sy", "sha-a", "0.0",
                     "p1", "u1", 0, 2, 0, source, "CONTEXT_RULE_CANDIDATE"),
                    (2, "z1", "太阳中风", "SYNDROME", "RULE_Z", "book/a.sy", "sha-a", "0.0",
                     "p1", "u1", 5, 9, 0, source, "CONTEXT_RULE_CANDIDATE"),
                ],
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
                "unclassified_term_candidates": 0, "contextual_term_type_candidates": 2,
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

            # The real-data validator must inspect every contextual relation row,
            # not merely one row returned by a limited search query.
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            connection.execute(
                "UPDATE contextual_term_type_candidates SET term=? WHERE candidate_id=?",
                ("头痛误写", "s1"),
            )
            connection.commit()
            with self.assertRaisesRegex(AssertionError, "candidate identity/source mismatch"):
                smoke_module.validate_all_contextual_relation_rows(connection)
            connection.execute(
                "UPDATE contextual_term_type_candidates SET term=? WHERE candidate_id=?",
                ("头痛", "s1"),
            )
            connection.execute(
                "UPDATE contextual_relation_candidates SET evidence_text=? WHERE relation_id=?",
                ("头痛辨证为太阳", "r1"),
            )
            connection.commit()
            with self.assertRaisesRegex(AssertionError, "evidence offset mismatch"):
                smoke_module.validate_all_contextual_relation_rows(connection)
            connection.close()


    def test_full_sqlite_scan_validates_every_formula_herb_endpoint_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "audit.sqlite3"
            connection = sqlite3.connect(db)
            connection.row_factory = sqlite3.Row
            connection.executescript("""
                CREATE TABLE content_blocks (
                    document TEXT, source_sha256 TEXT, tree_position TEXT,
                    block_id TEXT, content_text TEXT
                );
                CREATE TABLE entity_mentions (
                    mention_id TEXT, entity_type TEXT, matched_text TEXT,
                    character_start INTEGER, character_end INTEGER, unit_id TEXT,
                    document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT
                );
                CREATE TABLE semantic_relation_candidates (
                    relation_id TEXT, predicate TEXT, subject_mention_id TEXT,
                    subject_text TEXT, object_mention_id TEXT, object_text TEXT,
                    unit_id TEXT, document TEXT, source_sha256 TEXT, tree_position TEXT,
                    block_id TEXT, sentence_start INTEGER, sentence_end INTEGER,
                    evidence_text TEXT
                );
            """)
            connection.executemany(
                "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?)",
                [
                    ("book/a.sy", "sha-a", "0.0", "formula", "桂枝汤主之"),
                    ("book/a.sy", "sha-a", "0.1", "composition", "组成：桂枝、芍药"),
                ],
            )
            connection.executemany(
                "INSERT INTO entity_mentions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("f1", "FORMULA", "桂枝汤", 0, 3, "u-formula",
                     "book/a.sy", "sha-a", "0.0", "formula"),
                    ("h1", "HERB", "桂枝", 3, 5, "u-composition",
                     "book/a.sy", "sha-a", "0.1", "composition"),
                ],
            )
            evidence = "组成：桂枝、芍药"
            connection.execute(
                "INSERT INTO semantic_relation_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("r1", "FORMULA_CONTAINS_HERB", "f1", "桂枝汤", "h1", "桂枝",
                 "u-composition", "book/a.sy", "sha-a", "0.1", "composition",
                 0, len(evidence), evidence),
            )
            self.assertEqual(smoke_module.validate_all_formula_herb_relation_rows(connection), 1)

            # A damaged endpoint offset must be rejected even though the
            # relation row remains discoverable through its lexical IDs.
            connection.execute(
                "UPDATE entity_mentions SET character_start=2 WHERE mention_id='h1'"
            )
            with self.assertRaisesRegex(AssertionError, "object mention span mismatch"):
                smoke_module.validate_all_formula_herb_relation_rows(connection)
            connection.close()

    def test_full_text_index_row_count_matches_source_blocks(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE content_fts (content_text TEXT)")
        connection.executemany(
            "INSERT INTO content_fts(content_text) VALUES (?)",
            [("源文一",), ("源文二",)],
        )
        self.assertEqual(
            smoke_module.validate_full_text_index_count(connection, "fts5-trigram", 2),
            2,
        )
        connection.execute("DELETE FROM content_fts WHERE content_text='源文二'")
        with self.assertRaisesRegex(AssertionError, "full-text index row count mismatch"):
            smoke_module.validate_full_text_index_count(connection, "fts5-trigram", 2)
        self.assertIsNone(
            smoke_module.validate_full_text_index_count(connection, "sqlite-instr-fallback", 2)
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
