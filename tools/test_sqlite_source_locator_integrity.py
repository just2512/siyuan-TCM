import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("audit_sqlite_source_locator_integrity.py")
SPEC = importlib.util.spec_from_file_location("audit_sqlite_source_locator_integrity", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SQLiteSourceLocatorIntegrityTests(unittest.TestCase):
    def create_database(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            connection.execute("""
                CREATE TABLE content_blocks (
                    document TEXT, source_sha256 TEXT, tree_position TEXT,
                    block_id TEXT, characters INTEGER, content_text TEXT
                )
            """)

    def test_accepts_unique_exact_source_locators(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "search.sqlite3"
            self.create_database(database)
            with sqlite3.connect(database) as connection:
                connection.executemany(
                    "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("a.sy", "hash-a", "0.0", "b1", 4, "桂枝汤。"),
                        ("a.sy", "hash-a", "0.1", "b2", 3, "桂枝。"),
                        ("b.sy", "hash-b", "0.0", None, 2, "当归"),
                    ],
                )
            result = module.audit(database)
            self.assertEqual(result["content_block_rows"], 3)
            self.assertEqual(result["unique_source_locators"], 3)
            self.assertEqual(result["duplicate_locator_groups"], 0)
            self.assertEqual(result["source_locator_validation"], "PASS")

    def test_rejects_ambiguous_locator_even_when_text_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "search.sqlite3"
            self.create_database(database)
            with sqlite3.connect(database) as connection:
                connection.executemany(
                    "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("a.sy", "hash-a", "0.0", "b1", 4, "桂枝汤。"),
                        ("a.sy", "hash-a", "0.0", "b1", 4, "桂枝汤。"),
                    ],
                )
            with self.assertRaisesRegex(ValueError, "source locator integrity failed"):
                module.audit(database)

    def test_rejects_character_length_drift_and_missing_source_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "search.sqlite3"
            self.create_database(database)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?, ?)",
                    ("", "hash-a", "0.0", "b1", 99, "桂枝汤。"),
                )
            with self.assertRaisesRegex(ValueError, "source locator integrity failed"):
                module.audit(database)


if __name__ == "__main__":
    unittest.main()
