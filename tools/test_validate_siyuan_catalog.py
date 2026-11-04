import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("validate_siyuan_catalog.py")
SPEC = importlib.util.spec_from_file_location("validate_siyuan_catalog", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)


class CatalogueValidationTests(unittest.TestCase):
    def write(self, path, fields, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def fixture(self, root):
        generated = root / "generated"
        generated.mkdir()
        docs = [{
            "path": "book/a.sy", "title": "伤寒论", "title_source": "PROPERTY",
            "topics": "经典与理论;伤寒与温病", "parse_status": "PARSED",
            "asset_ref_count": "1", "search_text": "太阳病",
        }, {
            "path": "book/b.sy", "title": "空白", "title_source": "PROPERTY",
            "topics": "其他与待归类", "parse_status": "PARSED",
            "asset_ref_count": "0", "search_text": "",
        }]
        self.write(generated / "documents.csv", list(docs[0]), docs)
        self.write(generated / "asset_references.csv",
                   ["document", "reference", "local_status", "local_path", "match_method"], [
            {"document": "book/a.sy", "reference": "assets/a.png", "local_status": "NOT_CHECKED", "local_path": "", "match_method": "NOT_CHECKED"},
        ])
        review_fields = ["document", "title", "topics", "parse_status", "title_review_status", "source_status", "source_version_status", "collation_status"]
        self.write(generated / "document_review.csv", review_fields, [
            {"document": d["path"], "title": d["title"], "topics": d["topics"], "parse_status": d["parse_status"], "title_review_status": "NOT_REVIEWED", "source_status": "UNVERIFIED", "source_version_status": "UNVERIFIED", "collation_status": "NOT_REVIEWED"} for d in docs
        ])
        self.write(generated / "empty_body_review.csv", ["document", "review_status"], [
            {"document": "book/b.sy", "review_status": "NEEDS_SOURCE_INSPECTION"},
        ])
        self.write(generated / "title_review_candidates.csv", ["document", "review_status"], [])
        self.write(generated / "topic_review.csv", ["document", "catalog_topics", "catalog_topic_count", "review_bucket"], [
            {"document": "book/a.sy", "catalog_topics": docs[0]["topics"], "catalog_topic_count": "2", "review_bucket": "2_TOPICS"},
        ])
        self.write(generated / "topic_review_batches.csv", ["document", "batch_id", "batch_position"], [
            {"document": "book/a.sy", "batch_id": "TOPIC-001", "batch_position": "1"},
        ])
        self.write(generated / "asset_review_queue.csv", ["reference", "candidate_status", "candidate_count", "manual_status"], [
            {"reference": "assets/missing", "candidate_status": "ONE_CANDIDATE", "candidate_count": "1", "manual_status": "NEEDS_INSPECTION"},
        ])
        self.write(generated / "source_review_queue.csv", ["path", "candidate_category", "verification_status", "evidence_reference"], [
            {"path": "assets/book.pdf", "candidate_category": "asset_file", "verification_status": "UNVERIFIED", "evidence_reference": ""},
        ])
        source_candidates = root / "source.csv"
        self.write(source_candidates, ["path", "candidate_category", "verification_status", "evidence_reference"], [
            {"path": "assets/book.pdf", "candidate_category": "asset_file", "verification_status": "UNVERIFIED", "evidence_reference": ""},
        ])
        asset_candidates = root / "asset.csv"
        self.write(asset_candidates, ["reference", "candidate_status", "candidate_count"], [
            {"reference": "assets/missing", "candidate_status": "ONE_CANDIDATE", "candidate_count": "1"},
        ])
        return generated, source_candidates, asset_candidates

    def test_accepts_consistent_catalogue_and_review_queues(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.fixture(Path(temp))
            self.assertEqual(validator.validate_catalogue(*paths), {
                "documents": 2, "asset_references": 1, "document_review": 2,
                "empty_body_review": 1, "title_review_candidates": 0,
                "topic_review": 1, "asset_review_queue": 1, "source_review_queue": 1,
            })

    def test_rejects_asset_reference_count_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "documents.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["asset_ref_count"] = "2"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "附件引用计数"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_review_queue_missing_document(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "document_review.csv"
            self.write(path, ["document", "title", "topics", "parse_status", "title_review_status", "source_status", "source_version_status", "collation_status"], [])
            with self.assertRaisesRegex(ValueError, "文档集合不一致"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_asset_queue_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "asset_review_queue.csv"
            self.write(path, ["reference", "candidate_status", "candidate_count", "manual_status"], [
                {"reference": "assets/missing", "candidate_status": "NO_CANDIDATE", "candidate_count": "0", "manual_status": "NEEDS_INSPECTION"},
            ])
            with self.assertRaisesRegex(ValueError, "附件候选队列"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_unknown_document_in_asset_references(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "asset_references.csv"
            self.write(path, ["document", "reference", "local_status", "local_path", "match_method"], [
                {"document": "unknown.sy", "reference": "assets/a.png", "local_status": "NOT_CHECKED", "local_path": "", "match_method": "NOT_CHECKED"},
            ])
            with self.assertRaisesRegex(ValueError, "未知文档"):
                validator.validate_catalogue(generated, source, assets)


if __name__ == "__main__":
    unittest.main()
