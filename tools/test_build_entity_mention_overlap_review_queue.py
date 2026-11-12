from __future__ import annotations

import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from build_entity_mention_overlap_review_queue import build_review_queue


MENTION_FIELDS = [
    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
    "character_end", "document", "source_sha256", "tree_position", "block_id",
]
CONTENT_FIELDS = ["document", "source_sha256", "tree_position", "block_id", "content_text"]


class EntityMentionOverlapReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mentions = self.root / "mentions.csv.gz"
        self.content = self.root / "content.csv.gz"
        self.relations = self.root / "relations.csv"
        self.output = self.root / "review.csv"
        self.report = self.root / "review.json"
        self.locator = ("doc.sy", "source-hash", "0.1", "block")
        self.unit = hashlib.sha256("\0".join(self.locator).encode()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def write_csv(self, path: Path, fields: list[str], rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def write_gzip(self, path: Path, fields: list[str], rows: list[dict]) -> None:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def mention(self, mention_id: str, kind: str, text: str, start: int) -> dict:
        return {
            "mention_id": mention_id, "unit_id": self.unit, "entity_type": kind,
            "matched_text": text, "character_start": str(start),
            "character_end": str(start + len(text)), "document": self.locator[0],
            "source_sha256": self.locator[1], "tree_position": self.locator[2],
            "block_id": self.locator[3],
        }

    def prepare(self, source: str, mentions: list[dict], relations: list[dict] | None = None) -> None:
        self.write_gzip(self.content, CONTENT_FIELDS, [{
            "document": self.locator[0], "source_sha256": self.locator[1],
            "tree_position": self.locator[2], "block_id": self.locator[3],
            "content_text": source,
        }])
        self.write_gzip(self.mentions, MENTION_FIELDS, mentions)
        self.write_csv(self.relations, ["relation_id", "subject_mention_id", "object_mention_id"],
            relations or [])

    def test_exports_formula_herb_overlap_with_exact_source_and_relation_link(self):
        source = "桂枝汤"
        formula = self.mention("formula-1", "FORMULA", "桂枝汤", 0)
        herb = self.mention("herb-1", "HERB", "桂枝", 0)
        self.prepare(source, [formula, herb], [{
            "relation_id": "relation-1", "subject_mention_id": "formula-1",
            "object_mention_id": "herb-1",
        }])
        overlap_audit = self.root / "overlap-audit.json"
        overlap_audit.write_text(json.dumps({
            "overlap_pair_counts_by_entity_type": {
                "FORMULA|HERB": {"nested_formula_herb_entity": 1}
            }
        }), encoding="utf-8")
        result = build_review_queue(
            self.mentions, self.content, self.output, self.report, self.relations, overlap_audit
        )
        with self.output.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(result["cross_type_overlap_pairs"], 1)
        self.assertEqual(rows[0]["overlap_kind"], "nested_formula_herb_entity")
        self.assertEqual(rows[0]["relation_id"], "relation-1")
        self.assertEqual(rows[0]["context_text"], source)
        self.assertEqual(rows[0]["review_status"], "UNREVIEWED")

    def test_same_type_overlaps_are_not_placed_in_cross_type_queue(self):
        source = "肺"
        mentions = [
            self.mention("organ-1", "ORGAN", "肺", 0),
            self.mention("organ-2", "ORGAN", "肺", 0),
        ]
        self.prepare(source, mentions)
        result = build_review_queue(self.mentions, self.content, self.output, self.report)
        with self.output.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows, [])
        self.assertEqual(result["cross_type_overlap_pairs"], 0)

    def test_rejects_mention_offset_that_does_not_match_source(self):
        source = "桂枝汤"
        formula = self.mention("formula-1", "FORMULA", "桂枝汤", 0)
        herb = self.mention("herb-1", "HERB", "桂枝", 1)
        self.prepare(source, [formula, herb])
        with self.assertRaisesRegex(ValueError, "source span mismatch"):
            build_review_queue(self.mentions, self.content, self.output, self.report)

    def test_rejects_duplicate_source_locator(self):
        source = "桂枝汤"
        formula = self.mention("formula-1", "FORMULA", "桂枝汤", 0)
        self.write_gzip(self.content, CONTENT_FIELDS, [
            {"document": self.locator[0], "source_sha256": self.locator[1],
             "tree_position": self.locator[2], "block_id": self.locator[3], "content_text": source},
            {"document": self.locator[0], "source_sha256": self.locator[1],
             "tree_position": self.locator[2], "block_id": self.locator[3], "content_text": source},
        ])
        self.write_gzip(self.mentions, MENTION_FIELDS, [formula])
        self.write_csv(self.relations, ["relation_id", "subject_mention_id", "object_mention_id"], [])
        with self.assertRaisesRegex(ValueError, "duplicate source locator"):
            build_review_queue(self.mentions, self.content, self.output, self.report)

    def test_rejects_queue_count_that_does_not_reconcile_with_overlap_audit(self):
        source = "桂枝汤"
        formula = self.mention("formula-1", "FORMULA", "桂枝汤", 0)
        herb = self.mention("herb-1", "HERB", "桂枝", 0)
        self.prepare(source, [formula, herb])
        overlap_audit = self.root / "overlap-audit.json"
        overlap_audit.write_text(json.dumps({
            "overlap_pair_counts_by_entity_type": {
                "FORMULA|HERB": {"nested_formula_herb_entity": 2}
            }
        }), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not reconcile"):
            build_review_queue(
                self.mentions, self.content, self.output, self.report, None, overlap_audit
            )

    def test_rejects_relation_endpoint_not_present_in_mention_input(self):
        source = "桂枝汤"
        formula = self.mention("formula-1", "FORMULA", "桂枝汤", 0)
        self.prepare(source, [formula], [{
            "relation_id": "relation-1", "subject_mention_id": "formula-1",
            "object_mention_id": "missing-herb",
        }])
        with self.assertRaisesRegex(ValueError, "relation endpoint not found"):
            build_review_queue(self.mentions, self.content, self.output, self.report, self.relations)


if __name__ == "__main__":
    unittest.main()
