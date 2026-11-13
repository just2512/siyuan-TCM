from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_contextual_relation_candidates import relation_identity

MODULE_PATH = Path(__file__).with_name("audit_sqlite_contextual_relations.py")
SPEC = importlib.util.spec_from_file_location("audit_sqlite_contextual_relations", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


class SQLiteContextualRelationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "index.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.connection.executescript("""
            CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE content_blocks (
                document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT, content_text TEXT
            );
            CREATE TABLE contextual_term_type_candidates (
                candidate_id TEXT, term TEXT, candidate_type TEXT, rule_id TEXT,
                evidence_document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                unit_id TEXT, character_start INTEGER, character_end INTEGER,
                evidence_start INTEGER, evidence_text TEXT, classification_status TEXT
            );
            CREATE TABLE entity_mentions (
                mention_id TEXT, matched_text TEXT, entity_type TEXT, unit_id TEXT,
                document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                character_start INTEGER, character_end INTEGER
            );
            CREATE TABLE contextual_relation_candidates (
                relation_id TEXT PRIMARY KEY, predicate TEXT, subject_candidate_id TEXT,
                subject_text TEXT, subject_type TEXT, subject_start INTEGER, subject_end INTEGER,
                object_candidate_id TEXT, object_text TEXT, object_type TEXT,
                object_start INTEGER, object_end INTEGER, unit_id TEXT, document TEXT,
                source_sha256 TEXT, tree_position TEXT, block_id TEXT, sentence_start INTEGER,
                sentence_end INTEGER, evidence_text TEXT, predicate_text TEXT,
                extraction_rule TEXT, resolution_status TEXT
            );
        """)
        self.locator = ("a.sy", "sha-a", "0.0", "p1")
        self.source = "头痛辨证为太阳病。"
        self.unit_id = hashlib.sha256("\0".join(self.locator).encode()).hexdigest()
        self.connection.execute("INSERT INTO content_blocks VALUES (?,?,?,?,?)",
                                (*self.locator, self.source))
        self.connection.executemany(
            "INSERT INTO contextual_term_type_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("symptom-id", "头痛", "SYMPTOM", "SYMPTOM_CONTEXT_01",
                 *self.locator[:1], self.locator[1], self.locator[2], self.locator[3],
                 self.unit_id, 0, 2, 0, self.source, "CONTEXT_RULE_CANDIDATE"),
                ("syndrome-id", "太阳病", "SYNDROME", "SYNDROME_CONTEXT_01",
                 *self.locator[:1], self.locator[1], self.locator[2], self.locator[3],
                 self.unit_id, 5, 8, 0, self.source, "CONTEXT_RULE_CANDIDATE"),
            ],
        )
        subject = {"candidate_id": "symptom-id", "character_start": "0", "character_end": "2"}
        obj = {"candidate_id": "syndrome-id", "character_start": "5", "character_end": "8"}
        rid = relation_identity("SYMPTOM_TO_SYNDROME", subject, obj, self.unit_id, 0, len(self.source))
        self.connection.execute(
            "INSERT INTO contextual_relation_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, "SYMPTOM_TO_SYNDROME", "symptom-id", "头痛", "SYMPTOM", 0, 2,
             "syndrome-id", "太阳病", "SYNDROME", 5, 8, self.unit_id, *self.locator,
             0, len(self.source), self.source, "辨证为",
             "SYMPTOM_TO_SYNDROME_EXPLICIT_V1", "UNRESOLVED_CANDIDATE"),
        )
        self.connection.execute("INSERT INTO index_metadata VALUES ('contextual_relation_candidates','1')")
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_accepts_source_grounded_relation_and_reports_zero_predicates(self):
        result = module.audit(self.db)
        self.assertEqual(result["checked_relation_rows"], 1)
        self.assertEqual(result["relation_counts_by_predicate"], {
            "SYMPTOM_TO_SYNDROME": 1, "SYNDROME_TO_TREATMENT": 0, "TREATMENT_TO_FORMULA": 0,
        })

    def test_audits_source_note_point_to_symptom_association_candidates(self):
        source = "中脘穴：胃痛、恶心、呕吐。"
        locator = self.locator
        self.connection.execute(
            "UPDATE content_blocks SET content_text=? WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=?",
            (source, *locator),
        )
        self.connection.execute("DELETE FROM contextual_relation_candidates")
        self.connection.execute("DELETE FROM contextual_term_type_candidates")
        terms = [
            ("point-label", "中脘穴", "ACUPOINT", 0, 3),
            ("symptom-a", "胃痛", "SYMPTOM", 4, 6),
            ("symptom-b", "恶心", "SYMPTOM", 7, 9),
            ("symptom-c", "呕吐", "SYMPTOM", 10, 12),
        ]
        for candidate_id, term, candidate_type, start, end in terms:
            self.connection.execute(
                "INSERT INTO contextual_term_type_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (candidate_id, term, candidate_type, candidate_type + "_RULE",
                 locator[0], locator[1], locator[2], locator[3], self.unit_id,
                 start, end, 0, source, "CONTEXT_RULE_CANDIDATE"),
            )
        subject = {"candidate_id": "point-label", "character_start": "0", "character_end": "3"}
        for candidate_id, term, start, end in (
            ("symptom-a", "胃痛", 4, 6),
            ("symptom-b", "恶心", 7, 9),
            ("symptom-c", "呕吐", 10, 12),
        ):
            obj = {"candidate_id": candidate_id, "character_start": str(start), "character_end": str(end)}
            relation_id = relation_identity(
                "SOURCE_NOTE_ASSOCIATES", subject, obj, self.unit_id, 0, len(source)
            )
            self.connection.execute(
                "INSERT INTO contextual_relation_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (relation_id, "SOURCE_NOTE_ASSOCIATES", "point-label", "中脘穴", "ACUPOINT", 0, 3,
                 candidate_id, term, "SYMPTOM", start, end, self.unit_id, *locator,
                 0, len(source), source, "：", "SOURCE_NOTE_ASSOCIATES_LABEL_V1", "UNRESOLVED_CANDIDATE"),
            )
        self.connection.execute(
            "UPDATE index_metadata SET value='3' WHERE key='contextual_relation_candidates'"
        )
        self.connection.commit()
        result = module.audit(self.db)
        self.assertEqual(result["checked_relation_rows"], 3)
        self.assertEqual(result["relation_counts_by_predicate"]["SOURCE_NOTE_ASSOCIATES"], 3)
        self.assertEqual(result["sentence_and_attribution_boundary_validation"], "PASS")

    def test_rejects_fabricated_relation_identity(self):
        self.connection.execute("UPDATE contextual_relation_candidates SET relation_id='fabricated'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "ID/endpoint identity mismatch"):
            module.audit(self.db)

    def test_rejects_endpoint_candidate_identity_drift(self):
        self.connection.execute("UPDATE contextual_term_type_candidates SET term='白芍' WHERE candidate_id='symptom-id'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "subject endpoint is not a matching SQLite candidate"):
            module.audit(self.db)

    def test_rejects_sentence_evidence_offset_drift(self):
        self.connection.execute("UPDATE contextual_relation_candidates SET sentence_start=1")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "evidence offset/source mismatch"):
            module.audit(self.db)

    def test_rejects_metadata_count_drift(self):
        self.connection.execute("UPDATE index_metadata SET value='0'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "metadata count mismatch"):
            module.audit(self.db)


if __name__ == "__main__":
    unittest.main()
