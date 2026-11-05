import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("validate_review_evidence_references.py")
SPEC = importlib.util.spec_from_file_location("validate_review_evidence_references", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)


class EvidenceReferenceTests(unittest.TestCase):
    def write(self, path, fields, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ledger = self.root / "evidence.csv"
        self.decisions = self.root / "decisions.csv"
        self.sources = self.root / "sources.csv"
        self.assets = self.root / "assets.csv"
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind"], [
            {"evidence_id": "EV-001", "subject_type": "topic_decision", "subject_key": "book/a.sy", "evidence_kind": "original_sy"},
            {"evidence_id": "EV-002", "subject_type": "source_candidate", "subject_key": "assets/book.pdf", "evidence_kind": "copyright_page"},
            {"evidence_id": "EV-003", "subject_type": "asset_reference", "subject_key": "assets/img-1.png", "evidence_kind": "asset_content"},
            {"evidence_id": "EV-004", "subject_type": "document", "subject_key": "book/a.sy", "evidence_kind": "original_sy"},
            {"evidence_id": "EV-005", "subject_type": "source_candidate", "subject_key": "book/a.sy", "evidence_kind": "asset_content"},
        ])
        self.write(self.decisions, [
            "document", "title_review_status", "source_status", "source_version_status",
            "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
        ], [{
            "document": "book/a.sy", "topic_review_status": "CONFIRMED",
            "evidence_reference": "EV-001",
        }])
        self.write(self.sources, ["path", "verification_status", "evidence_reference"], [{
            "path": "assets/book.pdf", "verification_status": "VERIFIED", "evidence_reference": "EV-002",
        }])
        self.write(self.assets, ["reference", "manual_status", "content_evidence_reference"], [{
            "reference": "assets/img-1.png", "manual_status": "CONFIRMED_MATCH",
            "content_evidence_reference": "EV-003",
        }])

    def tearDown(self):
        self.temp.cleanup()

    def test_validates_decision_source_and_asset_references(self):
        result = validator.validate_references(self.ledger, self.decisions, self.sources, self.assets)
        self.assertEqual(result["evidence_records"], 5)
        self.assertEqual(result["decision_conclusions"], 1)
        self.assertEqual(result["source_conclusions"], 1)
        self.assertEqual(result["asset_conclusions"], 1)
        self.assertEqual(result["validated_evidence_references"], 3)

    def test_rejects_missing_evidence_id(self):
        with self.decisions.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "document", "title_review_status", "source_status", "source_version_status",
                "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
            ])
            writer.writeheader()
            writer.writerow({"document": "book/a.sy", "topic_review_status": "CONFIRMED",
                             "evidence_reference": "EV-MISSING"})
        with self.assertRaisesRegex(ValueError, "不存在的证据 ID"):
            validator.validate_references(self.ledger, self.decisions)

    def test_rejects_subject_and_domain_mismatch(self):
        with self.decisions.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "document", "title_review_status", "source_status", "source_version_status",
                "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
            ])
            writer.writeheader()
            writer.writerow({"document": "book/a.sy", "topic_review_status": "CONFIRMED",
                             "evidence_reference": "EV-002"})
        with self.assertRaisesRegex(ValueError, "对象不匹配"):
            validator.validate_references(self.ledger, self.decisions)
        with self.decisions.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "document", "title_review_status", "source_status", "source_version_status",
                "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
            ])
            writer.writeheader()
            writer.writerow({"document": "book/a.sy", "topic_review_status": "CONFIRMED",
                             "evidence_reference": "EV-005"})
        with self.assertRaisesRegex(ValueError, "类型不匹配"):
            validator.validate_references(self.ledger, self.decisions)

    def test_rejects_incompatible_evidence_kind(self):
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind"], [
            {"evidence_id": "EV-001", "subject_type": "topic_decision",
             "subject_key": "book/a.sy", "evidence_kind": "asset_content"},
        ])
        with self.assertRaisesRegex(ValueError, "证据类型不匹配"):
            validator.validate_references(self.ledger, self.decisions)

    def test_rejects_asset_reference_without_content_evidence(self):
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind"], [
            {"evidence_id": "EV-003", "subject_type": "asset_reference",
             "subject_key": "assets/img-1.png", "evidence_kind": "original_sy"},
        ])
        with self.assertRaisesRegex(ValueError, "证据类型不匹配"):
            validator.validate_references(self.ledger, assets_path=self.assets)

    def test_ignores_unverified_source_and_unreviewed_asset(self):
        self.write(self.sources, ["path", "verification_status", "evidence_reference"], [{
            "path": "assets/book.pdf", "verification_status": "UNVERIFIED",
            "evidence_reference": "old filename-only note",
        }])
        self.write(self.assets, ["reference", "manual_status", "content_evidence_reference"], [{
            "reference": "assets/img-1.png", "manual_status": "NEEDS_INSPECTION",
            "content_evidence_reference": "",
        }])
        result = validator.validate_references(self.ledger, sources_path=self.sources, assets_path=self.assets)
        self.assertEqual(result["source_conclusions"], 0)
        self.assertEqual(result["asset_conclusions"], 0)

    def test_rejects_empty_or_duplicate_ids_in_active_conclusion(self):
        with self.decisions.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "document", "title_review_status", "source_status", "source_version_status",
                "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
            ])
            writer.writeheader()
            writer.writerow({"document": "book/a.sy", "topic_review_status": "CONFIRMED",
                             "evidence_reference": "EV-001;EV-001"})
        with self.assertRaisesRegex(ValueError, "重复"):
            validator.validate_references(self.ledger, self.decisions)


if __name__ == "__main__":
    unittest.main()
