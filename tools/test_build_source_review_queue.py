import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_source_review_queue.py")
SPEC = importlib.util.spec_from_file_location("build_source_review_queue", MODULE_PATH)
queue = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(queue)


FIELDS = [
    "candidate_category", "path", "candidate_note",
    "verification_status", "evidence_reference",
]


class SourceReviewQueueTests(unittest.TestCase):
    def write_rows(self, path, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, category, path, status="UNVERIFIED", evidence=""):
        return {
            "candidate_category": category, "path": path,
            "candidate_note": "候选，不代表已核验",
            "verification_status": status, "evidence_reference": evidence,
        }

    def test_builds_deterministic_evidence_queue_without_promoting_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.csv"
            self.write_rows(source, [
                self.row("nihongxia_lecture", "lectures/a"),
                self.row("asset_file", "assets/book.pdf"),
                self.row("huangdi_neijing_chapter", "chapters/a"),
            ])
            rows = queue.read_candidates(source)
            result = queue.build_queue(rows, root / "out", batch_size=2)
            self.assertEqual(result, {
                "candidates": 3, "batches": 2, "unverified": 3,
                "verified": 0, "conflict": 0, "unresolved": 0,
            })
            with (root / "out" / "source_review_queue.csv").open(encoding="utf-8-sig", newline="") as stream:
                output = list(csv.DictReader(stream))
            self.assertEqual([row["candidate_category"] for row in output], [
                "asset_file", "huangdi_neijing_chapter", "nihongxia_lecture",
            ])
            self.assertEqual(output[0]["verification_status"], "UNVERIFIED")
            self.assertIn("版权页", output[0]["required_evidence"])
            self.assertEqual(output[2]["batch_id"], "SOURCE-002")
            report = (root / "out" / "source_review_queue.md").read_text(encoding="utf-8")
            self.assertIn("候选类别和文件名不是书目证据", report)

    def test_rejects_duplicate_paths_unknown_categories_and_invalid_states(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.csv"
            self.write_rows(source, [
                self.row("asset_file", "assets/a.pdf"),
                self.row("asset_file", "assets/a.pdf"),
            ])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)
            self.write_rows(source, [self.row("unknown", "x")])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)
            self.write_rows(source, [self.row("asset_file", "assets/a.pdf", "MAYBE")])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)

    def test_requires_evidence_for_non_unverified_conclusions(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.csv"
            self.write_rows(source, [self.row("asset_file", "assets/a.pdf", "VERIFIED")])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)
            self.write_rows(source, [self.row("asset_file", "assets/a.pdf", "VERIFIED", "版权页 p.2")])
            self.assertEqual(queue.read_candidates(source)[0]["verification_status"], "VERIFIED")

    def test_rejects_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            queue.build_queue([], Path("unused"), 0)


if __name__ == "__main__":
    unittest.main()
