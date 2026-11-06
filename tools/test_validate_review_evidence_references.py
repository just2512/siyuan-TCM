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
        if path == self.ledger:
            fields = list(fields)
            for field in ("context_reference", "content_basis", "source_reference"):
                if field not in fields:
                    fields.append(field)
            rows = [{
                **row,
                "context_reference": row.get("context_reference", ""),
                "content_basis": row.get("content_basis", ""),
                "source_reference": row.get("source_reference", ""),
            } for row in rows]
        if path == self.assets:
            if "document_paths" not in fields:
                fields = list(fields) + ["document_paths"]
            rows = [{
                **row,
                "document_paths": row.get("document_paths", "book/a.sy"),
            } for row in rows]
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
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method"], [
            {"evidence_id": "EV-001", "subject_type": "topic_decision", "subject_key": "book/a.sy", "evidence_kind": "original_sy", "inspection_method": "HUMAN_DIRECT"},
            {"evidence_id": "EV-002", "subject_type": "source_candidate", "subject_key": "assets/book.pdf", "evidence_kind": "copyright_page", "inspection_method": "HUMAN_DIRECT"},
            {"evidence_id": "EV-003", "subject_type": "asset_reference", "subject_key": "assets/img-1.png", "evidence_kind": "asset_content", "inspection_method": "HUMAN_DIRECT", "source_reference": "assets/img-1.png", "context_reference": "book/a.sy#block-1", "content_basis": "VISUAL_CONTENT_AND_NOTE_CONTEXT"},
            {"evidence_id": "EV-004", "subject_type": "document", "subject_key": "book/a.sy", "evidence_kind": "original_sy", "inspection_method": "HUMAN_DIRECT"},
            {"evidence_id": "EV-005", "subject_type": "source_candidate", "subject_key": "book/a.sy", "evidence_kind": "asset_content", "inspection_method": "HUMAN_DIRECT"},
        ])
        self.write(self.decisions, [
            "document", "title_review_status", "source_status", "source_version_status",
            "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
        ], [{
            "document": "book/a.sy", "topic_review_status": "CONFIRMED",
            "evidence_reference": "EV-001",
        }])
        self.write(self.sources, [
            "path", "source_identity_status", "source_identity_evidence_reference",
            "source_version_status", "source_version_evidence_reference",
            "collation_status", "collation_evidence_reference",
        ], [{
            "path": "assets/book.pdf",
            "source_identity_status": "VERIFIED", "source_identity_evidence_reference": "EV-002",
            "source_version_status": "UNVERIFIED", "source_version_evidence_reference": "",
            "collation_status": "UNVERIFIED", "collation_evidence_reference": "",
        }])
        self.write(self.assets, ["reference", "manual_status", "content_evidence_reference", "document_paths"], [{
            "reference": "assets/img-1.png", "manual_status": "CONFIRMED_MATCH",
            "content_evidence_reference": "EV-003", "document_paths": "book/a.sy",
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

    def test_accepts_shared_decision_evidence_ids_for_distinct_conclusion_domains(self):
        self.write(self.ledger, [
            "evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method",
        ], [
            {"evidence_id": "EV-101", "subject_type": "document", "subject_key": "book/a.sy",
             "evidence_kind": "original_sy", "inspection_method": "HUMAN_DIRECT"},
            {"evidence_id": "EV-102", "subject_type": "document", "subject_key": "book/a.sy",
             "evidence_kind": "title_page", "inspection_method": "HUMAN_DIRECT"},
        ])
        self.write(self.decisions, [
            "document", "title_review_status", "source_status", "source_version_status",
            "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
        ], [{
            "document": "book/a.sy", "title_review_status": "CONFIRMED",
            "source_status": "PARTIAL", "topic_review_status": "CONFIRMED",
            "evidence_reference": "EV-101;EV-102",
        }])
        result = validator.validate_references(self.ledger, self.decisions)
        self.assertEqual(result["decision_conclusions"], 3)
        self.assertEqual(result["validated_evidence_references"], 2)

    def test_rejects_asset_evidence_context_from_unrelated_document(self):
        self.write(self.ledger, [
            "evidence_id", "subject_type", "subject_key", "evidence_kind",
            "inspection_method", "source_reference", "context_reference", "content_basis",
        ], [{
            "evidence_id": "EV-003", "subject_type": "asset_reference",
            "subject_key": "assets/img-1.png", "evidence_kind": "asset_content",
            "inspection_method": "HUMAN_DIRECT", "source_reference": "assets/img-1.png",
            "context_reference": "book/other.sy#block-1",
            "content_basis": "VISUAL_CONTENT_AND_NOTE_CONTEXT",
        }])
        with self.assertRaisesRegex(ValueError, "不属于该附件引用的文档集合"):
            validator.validate_references(self.ledger, assets_path=self.assets)

    def test_rejects_asset_evidence_without_block_anchor(self):
        self.write(self.ledger, [
            "evidence_id", "subject_type", "subject_key", "evidence_kind",
            "inspection_method", "source_reference", "context_reference", "content_basis",
        ], [{
            "evidence_id": "EV-003", "subject_type": "asset_reference",
            "subject_key": "assets/img-1.png", "evidence_kind": "asset_content",
            "inspection_method": "HUMAN_DIRECT", "source_reference": "assets/img-1.png",
            "context_reference": "book/a.sy",
            "content_basis": "VISUAL_CONTENT_AND_NOTE_CONTEXT",
        }])
        with self.assertRaisesRegex(ValueError, "块定位"):
            validator.validate_references(self.ledger, assets_path=self.assets)

    def test_rejects_asset_evidence_source_outside_assets_root(self):
        self.write(self.ledger, [
            "evidence_id", "subject_type", "subject_key", "evidence_kind",
            "inspection_method", "source_reference", "context_reference", "content_basis",
        ], [{
            "evidence_id": "EV-003", "subject_type": "asset_reference",
            "subject_key": "assets/img-1.png", "evidence_kind": "asset_content",
            "inspection_method": "HUMAN_DIRECT", "source_reference": "catalog/img-1.png",
            "context_reference": "book/a.sy#block-1",
            "content_basis": "VISUAL_CONTENT_AND_NOTE_CONTEXT",
        }])
        with self.assertRaisesRegex(ValueError, "assets/ 下"):
            validator.validate_references(self.ledger, assets_path=self.assets)

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
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method"], [
            {"evidence_id": "EV-001", "subject_type": "topic_decision",
             "subject_key": "book/a.sy", "evidence_kind": "asset_content", "inspection_method": "HUMAN_DIRECT"},
        ])
        with self.assertRaisesRegex(ValueError, "证据类型不匹配"):
            validator.validate_references(self.ledger, self.decisions)

    def test_rejects_source_version_evidence_used_for_identity(self):
        self.write(self.sources, [
            "path", "source_identity_status", "source_identity_evidence_reference",
            "source_version_status", "source_version_evidence_reference",
            "collation_status", "collation_evidence_reference",
        ], [{
            "path": "assets/book.pdf",
            "source_identity_status": "VERIFIED", "source_identity_evidence_reference": "EV-002",
            "source_version_status": "UNVERIFIED", "source_version_evidence_reference": "",
            "collation_status": "UNVERIFIED", "collation_evidence_reference": "",
        }])
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method"], [
            {"evidence_id": "EV-002", "subject_type": "source_candidate",
             "subject_key": "assets/book.pdf", "evidence_kind": "body_page",
             "inspection_method": "HUMAN_DIRECT"},
        ])
        with self.assertRaisesRegex(ValueError, "证据类型不匹配"):
            validator.validate_references(self.ledger, sources_path=self.sources)

    def test_rejects_programmatic_evidence_for_human_conclusion(self):
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method"], [
            {"evidence_id": "EV-001", "subject_type": "topic_decision",
             "subject_key": "book/a.sy", "evidence_kind": "original_sy",
             "inspection_method": "PROGRAMMATIC_STRUCTURE"},
        ])
        with self.assertRaisesRegex(ValueError, "不是人工直接核验记录"):
            validator.validate_references(self.ledger, self.decisions)

    def test_accepts_partial_source_conclusion_without_promoting_it_to_verified(self):
        self.write(self.sources, [
            "path", "source_identity_status", "source_identity_evidence_reference",
            "source_version_status", "source_version_evidence_reference",
            "collation_status", "collation_evidence_reference",
        ], [{
            "path": "assets/book.pdf",
            "source_identity_status": "PARTIAL", "source_identity_evidence_reference": "EV-002",
            "source_version_status": "UNVERIFIED", "source_version_evidence_reference": "",
            "collation_status": "UNVERIFIED", "collation_evidence_reference": "",
        }])
        result = validator.validate_references(self.ledger, sources_path=self.sources)
        self.assertEqual(result["source_conclusions"], 1)

    def test_accepts_partial_document_source_status(self):
        self.write(self.decisions, [
            "document", "title_review_status", "source_status", "source_version_status",
            "collation_status", "topic_review_status", "empty_body_status", "evidence_reference",
        ], [{
            "document": "assets/book.pdf",
            "source_status": "PARTIAL",
            "evidence_reference": "EV-002",
        }])
        result = validator.validate_references(self.ledger, self.decisions)
        self.assertEqual(result["decision_conclusions"], 1)

    def test_rejects_asset_content_evidence_without_sy_context_or_content_basis(self):
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method"], [{
            "evidence_id": "EV-003", "subject_type": "asset_reference",
            "subject_key": "assets/img-1.png", "evidence_kind": "asset_content",
            "inspection_method": "HUMAN_DIRECT",
        }])
        with self.assertRaisesRegex(ValueError, "上下文/块定位"):
            validator.validate_references(self.ledger, assets_path=self.assets)

    def test_rejects_asset_reference_without_content_evidence(self):
        self.write(self.ledger, ["evidence_id", "subject_type", "subject_key", "evidence_kind", "inspection_method"], [
            {"evidence_id": "EV-003", "subject_type": "asset_reference",
             "subject_key": "assets/img-1.png", "evidence_kind": "original_sy", "inspection_method": "HUMAN_DIRECT"},
        ])
        with self.assertRaisesRegex(ValueError, "证据类型不匹配"):
            validator.validate_references(self.ledger, assets_path=self.assets)

    def test_ignores_unverified_source_and_unreviewed_asset(self):
        self.write(self.sources, [
            "path", "source_identity_status", "source_identity_evidence_reference",
            "source_version_status", "source_version_evidence_reference",
            "collation_status", "collation_evidence_reference",
        ], [{
            "path": "assets/book.pdf",
            "source_identity_status": "UNVERIFIED", "source_identity_evidence_reference": "old filename-only note",
            "source_version_status": "UNVERIFIED", "source_version_evidence_reference": "",
            "collation_status": "UNVERIFIED", "collation_evidence_reference": "",
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
