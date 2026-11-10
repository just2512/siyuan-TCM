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
            self.assertEqual([r["matched_text"] for r in rows], ["桂枝", "桂枝汤", "桂枝", "芍药"])
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

    def test_longer_formula_name_suppresses_nested_formula_but_keeps_herbs(self):
        lexicon = [
            {"entity_type": "FORMULA", "term": "芍药甘草汤", "lexicon_version": "1.2.0"},
            {"entity_type": "FORMULA", "term": "乌头麻黄黄芪芍药甘草汤", "lexicon_version": "1.2.0"},
            {"entity_type": "HERB", "term": "乌头", "lexicon_version": "1.2.0"},
            {"entity_type": "HERB", "term": "芍药", "lexicon_version": "1.2.0"},
            {"entity_type": "HERB", "term": "甘草", "lexicon_version": "1.2.0"},
        ]
        matches = module.find_matches(
            "乌头麻黄黄芪芍药甘草汤主之", module.build_matcher(lexicon)
        )
        formulas = [item["term"] for _, _, item in matches if item["entity_type"] == "FORMULA"]
        herbs = [item["term"] for _, _, item in matches if item["entity_type"] == "HERB"]
        self.assertEqual(formulas, ["乌头麻黄黄芪芍药甘草汤", "芍药甘草汤"])
        self.assertEqual(herbs, ["乌头", "芍药", "甘草"])
        formula_spans = [
            (start, end, item["term"])
            for start, end, item in matches if item["entity_type"] == "FORMULA"
        ]
        self.assertEqual(formula_spans, [
            (0, len("乌头麻黄黄芪芍药甘草汤"), "乌头麻黄黄芪芍药甘草汤"),
            (len("乌头麻黄黄芪"), len("乌头麻黄黄芪芍药甘草汤"), "芍药甘草汤"),
        ])

    def test_repeated_same_term_keeps_distinct_occurrence_ids_and_offsets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            lexicon = root / "lexicon.csv"
            output = root / "out"
            units_path = root / "knowledge_units.jsonl.gz"
            source_text = "头痛缓解后，头痛再次出现。"
            source = {
                "document": "notes/repeated.sy", "source_sha256": "b" * 64,
                "tree_position": "0.4", "block_id": "repeat-block",
                "content_type": "PARAGRAPH", "section_path": "",
            }
            with gzip.open(content, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "document", "source_sha256", "tree_position", "block_id",
                    "content_type", "section_path", "content_text",
                ])
                writer.writeheader()
                writer.writerow({**source, "content_text": source_text})
            with lexicon.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["entity_type", "term"])
                writer.writeheader()
                writer.writerow({"entity_type": "SYMPTOM", "term": "头痛"})

            result = module.extract(content, lexicon, output)
            self.assertEqual(result["mentions"], 2)
            path = output / "entity_mention_candidates.csv.gz"
            unit = {
                "unit_id": module.unit_id(source),
                "source": {"document": source["document"], "sha256": source["source_sha256"],
                           "tree_position": source["tree_position"], "block_id": source["block_id"]},
                "content": {"source_text": source_text},
            }
            with gzip.open(units_path, "wt", encoding="utf-8") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            self.assertEqual(module.validate(path, units_path), 2)
            with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(
                [(row["matched_text"], int(row["character_start"]), int(row["character_end"]))
                 for row in rows],
                [("头痛", 0, 2), ("头痛", 7, 9)],
            )
            self.assertEqual(len({row["mention_id"] for row in rows}), 2)

    def test_validator_rejects_mention_id_not_derived_from_occurrence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            lexicon = root / "lexicon.csv"
            output = root / "out"
            fields = ["document", "source_sha256", "tree_position", "block_id",
                      "content_type", "section_path", "content_text"]
            with gzip.open(content, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "document": "notes/a.sy", "source_sha256": "a" * 64,
                    "tree_position": "0.1", "block_id": "b1",
                    "content_type": "PARAGRAPH", "section_path": "",
                    "content_text": "头痛与头痛",
                })
            with lexicon.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["entity_type", "term"])
                writer.writeheader()
                writer.writerow({"entity_type": "SYMPTOM", "term": "头痛"})
            module.extract(content, lexicon, output)
            path = output / "entity_mention_candidates.csv.gz"
            with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
                fieldnames = rows[0].keys()
            rows[0]["mention_id"] = "fabricated-id"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "mention ID does not match occurrence identity"):
                module.validate(path)

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
