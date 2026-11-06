import csv
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_entity_mention_candidates.py")
SPEC = importlib.util.spec_from_file_location("build_entity_mention_candidates", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class EntityMentionCandidateTests(unittest.TestCase):
    def test_extracts_overlapping_mentions_with_exact_spans_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            lexicon = root / "lexicon.csv"
            output = root / "out"
            fields = ["document", "source_sha256", "tree_position", "block_id", "content_type", "section_path", "content_text"]
            with gzip.open(content, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "document": "notes/a.sy", "source_sha256": "a" * 64,
                    "tree_position": "0.1", "block_id": "b1",
                    "content_type": "PARAGRAPH", "section_path": "经方",
                    "content_text": "桂枝汤由桂枝、芍药组成。",
                })
            with lexicon.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["entity_type", "term", "lexicon_version"])
                writer.writeheader()
                writer.writerows([
                    {"entity_type": "FORMULA", "term": "桂枝汤", "lexicon_version": "1.0.0"},
                    {"entity_type": "HERB", "term": "桂枝", "lexicon_version": "1.0.0"},
                    {"entity_type": "HERB", "term": "芍药", "lexicon_version": "1.0.0"},
                ])
            result = module.extract(content, lexicon, output)
            self.assertEqual(result["mentions"], 4)
            path = output / "entity_mention_candidates.csv.gz"
            units_path = root / "knowledge_units.jsonl.gz"
            source_row = {
                "document": "notes/a.sy", "source_sha256": "a" * 64,
                "tree_position": "0.1", "block_id": "b1",
            }
            unit = {
                "unit_id": module.unit_id(source_row),
                "source": {"document": "notes/a.sy", "sha256": "a" * 64,
                           "tree_position": "0.1", "block_id": "b1"},
                "content": {"source_text": "桂枝汤由桂枝、芍药组成。"},
            }
            with gzip.open(units_path, "wt", encoding="utf-8") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            self.assertEqual(module.validate(path, units_path), 4)
            with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r["matched_text"] for r in rows], ["桂枝汤", "桂枝", "桂枝", "芍药"])
            formula = next(r for r in rows if r["entity_type"] == "FORMULA")
            self.assertEqual((formula["character_start"], formula["character_end"]), ("0", "3"))
            self.assertEqual(formula["document"], "notes/a.sy")
            self.assertEqual(formula["resolution_status"], "UNRESOLVED_CANDIDATE")

    def test_aho_corasick_retains_nested_and_repeated_matches(self):
        lexicon = [
            {"entity_type": "FORMULA", "term": "桂枝汤", "lexicon_version": "1.0.0"},
            {"entity_type": "HERB", "term": "桂枝", "lexicon_version": "1.0.0"},
            {"entity_type": "HERB", "term": "芍药", "lexicon_version": "1.0.0"},
        ]
        matches = module.find_matches("桂枝汤与桂枝、芍药；桂枝", module.build_matcher(lexicon))
        self.assertEqual(
            [(start, end, item["term"]) for start, end, item in matches],
            [(0, 2, "桂枝"), (0, 3, "桂枝汤"), (4, 6, "桂枝"),
             (7, 9, "芍药"), (10, 12, "桂枝")],
        )

    def test_rejects_missing_content_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            lexicon = root / "lexicon.csv"
            with gzip.open(content, "wt", encoding="utf-8", newline="") as stream:
                stream.write("document,content_text\\n")
            with lexicon.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["entity_type", "term"])
                writer.writeheader()
                writer.writerow({"entity_type": "HERB", "term": "桂枝"})
            with self.assertRaisesRegex(ValueError, "content index missing fields"):
                module.extract(content, lexicon, root / "out")


if __name__ == "__main__":
    unittest.main()
