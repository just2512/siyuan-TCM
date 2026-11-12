from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from split_overlap_review_batches import split_review_batches


FIELDS = ["pair_id", "candidate_type_pair", "overlap_kind", "review_status", "review_decision"]


class SplitOverlapReviewBatchesTests(unittest.TestCase):
    def write_queue(self, path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_partitions_all_rows_without_loss_or_duplication_and_respects_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "queue.csv", root / "batches"
            rows = [
                {"pair_id": f"p{i:03d}", "candidate_type_pair": "HERB|SYMPTOM" if i % 3 else "FORMULA|HERB",
                 "overlap_kind": "nested" if i % 2 else "partial", "review_status": "UNREVIEWED",
                 "review_decision": ""}
                for i in range(23)
            ]
            self.write_queue(source, rows)
            manifest = split_review_batches(source, output, 5)
            self.assertEqual(manifest["input_rows"], len(rows))
            self.assertEqual(manifest["review_decisions_assigned"], 0)
            self.assertEqual(manifest["candidate_mutations"], 0)
            observed = []
            for item in manifest["batches"]:
                self.assertLessEqual(item["rows"], 5)
                with (output / item["file"]).open(encoding="utf-8-sig", newline="") as stream:
                    observed.extend(row["pair_id"] for row in csv.DictReader(stream))
            self.assertCountEqual(observed, [row["pair_id"] for row in rows])
            self.assertEqual(len(observed), len(set(observed)))

    def test_output_is_deterministic_for_same_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "queue.csv"
            rows = [
                {"pair_id": f"p{i}", "candidate_type_pair": "A|B", "overlap_kind": "nested",
                 "review_status": "UNREVIEWED", "review_decision": ""}
                for i in range(7)
            ]
            self.write_queue(source, rows)
            first = split_review_batches(source, root / "one", 3)
            second = split_review_batches(source, root / "two", 3)
            self.assertEqual(first, second)
            for item in first["batches"]:
                self.assertEqual(
                    (root / "one" / item["file"]).read_bytes(),
                    (root / "two" / item["file"]).read_bytes(),
                )

    def test_rejects_duplicate_pair_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "queue.csv"
            row = {"pair_id": "duplicate", "candidate_type_pair": "A|B",
                   "overlap_kind": "nested", "review_status": "UNREVIEWED", "review_decision": ""}
            self.write_queue(source, [row, row])
            with self.assertRaisesRegex(ValueError, "duplicate pair_id"):
                split_review_batches(source, root / "out", 10)

    def test_refuses_rows_already_marked_reviewed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "queue.csv"
            row = {"pair_id": "p1", "candidate_type_pair": "A|B",
                   "overlap_kind": "nested", "review_status": "REVIEWED", "review_decision": "KEEP_BOTH"}
            self.write_queue(source, [row])
            with self.assertRaisesRegex(ValueError, "already reviewed"):
                split_review_batches(source, root / "out", 10)


if __name__ == "__main__":
    unittest.main()
