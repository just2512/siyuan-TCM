from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("audit_sqlite_formula_herb_relations.py")
SPEC = importlib.util.spec_from_file_location("audit_sqlite_formula_herb_relations", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


class SQLiteFormulaHerbRelationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "index.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.connection.executescript("""
            CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE content_blocks (
                document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT, content_text TEXT
            );
            CREATE TABLE entity_mentions (
                mention_id TEXT PRIMARY KEY, unit_id TEXT, entity_type TEXT, matched_text TEXT,
                character_start INTEGER, character_end INTEGER, document TEXT, source_sha256 TEXT,
                tree_position TEXT, block_id TEXT
            );
            CREATE TABLE semantic_relation_candidates (
                relation_id TEXT PRIMARY KEY, unit_id TEXT, subject_mention_id TEXT,
                subject_text TEXT, predicate TEXT, object_mention_id TEXT, object_text TEXT,
                document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                sentence_start INTEGER, sentence_end INTEGER, evidence_text TEXT,
                extraction_rule TEXT, resolution_status TEXT
            );
        """)
        locator = ("a.sy", "sha-a", "0.0", "p1")
        text = "桂枝汤由桂枝组成。"
        self.connection.execute("INSERT INTO content_blocks VALUES (?,?,?,?,?)", (*locator, text))
        unit_id = hashlib.sha256("\0".join(locator).encode()).hexdigest()
        self.connection.executemany(
            "INSERT INTO entity_mentions VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("m-formula", unit_id, "FORMULA", "桂枝汤", 0, 3, *locator),
                ("m-herb", unit_id, "HERB", "桂枝", 4, 6, *locator),
            ],
        )
        rule = "FORMULA_COMPOSITION_EXPLICIT_V1"
        identity = "\0".join(("m-formula", "FORMULA_CONTAINS_HERB", "m-herb",
                               unit_id, "0", str(len(text)), rule))
        rid = hashlib.sha256(identity.encode()).hexdigest()
        self.connection.execute(
            "INSERT INTO semantic_relation_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, unit_id, "m-formula", "桂枝汤", "FORMULA_CONTAINS_HERB",
             "m-herb", "桂枝", *locator, 0, len(text), text, rule, "UNRESOLVED_CANDIDATE"),
        )
        self.connection.execute("INSERT INTO index_metadata VALUES ('relation_candidates','1')")
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_accepts_exact_endpoint_and_evidence_provenance(self):
        result = module.audit(self.db)
        self.assertEqual(result["checked_relation_rows"], 1)
        self.assertEqual(result["relation_counts_by_predicate"], {"FORMULA_CONTAINS_HERB": 1})

    def test_rejects_fabricated_relation_identity(self):
        self.connection.execute("UPDATE semantic_relation_candidates SET relation_id='fabricated'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "ID/endpoint identity mismatch"):
            module.audit(self.db)

    def test_rejects_wrong_endpoint_type(self):
        self.connection.execute("UPDATE entity_mentions SET entity_type='HERB' WHERE mention_id='m-formula'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "endpoint type/text mismatch"):
            module.audit(self.db)

    def test_rejects_evidence_offset_drift(self):
        self.connection.execute("UPDATE semantic_relation_candidates SET sentence_start=1")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "evidence offset mismatch"):
            module.audit(self.db)

    def test_rejects_metadata_count_drift(self):
        self.connection.execute("UPDATE index_metadata SET value='2' WHERE key='relation_candidates'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "metadata count mismatch"):
            module.audit(self.db)


if __name__ == "__main__":
    unittest.main()
