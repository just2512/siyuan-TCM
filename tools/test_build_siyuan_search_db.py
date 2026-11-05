import csv
import gzip
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_siyuan_search_db.py")
SPEC = importlib.util.spec_from_file_location("build_siyuan_search_db", MODULE_PATH)
search_db = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(search_db)


class SiYuanSearchDatabaseTests(unittest.TestCase):
    def _write_gzip_csv(self, path, fields, rows):
        with gzip.open(path, "wt", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_builds_searchable_sqlite_database_and_imports_relationships(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            relations = root / "relations.csv.gz"
            db = root / "search.sqlite3"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [
                {"document": "book/a.sy", "source_sha256": "hash-a",
                 "tree_position": "0.0", "block_id": "p1",
                 "parent_block_id": "doc", "parent_node_type": "NodeDocument",
                 "content_type": "PARAGRAPH", "heading_level": "",
                 "section_path": "经方 / 桂枝汤", "section_heading_block_ids": "h1;h2",
                 "characters": 10, "content_text": "桂枝汤治疗太阳中风"},
                {"document": "book/b.sy", "source_sha256": "hash-b",
                 "tree_position": "0.1", "block_id": "p2",
                 "parent_block_id": "doc2", "parent_node_type": "NodeDocument",
                 "content_type": "PARAGRAPH", "heading_level": "",
                 "section_path": "中药", "section_heading_block_ids": "h3",
                 "characters": 8, "content_text": "麻黄用于发汗"},
            ])
            self._write_gzip_csv(relations, search_db.RELATION_FIELDS, [
                {"source_document": "book/a.sy", "source_sha256": "hash-a",
                 "source_tree_position": "0.0", "source_block_id": "p1",
                 "source_node_type": "NodeTextMark", "relation_type": "BLOCK_REFERENCE",
                 "target": "target-id", "target_subtype": "d",
                 "target_document": "book/b.sy", "resolution": "RESOLVED_IN_CORPUS"}
            ])
            result = search_db.build_database(content, relations, db)
            self.assertEqual(result["content_blocks"], 2)
            self.assertEqual(result["relationships"], 1)
            self.assertTrue(db.is_file())
            # Three-character Chinese phrase uses trigram FTS when available.
            results = search_db.search_database(db, "桂枝汤")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["document"], "book/a.sy")
            self.assertEqual(results[0]["section_path"], "经方 / 桂枝汤")
            # Two-character Chinese term uses exact substring fallback.
            results = search_db.search_database(db, "麻黄")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["document"], "book/b.sy")
            with sqlite3.connect(db) as connection:
                count = connection.execute("SELECT COUNT(*) FROM node_relationships").fetchone()[0]
            self.assertEqual(count, 1)

    def test_rejects_empty_query(self):
        with self.assertRaises(ValueError):
            search_db.search_database(Path("unused.db"), "  ")


if __name__ == "__main__":
    unittest.main()
