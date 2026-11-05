import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("validate_review_evidence.py")
SPEC = importlib.util.spec_from_file_location("validate_review_evidence", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)


class ReviewEvidenceLedgerTests(unittest.TestCase):
    def write_ledger(self, path, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=validator.FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, **updates):
        result = {
            "evidence_id": "EV-001",
            "subject_type": "document",
            "subject_key": "folder/note.sy",
            "evidence_kind": "original_sy",
            "inspection_method": "HUMAN_DIRECT",
            "source_reference": "local-review/evidence-index.md",
            "locator": "原始 .sy；标题属性及正文第 3 段",
            "observation": "标题与正文内容一致；此处仅记录核验观察",
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-11-05",
        }
        result.update(updates)
        return result

    def test_accepts_complete_traceable_ledger_row(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.csv"
            self.write_ledger(path, [self.row()])
            result = validator.validate_ledger(path)
            self.assertEqual(result["evidence_rows"], 1)
            self.assertEqual(result["unique_subjects"], 1)
            self.assertEqual(result["original_sy"], 1)

    def test_rejects_duplicate_ids_but_allows_multiple_evidence_items_per_subject(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.csv"
            self.write_ledger(path, [self.row(), self.row(evidence_id="EV-002", locator="版权页 p.2")])
            result = validator.validate_ledger(path)
            self.assertEqual(result["evidence_rows"], 2)
            self.assertEqual(result["unique_subjects"], 1)
            self.write_ledger(path, [self.row(), self.row(subject_key="other.sy")])
            with self.assertRaisesRegex(ValueError, "证据 ID 重复"):
                validator.validate_ledger(path)

    def test_rejects_missing_fields_invalid_enums_and_date(self):
        cases = [
            ({"locator": ""}, "缺少必填字段"),
            ({"subject_type": "unknown"}, "subject_type 无效"),
            ({"evidence_kind": "filename_only"}, "evidence_kind 无效"),
            ({"inspection_method": "AI_GUESS"}, "inspection_method 无效"),
            ({"reviewed_at": "yesterday"}, "YYYY-MM-DD"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.csv"
            for updates, message in cases:
                with self.subTest(updates=updates):
                    self.write_ledger(path, [self.row(**updates)])
                    with self.assertRaisesRegex(ValueError, message):
                        validator.validate_ledger(path)

    def test_programmatic_records_must_not_claim_a_human_reviewer(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.csv"
            self.write_ledger(path, [self.row(
                inspection_method="PROGRAMMATIC_STRUCTURE", reviewer="jerry",
            )])
            with self.assertRaisesRegex(ValueError, "不得伪装为人工核验人"):
                validator.validate_ledger(path)

    def test_rejects_absolute_machine_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.csv"
            for source in [r"C:\\Users\\name\\assets\\a.png", "/home/user/assets/a.png", r"\\\\server\\share\\a.png"]:
                with self.subTest(source=source):
                    self.write_ledger(path, [self.row(source_reference=source)])
                    with self.assertRaisesRegex(ValueError, "本机绝对路径"):
                        validator.validate_ledger(path)


if __name__ == "__main__":
    unittest.main()
