from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("audit_sqlite_entity_mentions.py")
SPEC = importlib.util.spec_from_file_location("audit_sqlite_entity_mentions", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


class SQLiteEntityMentionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "index.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.connection.executescript("""
            CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE content_blocks (
                document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                content_type TEXT, section_path TEXT, content_text TEXT
            );
            CREATE TABLE entity_catalog (entity_id TEXT PRIMARY KEY, entity_type TEXT);
            CREATE TABLE entity_mentions (
                mention_id TEXT PRIMARY KEY, entity_id TEXT, unit_id TEXT, entity_type TEXT,
                matched_text TEXT, character_start INTEGER, character_end INTEGER,
                document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                content_type TEXT, section_path TEXT, lexicon_version TEXT,
                extraction_method TEXT, resolution_status TEXT
            );
        """)
        locator = ("book/a.sy", "sha-a", "0.0", "p1")
        unit_id = hashlib.sha256("\0".join(locator).encode()).hexdigest()
        self.connection.execute(
            "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?, ?)",
            (*locator, "PARAGRAPH", "经方", "桂枝汤，桂枝汤"),
        )
        self.connection.execute("INSERT INTO entity_catalog VALUES ('e1', 'FORMULA')")
        rows = [
            ("m1", "e1", unit_id, "FORMULA", "桂枝汤", 0, 3, *locator,
             "PARAGRAPH", "经方", "v1", "LEXICON", "UNRESOLVED_CANDIDATE"),
            ("m2", "e1", unit_id, "FORMULA", "桂枝汤", 4, 7, *locator,
             "PARAGRAPH", "经方", "v1", "LEXICON", "UNRESOLVED_CANDIDATE"),
        ]
        self.connection.executemany("INSERT INTO entity_mentions VALUES (" + ",".join("?" for _ in rows[0]) + ")", rows)
        self.connection.execute("INSERT INTO index_metadata VALUES ('entity_mentions', '2')")
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_preserves_and_validates_distinct_repeated_occurrences(self):
        result = module.audit(self.db)
        self.assertEqual(result["checked_entity_mentions"], 2)
        self.assertEqual(result["mention_counts_by_entity_type"], {"FORMULA": 2})

    def test_rejects_source_offset_substitution(self):
        self.connection.execute("UPDATE entity_mentions SET character_start=1 WHERE mention_id='m1'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "source span mismatch"):
            module.audit(self.db)

    def test_rejects_unit_id_not_derived_from_source_locator(self):
        self.connection.execute("UPDATE entity_mentions SET unit_id='wrong' WHERE mention_id='m1'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "unit_id/source locator mismatch"):
            module.audit(self.db)

    def test_rejects_unresolvable_source_locator(self):
        self.connection.execute("UPDATE entity_mentions SET block_id='missing' WHERE mention_id='m1'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "unit_id/source locator mismatch"):
            module.audit(self.db)

    def test_rejects_entity_catalog_type_drift(self):
        self.connection.execute("UPDATE entity_catalog SET entity_type='HERB' WHERE entity_id='e1'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "catalog type mismatch"):
            module.audit(self.db)


if __name__ == "__main__":
    unittest.main()
