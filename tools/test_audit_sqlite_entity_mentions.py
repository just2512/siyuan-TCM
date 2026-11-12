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


def expected_mention_id(unit_id, entity_type, start, end, matched_text):
    raw = "\0".join((unit_id, entity_type, str(start), str(end), matched_text))
    return hashlib.sha256(raw.encode()).hexdigest()


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
            (expected_mention_id(unit_id, "FORMULA", 0, 3, "桂枝汤"), "e1", unit_id, "FORMULA", "桂枝汤", 0, 3, *locator,
             "PARAGRAPH", "经方", "v1", "LEXICON", "UNRESOLVED_CANDIDATE"),
            (expected_mention_id(unit_id, "FORMULA", 4, 7, "桂枝汤"), "e1", unit_id, "FORMULA", "桂枝汤", 4, 7, *locator,
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
        self.connection.execute(
            "UPDATE content_blocks SET content_text='X桂枝汤，桂枝汤'"
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "source span mismatch"):
            module.audit(self.db)

    def test_rejects_unit_id_not_derived_from_source_locator(self):
        self.connection.execute("UPDATE entity_mentions SET unit_id='wrong' WHERE character_start=0")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "unit_id/source locator mismatch"):
            module.audit(self.db)

    def test_rejects_unresolvable_source_locator(self):
        wrong_unit = module.source_unit_id("book/a.sy", "sha-a", "0.0", "missing")
        wrong_mention_id = expected_mention_id(wrong_unit, "FORMULA", 0, 3, "桂枝汤")
        self.connection.execute(
            "UPDATE entity_mentions SET block_id='missing', unit_id=?, mention_id=? "
            "WHERE character_start=0",
            (wrong_unit, wrong_mention_id),
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "source locator cannot be resolved"):
            module.audit(self.db)

    def test_rejects_mention_id_not_derived_from_occurrence(self):
        self.connection.execute(
            "UPDATE entity_mentions SET mention_id='fabricated-id' WHERE character_start=0"
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "ID/occurrence identity mismatch"):
            module.audit(self.db)

    def test_rejects_entity_catalog_type_drift(self):
        self.connection.execute("UPDATE entity_catalog SET entity_type='HERB' WHERE entity_id='e1'")
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "catalog type mismatch"):
            module.audit(self.db)


if __name__ == "__main__":
    unittest.main()
