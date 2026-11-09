import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from audit_entity_mention_overlaps import audit


class EntityMentionOverlapAuditTests(unittest.TestCase):
    def test_distinguishes_nested_formula_herb_and_same_type_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            rows = [
                ("f1", "u", "FORMULA", "桂枝汤", 0, 3),
                ("h1", "u", "HERB", "桂枝", 0, 2),
                ("f2", "u", "FORMULA", "芍药甘草汤", 10, 15),
                ("f3", "u", "FORMULA", "甘草汤", 12, 15),
                ("h2", "u", "HERB", "桂枝", 20, 22),
                ("h3", "u", "HERB", "桂枝", 30, 32),
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(fields)
                for mid, unit, kind, term, start, end in rows:
                    writer.writerow([mid, unit, kind, term, start, end,
                                     "a.sy", "a" * 64, "0.1", "b"])
            result = audit(source, output)
            self.assertEqual(result["total_mentions"], 6)
            self.assertEqual(result["overlap_pair_counts"]["nested_formula_herb_entity"], 1)
            self.assertEqual(result["overlap_pair_counts"]["nested_named_formula"], 1)
            self.assertEqual(result["repeated_term_groups"], 1)
            self.assertEqual(result["repeated_term_occurrences_in_groups"], 3)
            report = output.read_text(encoding="utf-8")
            self.assertIn('"start": 0', report)
            self.assertIn('"start": 30', report)

    def test_reports_same_type_exact_duplicate_window_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid in ("h1", "h2"):
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u", "entity_type": "HERB",
                        "matched_text": "桂枝", "character_start": 0, "character_end": 2,
                        "document": "a.sy", "source_sha256": "a" * 64,
                        "tree_position": "0.1", "block_id": "b",
                    })
            result = audit(source, output)
            self.assertEqual(
                result["overlap_pair_counts"]["same_type_exact_duplicate_window"], 1
            )


if __name__ == "__main__":
    unittest.main()
