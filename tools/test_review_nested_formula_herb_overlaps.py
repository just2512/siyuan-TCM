from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from review_nested_formula_herb_overlaps import review_nested_formula_herb_overlaps


FIELDS = [
    "pair_id", "unit_id", "document", "source_sha256", "tree_position", "block_id",
    "overlap_kind", "entity_type_pair",
    "left_mention_id", "left_type", "left_text", "left_start", "left_end",
    "right_mention_id", "right_type", "right_text", "right_start", "right_end",
    "relation_id", "context_start", "context_end", "context_text",
    "review_status", "review_decision", "review_note",
]


class NestedFormulaHerbOverlapReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.csv"
        self.output = self.root / "reviewed.csv"
        self.report = self.root / "report.json"

    def tearDown(self):
        self.temp.cleanup()

    def row(self, *, left_type="FORMULA", right_type="HERB",
             overlap_kind="nested_formula_herb_entity", context="桂枝汤",
             left_text="桂枝汤", right_text="桂枝", left_start=0,
             left_end=3, right_start=0, right_end=2, pair_id="pair-1"):
        return {
            "pair_id": pair_id, "unit_id": "unit-1", "document": "doc.sy",
            "source_sha256": "source-sha", "tree_position": "0.1", "block_id": "block-1",
            "overlap_kind": overlap_kind, "entity_type_pair": "FORMULA|HERB",
            "left_mention_id": "left-1", "left_type": left_type, "left_text": left_text,
            "left_start": str(left_start), "left_end": str(left_end),
            "right_mention_id": "right-1", "right_type": right_type, "right_text": right_text,
            "right_start": str(right_start), "right_end": str(right_end),
            "relation_id": "", "context_start": "0", "context_end": str(len(context)),
            "context_text": context, "review_status": "UNREVIEWED",
            "review_decision": "", "review_note": "",
        }

    def write(self, rows):
        with self.source.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def read(self):
        with self.output.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_keeps_both_for_exact_nested_formula_name_herb_mention(self):
        self.write([self.row()])
        self.report.write_text(json.dumps({"cross_type_overlap_pairs": 1}), encoding="utf-8")
        result = review_nested_formula_herb_overlaps(self.source, self.output, self.report)
        row = self.read()[0]
        self.assertEqual((row["review_status"], row["review_decision"]), ("REVIEWED", "KEEP_BOTH"))
        self.assertIn("does not create", row["review_note"])
        self.assertEqual(result["reviewed_by_rule"], 1)
        self.assertEqual(result["relationship_inferences"], 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["review_status"], "REVIEWED")

    def test_handles_formula_and_herb_reversed_in_left_right_columns(self):
        self.write([self.row(
            left_type="HERB", right_type="FORMULA",
            left_text="桂枝", right_text="桂枝汤",
            left_start=0, left_end=2, right_start=0, right_end=3,
        )])
        result = review_nested_formula_herb_overlaps(self.source, self.output)
        self.assertEqual(result["reviewed_by_rule"], 1)
        self.assertEqual(self.read()[0]["review_decision"], "KEEP_BOTH")

    def test_does_not_decide_partial_overlap_or_other_entity_pairs(self):
        partial = self.row(
            overlap_kind="partial_overlap", left_text="桂枝汤", right_text="枝汤",
            left_start=0, left_end=3, right_start=1, right_end=3,
        )
        other = self.row(
            overlap_kind="nested_cross_type_entity", pair_id="pair-2",
        )
        self.write([partial, other])
        result = review_nested_formula_herb_overlaps(self.source, self.output)
        self.assertEqual(result["reviewed_by_rule"], 0)
        self.assertEqual(result["remaining_unreviewed_rows"], 2)
        self.assertTrue(all(r["review_status"] == "UNREVIEWED" for r in self.read()))

    def test_does_not_infer_relationship_from_name_containment(self):
        row = self.row()
        row["relation_id"] = ""
        self.write([row])
        review_nested_formula_herb_overlaps(self.source, self.output)
        self.assertEqual(self.read()[0]["relation_id"], "")

    def test_rejects_mismatched_evidence_offsets(self):
        self.write([self.row(right_text="桂枝", right_start=1, right_end=3)])
        with self.assertRaisesRegex(ValueError, "herb text does not match"):
            review_nested_formula_herb_overlaps(self.source, self.output)

    def test_rejects_non_nested_formula_herb_spans(self):
        self.write([self.row(
            left_text="枝汤", right_text="桂枝",
            left_start=1, left_end=3, right_start=0, right_end=2,
        )])
        with self.assertRaisesRegex(ValueError, "not strictly nested"):
            review_nested_formula_herb_overlaps(self.source, self.output)

    def test_preserves_existing_review_decisions(self):
        row = self.row()
        row["review_status"] = "REVIEWED"
        row["review_decision"] = "DROP_LEFT"
        row["review_note"] = "existing explicit decision"
        self.write([row])
        result = review_nested_formula_herb_overlaps(self.source, self.output)
        self.assertEqual(result["reviewed_by_rule"], 0)
        self.assertEqual(self.read()[0]["review_decision"], "DROP_LEFT")

    def test_requires_distinct_input_and_output_paths(self):
        self.write([self.row()])
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            review_nested_formula_herb_overlaps(self.source, self.source)


if __name__ == "__main__":
    unittest.main()
