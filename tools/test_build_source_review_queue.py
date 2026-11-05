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
    "source_identity_status", "source_identity_evidence_reference",
    "source_version_status", "source_version_evidence_reference",
    "collation_status", "collation_evidence_reference",
]


class SourceReviewQueueTests(unittest.TestCase):
    def write_rows(self, path, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, category, path, **updates):
        result = {
            "candidate_category": category, "path": path,
            "candidate_note": "候选，不代表已核验",
            "source_identity_status": "UNVERIFIED", "source_identity_evidence_reference": "",
            "source_version_status": "UNVERIFIED", "source_version_evidence_reference": "",
            "collation_status": "UNVERIFIED", "collation_evidence_reference": "",
        }
        result.update(updates)
        return result

    def test_builds_deterministic_independent_evidence_queues(self):
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
            self.assertEqual(result["candidates"], 3)
            self.assertEqual(result["source_identity_status_unverified"], 3)
            self.assertEqual(result["source_version_status_unverified"], 3)
            self.assertEqual(result["collation_status_unverified"], 3)
            with (root / "out" / "source_review_queue.csv").open(encoding="utf-8-sig", newline="") as stream:
                output = list(csv.DictReader(stream))
            self.assertEqual([row["candidate_category"] for row in output], [
                "asset_file", "huangdi_neijing_chapter", "nihongxia_lecture",
            ])
            self.assertEqual(output[0]["source_identity_status"], "UNVERIFIED")
            self.assertIn("版权页", output[0]["required_evidence"])
            self.assertEqual(output[2]["batch_id"], "SOURCE-002")
            report = (root / "out" / "source_review_queue.md").read_text(encoding="utf-8")
            self.assertIn("来源身份、版本身份、文本校勘是三个独立结论", report)

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
            self.write_rows(source, [self.row("asset_file", "assets/a.pdf", source_version_status="MAYBE")])
            with self.assertRaises(ValueError):
                queue.read_candidates(source)

    def test_requires_separate_evidence_for_each_conclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.csv"
            self.write_rows(source, [self.row(
                "asset_file", "assets/a.pdf",
                source_identity_status="VERIFIED",
                source_identity_evidence_reference="EV-001",
                source_version_status="VERIFIED",
                source_version_evidence_reference="",
            )])
            with self.assertRaisesRegex(ValueError, "source_version_status 已有结论但缺少"):
                queue.read_candidates(source)

    def test_allows_identity_verified_while_version_and_collation_remain_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.csv"
            self.write_rows(source, [self.row(
                "asset_file", "assets/a.pdf",
                source_identity_status="VERIFIED",
                source_identity_evidence_reference="EV-001",
            )])
            rows = queue.read_candidates(source)
            queue.build_queue(rows, root / "out")
            with (root / "out" / "source_review_queue.csv").open(encoding="utf-8-sig", newline="") as stream:
                output = list(csv.DictReader(stream))
            self.assertEqual(output[0]["source_identity_status"], "VERIFIED")
            self.assertEqual(output[0]["source_version_status"], "UNVERIFIED")
            self.assertEqual(output[0]["collation_status"], "UNVERIFIED")

    def test_rejects_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            queue.build_queue([], Path("unused"), 0)


if __name__ == "__main__":
    unittest.main()
