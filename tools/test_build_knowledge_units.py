import csv
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_knowledge_units.py")
SPEC = importlib.util.spec_from_file_location("build_knowledge_units", MODULE_PATH)
units = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(units)


class KnowledgeUnitTests(unittest.TestCase):
    def _source(self, path, rows):
        fields = [
            "document", "source_sha256", "tree_position", "block_id",
            "parent_block_id", "parent_node_type", "content_type",
            "heading_level", "section_path", "section_heading_block_ids",
            "characters", "content_text",
        ]
        with gzip.open(path, "wt", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _row(self, **overrides):
        row = {
            "document": "notebook/doc.sy", "source_sha256": "a" * 64,
            "tree_position": "0.1.2", "block_id": "block-1",
            "parent_block_id": "parent-1", "parent_node_type": "NodeDocument",
            "content_type": "PARAGRAPH", "heading_level": "",
            "section_path": "经方 / 桂枝汤",
            "section_heading_block_ids": "heading-1;heading-2",
            "characters": "8", "content_text": "  桂枝汤\n主治太阳中风。 ",
        }
        row.update(overrides)
        return row

    def test_builds_provenance_preserving_machine_units(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "content.csv.gz"
            output = root / "out"
            self._source(source, [self._row(), self._row(
                tree_position="0.2", block_id="block-2",
                content_type="TABLE_CELL", content_text="麻黄"
            )])
            result = units.build(source, output)
            self.assertEqual(result["units"], 2)
            self.assertEqual(units.validate(output / "knowledge_units.jsonl.gz"), 2)
            with gzip.open(output / "knowledge_units.jsonl.gz", "rt", encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream]
            first = records[0]
            self.assertEqual(first["content"]["source_text"], "  桂枝汤\n主治太阳中风。 ")
            self.assertEqual(first["content"]["normalized_text"], "桂枝汤 主治太阳中风。")
            self.assertEqual(first["source"]["document"], "notebook/doc.sy")
            self.assertEqual(first["source"]["block_id"], "block-1")
            self.assertEqual(first["context"]["section_heading_block_ids"], ["heading-1", "heading-2"])
            self.assertEqual(first["semantic_status"], "UNCLASSIFIED")
            self.assertEqual(first["assertion_status"], "NOT_INTERPRETED")
            self.assertEqual(records[1]["unit_type"], "SOURCE_TABLE_CELL")

    def test_unit_id_is_deterministic_and_revision_sensitive(self):
        row = self._row()
        self.assertEqual(units.stable_unit_id(row), units.stable_unit_id(dict(row)))
        changed = dict(row, source_sha256="b" * 64)
        self.assertNotEqual(units.stable_unit_id(row), units.stable_unit_id(changed))

    def test_rejects_unsafe_source_path_and_unknown_content_type(self):
        with self.assertRaises(ValueError):
            units.make_unit(self._row(document="../outside.sy"))
        with self.assertRaises(ValueError):
            units.make_unit(self._row(content_type="UNKNOWN"))

    def test_rejects_duplicate_unit_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "content.csv.gz"
            self._source(source, [self._row(), self._row()])
            with self.assertRaisesRegex(ValueError, "duplicate unit_id"):
                units.build(source, root / "out")


if __name__ == "__main__":
    unittest.main()
