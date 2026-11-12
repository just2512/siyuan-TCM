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
            "context_reference": "",
            "content_basis": "",
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

    def test_asset_content_requires_direct_inspection_and_note_context(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.csv"
            base = {
                "subject_type": "asset_reference",
                "subject_key": "assets/image.png",
                "evidence_kind": "asset_content",
                "source_reference": "assets/image.png",
                "locator": "图像第 1 页中央区域",
                "observation": "图中可见的药材标签与原始笔记该附件引用上下文逐项对应",
                "context_reference": "folder/note.sy#block-123",
                "content_basis": "VISUAL_CONTENT_AND_NOTE_CONTEXT",
            }
            self.write_ledger(path, [self.row(**base)])
            result = validator.validate_ledger(path)
            self.assertEqual(result["asset_content"], 1)

            for updates, message in [
                ({"context_reference": ""}, "上下文/块定位"),
                ({"context_reference": "folder/note.sy"}, "上下文/块定位"),
                ({"context_reference": "folder/note.sy#"}, "上下文/块定位"),
                ({"content_basis": ""}, "有效 content_basis"),
                ({"content_basis": "FILENAME_AND_HASH_ONLY"}, "content_basis 无效"),
                ({"inspection_method": "PROGRAMMATIC_STRUCTURE", "reviewer": "automated-test"}, "必须来自 HUMAN_DIRECT"),
                ({"context_reference": "/home/user/note.sy"}, "绝对路径或路径穿越"),
                ({"source_reference": "catalog/image.png"}, "assets/ 下的安全相对附件路径"),
                ({"source_reference": "assets/../private.png"}, "assets/ 下的安全相对附件路径"),
                ({"subject_key": "catalog/image.png"}, "assets/ 下的安全相对附件路径"),
            ]:
                with self.subTest(updates=updates):
                    candidate = dict(base)
                    candidate.update(updates)
                    self.write_ledger(path, [self.row(**candidate)])
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

    def test_human_direct_records_must_not_claim_an_automated_reviewer(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ledger.csv"
            for method in ("HUMAN_DIRECT", "SECONDARY_REFERENCE"):
                with self.subTest(method=method):
                    self.write_ledger(path, [self.row(
                        inspection_method=method,
                        reviewer="automated-structure-scan",
                    )])
                    with self.assertRaisesRegex(ValueError, "不得使用自动化核验人标识"):
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
