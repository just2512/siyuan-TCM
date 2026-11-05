import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_asset_review_queue.py")
SPEC = importlib.util.spec_from_file_location("build_asset_review_queue", MODULE_PATH)
queue = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(queue)


FIELDS = [
    "reference", "candidate_class", "occurrence_count", "candidate_status",
    "candidate_count", "candidate_paths", "document_paths", "titles",
    "candidate_basis", "manual_status", "manual_note", "content_evidence_reference",
]


class AssetReviewQueueTests(unittest.TestCase):
    def write_candidates(self, path, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, reference, status, count, paths, occurrences="1"):
        return {
            "reference": reference, "candidate_class": "NO_EXTENSION_REFERENCE",
            "occurrence_count": occurrences, "candidate_status": status,
            "candidate_count": str(count), "candidate_paths": paths,
            "document_paths": "notebook/doc.sy", "titles": "测试笔记",
            "candidate_basis": "ASSETS_DIRECTORY_FILENAME_ONLY_NOT_CONTENT_VERIFIED",
            "manual_status": "NEEDS_INSPECTION", "manual_note": "", "content_evidence_reference": "",
        }

    def test_builds_stable_batches_and_summary_without_promoting_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "candidates.csv"
            self.write_candidates(source, [
                self.row("assets/z", "NO_CANDIDATE", 0, ""),
                self.row("assets/a", "ONE_CANDIDATE", 1, "assets/a-1.jpg"),
                self.row("assets/m", "MULTIPLE_CANDIDATES", 2, "assets/m-1.jpg;assets/m-2.jpg", "2"),
            ])
            rows = queue.read_candidates(source)
            result = queue.build_queue(rows, root / "out", batch_size=2)
            self.assertEqual(result, {
                "references": 3, "occurrences": 4, "candidate_paths": 3,
                "batches": 2, "one_candidate": 1, "multiple_candidates": 1,
                "no_candidate": 1,
            })
            with (root / "out" / "asset_review_queue.csv").open(encoding="utf-8-sig", newline="") as stream:
                output = list(csv.DictReader(stream))
            self.assertEqual([row["reference"] for row in output], ["assets/a", "assets/m", "assets/z"])
            self.assertEqual(output[0]["recommended_action"], "INSPECT_SINGLE_CANDIDATE_CONTENT")
            self.assertEqual(output[1]["batch_id"], "ASSET-001")
            self.assertEqual(output[2]["batch_id"], "ASSET-002")
            self.assertTrue(all(row["manual_status"] == "NEEDS_INSPECTION" for row in output))
            self.assertIn("候选文件路径总数", (root / "out" / "asset_review_queue.md").read_text(encoding="utf-8"))

    def test_rejects_duplicate_references_and_inconsistent_candidate_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "candidates.csv"
            self.write_candidates(source, [
                self.row("assets/a", "ONE_CANDIDATE", 1, "assets/a.jpg"),
                self.row("assets/a", "ONE_CANDIDATE", 1, "assets/a.jpg"),
            ])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)
            self.write_candidates(source, [
                self.row("assets/a", "ONE_CANDIDATE", 2, "assets/a.jpg"),
            ])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)

    def test_rejects_status_count_mismatch_and_invalid_manual_state(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "candidates.csv"
            self.write_candidates(source, [
                self.row("assets/a", "NO_CANDIDATE", 1, "assets/a.jpg"),
            ])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)
            self.write_candidates(source, [
                {**self.row("assets/a", "NO_CANDIDATE", 0, ""), "manual_status": "AUTO_FOUND"},
            ])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)

    def test_rejects_content_conclusion_without_evidence_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "candidates.csv"
            self.write_candidates(source, [{**self.row("assets/a", "ONE_CANDIDATE", 1, "assets/a.jpg"), "manual_status": "CONFIRMED_MATCH"}])
            with self.assertRaisesRegex(ValueError, "缺少 content_evidence_reference"):
                queue.read_candidates(source)
            self.write_candidates(source, [{**self.row("assets/a", "ONE_CANDIDATE", 1, "assets/a.jpg"),
                "manual_status": "CONFIRMED_MATCH", "content_evidence_reference": "catalog/local-review/asset-content-review.csv#A-001"}])
            self.assertEqual(queue.read_candidates(source)[0]["manual_status"], "CONFIRMED_MATCH")

    def test_rejects_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            queue.build_queue([], Path("unused"), 0)


if __name__ == "__main__":
    unittest.main()
