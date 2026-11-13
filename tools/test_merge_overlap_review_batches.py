from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from merge_overlap_review_batches import merge_review_batches
from split_overlap_review_batches import split_review_batches


FIELDS = [
    "pair_id", "candidate_type_pair", "overlap_kind", "document", "evidence_text",
    "review_status", "review_decision", "review_note",
]


class MergeOverlapReviewBatchesTests(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def read_csv(self, path: Path) -> list[dict]:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "queue.csv"
        self.batch_dir = self.root / "batches"
        self.output = self.root / "merged.csv"
        self.rows = [
            {
                "pair_id": f"pair-{index}",
                "candidate_type_pair": "HERB|SYMPTOM" if index % 2 else "FORMULA|HERB",
                "overlap_kind": "nested" if index % 3 else "partial",
                "document": f"doc-{index}.sy",
                "evidence_text": f"source evidence {index}",
                "review_status": "UNREVIEWED",
                "review_decision": "",
                "review_note": "",
            }
            for index in range(7)
        ]
        self.write_csv(self.source, self.rows)
        split_review_batches(self.source, self.batch_dir, 3)

    def tearDown(self):
        self.temp.cleanup()

    def test_merges_review_decisions_without_changing_candidate_evidence(self):
        manifest = self.batch_dir / "overlap-review-batches.json"
        import json
        data = json.loads(manifest.read_text(encoding="utf-8"))
        first_batch = self.batch_dir / data["batches"][0]["file"]
        batch_rows = self.read_csv(first_batch)
        batch_rows[0]["review_status"] = "REVIEWED"
        batch_rows[0]["review_decision"] = "KEEP_BOTH"
        batch_rows[0]["review_note"] = "Both spans have distinct meaning in context."
        self.write_csv(first_batch, batch_rows)

        result = merge_review_batches(self.source, self.batch_dir, self.output)
        merged = {row["pair_id"]: row for row in self.read_csv(self.output)}
        reviewed = next(row for row in merged.values() if row["review_status"] == "REVIEWED")

        self.assertEqual(result["input_rows"], len(self.rows))
        self.assertEqual(result["review_status_counts"], {"REVIEWED": 1, "UNREVIEWED": 6})
        self.assertEqual(result["review_decision_counts"], {"KEEP_BOTH": 1})
        self.assertEqual(reviewed["review_decision"], "KEEP_BOTH")
        self.assertEqual(reviewed["review_note"], "Both spans have distinct meaning in context.")
        for original in self.rows:
            current = merged[original["pair_id"]]
            for field in FIELDS:
                if field not in {"review_status", "review_decision", "review_note"}:
                    self.assertEqual(current[field], original[field])
        self.assertTrue(self.output.with_name(self.output.name + ".report.json").is_file())

    def test_rejects_stale_source_queue(self):
        changed = [dict(row) for row in self.rows]
        changed[0]["evidence_text"] = "changed after batch export"
        self.write_csv(self.source, changed)
        with self.assertRaisesRegex(ValueError, "source SHA-256"):
            merge_review_batches(self.source, self.batch_dir, self.output)

    def test_rejects_modified_candidate_or_evidence_fields(self):
        import json
        manifest = json.loads(
            (self.batch_dir / "overlap-review-batches.json").read_text(encoding="utf-8")
        )
        first_batch = self.batch_dir / manifest["batches"][0]["file"]
        rows = self.read_csv(first_batch)
        rows[0]["evidence_text"] = "tampered evidence"
        self.write_csv(first_batch, rows)
        with self.assertRaisesRegex(ValueError, "immutable field changed: evidence_text"):
            merge_review_batches(self.source, self.batch_dir, self.output)

    def test_rejects_reviewed_row_without_decision(self):
        import json
        manifest = json.loads(
            (self.batch_dir / "overlap-review-batches.json").read_text(encoding="utf-8")
        )
        first_batch = self.batch_dir / manifest["batches"][0]["file"]
        rows = self.read_csv(first_batch)
        rows[0]["review_status"] = "REVIEWED"
        rows[0]["review_decision"] = ""
        self.write_csv(first_batch, rows)
        with self.assertRaisesRegex(ValueError, "reviewed row has no review_decision"):
            merge_review_batches(self.source, self.batch_dir, self.output)

    def test_rejects_unknown_review_status(self):
        import json
        manifest = json.loads(
            (self.batch_dir / "overlap-review-batches.json").read_text(encoding="utf-8")
        )
        first_batch = self.batch_dir / manifest["batches"][0]["file"]
        rows = self.read_csv(first_batch)
        rows[0]["review_status"] = "APPROVED"
        self.write_csv(first_batch, rows)
        with self.assertRaisesRegex(ValueError, "unsupported review_status"):
            merge_review_batches(self.source, self.batch_dir, self.output)


if __name__ == "__main__":
    unittest.main()
