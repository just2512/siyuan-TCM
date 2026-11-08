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
            "path": "book/a.sy", "title": "伤寒论", "title_source": "BODY_FIRST_LINE",
            "topics": "经典与理论;伤寒与温病", "parse_status": "PARSED",
            "asset_ref_count": "1", "parent_document": "", "document_depth": "0", "child_document_count": "0", "search_text": "太阳病",
            "topic_matched_terms": "伤寒与温病:伤寒论;经典与理论:阴阳",
            "title_topic_matched_terms": "伤寒与温病:伤寒论",
            "body_topic_matched_terms": "经典与理论:阴阳",
        }, {
            "path": "book/b.sy", "title": "空白", "title_source": "PROPERTY",
            "topics": "其他与待归类", "parse_status": "PARSED",
            "asset_ref_count": "0", "parent_document": "", "document_depth": "0", "child_document_count": "0", "search_text": "",
            "topic_matched_terms": "", "title_topic_matched_terms": "", "body_topic_matched_terms": "",
        }]
        self.write(generated / "documents.csv", list(docs[0]), docs)
        self.write(generated / "document_hierarchy.csv", [
            "document", "parent_document", "document_depth", "child_document_count",
            "structure_role",
        ], [
            {"document": d["path"], "parent_document": "", "document_depth": "0",
             "child_document_count": "0", "structure_role": "LEAF"}
            for d in docs
        ])
        self.write(generated / "asset_references.csv",
                   ["document", "reference", "local_status", "local_path", "match_method"], [
            {"document": "book/a.sy", "reference": "assets/a.png", "local_status": "NOT_CHECKED", "local_path": "", "match_method": "NOT_CHECKED"},
        ])
        review_fields = ["document", "title", "topics", "parse_status", "title_review_status", "topic_review_status", "source_status", "source_version_status", "collation_status", "human_corrected_title", "human_approved_topics", "reviewer", "review_notes", "evidence_reference", "parent_document", "document_depth", "child_document_count"]
        self.write(generated / "document_review.csv", review_fields, [
            {"document": d["path"], "title": d["title"], "topics": d["topics"], "parse_status": d["parse_status"], "title_review_status": "NOT_REVIEWED", "topic_review_status": "NOT_REVIEWED", "source_status": "UNVERIFIED", "source_version_status": "UNVERIFIED", "collation_status": "NOT_REVIEWED", "reviewer": "", "review_notes": "", "evidence_reference": "", "parent_document": d["parent_document"], "document_depth": d["document_depth"], "child_document_count": d["child_document_count"]} for d in docs
        ])
        self.write(generated / "empty_body_review.csv", [
            "document", "review_status", "parent_document", "document_depth",
            "child_document_count", "reviewer", "review_notes", "evidence_reference",
        ], [
            {"document": "book/b.sy", "review_status": "NEEDS_SOURCE_INSPECTION",
             "parent_document": "", "document_depth": "0", "child_document_count": "0",
             "reviewer": "", "review_notes": "", "evidence_reference": ""},
        ])
        self.write(generated / "title_review_candidates.csv", ["document", "review_status", "human_corrected_title", "reviewer", "review_notes", "evidence_reference"], [
            {"document": "book/a.sy", "review_status": "NOT_REVIEWED", "human_corrected_title": "", "reviewer": "", "review_notes": "", "evidence_reference": ""},
        ])
        self.write(generated / "topic_review.csv", ["document", "catalog_topics", "catalog_topic_count", "review_bucket", "review_status", "catalog_matched_terms", "catalog_title_matched_terms", "catalog_body_matched_terms", "human_approved_topics", "reviewer", "review_notes", "evidence_reference"], [
            {"document": "book/a.sy", "catalog_topics": docs[0]["topics"], "catalog_topic_count": "2", "review_bucket": "2_TOPICS", "review_status": "NOT_REVIEWED",
             "catalog_matched_terms": docs[0]["topic_matched_terms"],
             "catalog_title_matched_terms": docs[0]["title_topic_matched_terms"],
             "catalog_body_matched_terms": docs[0]["body_topic_matched_terms"]},
        ])
        self.write(generated / "topic_review_batches.csv", ["document", "batch_id", "batch_position", "batch_size", "review_status", "human_approved_topics", "reviewer", "review_notes", "evidence_reference"], [
            {"document": "book/a.sy", "batch_id": "TOPIC-001", "batch_position": "1", "batch_size": "1", "review_status": "NOT_REVIEWED", "human_approved_topics": "", "reviewer": "", "review_notes": "", "evidence_reference": ""},
        ])
        self.write(generated / "asset_review_queue.csv", [
            "reference", "candidate_paths", "candidate_status", "candidate_count",
            "manual_status", "content_evidence_reference",
        ], [
            {"reference": "assets/missing", "candidate_paths": "assets/candidate.png",
             "candidate_status": "ONE_CANDIDATE", "candidate_count": "1",
             "manual_status": "NEEDS_INSPECTION", "content_evidence_reference": ""},
        ])
        source_fields = [
            "path", "candidate_category", "source_identity_status", "source_identity_evidence_reference",
            "source_version_status", "source_version_evidence_reference",
            "collation_status", "collation_evidence_reference",
        ]
        source_row = {
            "path": "assets/book.pdf", "candidate_category": "asset_file",
            "source_identity_status": "UNVERIFIED", "source_identity_evidence_reference": "",
            "source_version_status": "UNVERIFIED", "source_version_evidence_reference": "",
            "collation_status": "UNVERIFIED", "collation_evidence_reference": "",
        }
        self.write(generated / "source_review_queue.csv", source_fields, [source_row])
        source_candidates = root / "source.csv"
        self.write(source_candidates, source_fields, [source_row])
        asset_candidates = root / "asset.csv"
        self.write(asset_candidates, [
            "reference", "candidate_paths", "candidate_status", "candidate_count",
            "manual_status", "content_evidence_reference",
        ], [
            {"reference": "assets/missing", "candidate_paths": "assets/candidate.png",
             "candidate_status": "ONE_CANDIDATE", "candidate_count": "1",
             "manual_status": "NEEDS_INSPECTION", "content_evidence_reference": ""},
        ])
        return generated, source_candidates, asset_candidates

    def test_rejects_decision_table_projection_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated, source, assets = self.fixture(root)
            decisions = root / "review-decisions.csv"
            fields = [
                "document", "reviewer", "title_review_status", "human_corrected_title",
                "source_status", "source_version_status", "collation_status",
                "topic_review_status", "human_approved_topics", "empty_body_status",
                "review_notes", "evidence_reference",
            ]
            self.write(decisions, fields, [{
                "document": "book/a.sy", "reviewer": "reviewer-1",
                "title_review_status": "CONFIRMED", "evidence_reference": "EV-001",
            }])
            with self.assertRaisesRegex(ValueError, "document_review.title_review_status 与 review-decisions.csv 不一致"):
                validator.validate_catalogue(generated, source, assets, decisions)

    def test_rejects_empty_body_decision_projection_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated, source, assets = self.fixture(root)
            decisions = root / "review-decisions.csv"
            fields = [
                "document", "reviewer", "title_review_status", "human_corrected_title",
                "source_status", "source_version_status", "collation_status",
                "topic_review_status", "human_approved_topics", "empty_body_status",
                "review_notes", "evidence_reference",
            ]
            self.write(decisions, fields, [{
                "document": "book/b.sy", "reviewer": "reviewer-2",
                "empty_body_status": "UNRESOLVED", "review_notes": "原始 .sy 待检查",
                "evidence_reference": "EV-002",
            }])
            review_path = generated / "document_review.csv"
            with review_path.open(encoding="utf-8-sig", newline="") as stream:
                review_rows = list(csv.DictReader(stream))
            for row in review_rows:
                if row["document"] == "book/b.sy":
                    row["reviewer"] = "reviewer-2"
                    row["review_notes"] = "原始 .sy 待检查"
                    row["evidence_reference"] = "EV-002"
            self.write(review_path, list(review_rows[0]), review_rows)
            empty_path = generated / "empty_body_review.csv"
            with empty_path.open(encoding="utf-8-sig", newline="") as stream:
                empty_rows = list(csv.DictReader(stream))
            empty_rows[0]["reviewer"] = "reviewer-2"
            empty_rows[0]["review_notes"] = "原始 .sy 待检查"
            empty_rows[0]["evidence_reference"] = "EV-002"
            self.write(empty_path, list(empty_rows[0]), empty_rows)
            with self.assertRaisesRegex(ValueError, "empty_body_review.review_status 与 review-decisions.csv 不一致"):
                validator.validate_catalogue(generated, source, assets, decisions)

    def test_accepts_persisted_decisions_projected_to_review_queues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated, source, assets = self.fixture(root)
            decisions = root / "review-decisions.csv"
            fields = [
                "document", "reviewer", "title_review_status", "human_corrected_title",
                "source_status", "source_version_status", "collation_status",
                "topic_review_status", "human_approved_topics", "empty_body_status",
                "review_notes", "evidence_reference",
            ]
            self.write(decisions, fields, [
                {
                    "document": "book/a.sy", "reviewer": "reviewer-1",
                    "title_review_status": "CONFIRMED", "source_status": "PARTIAL",
                    "source_version_status": "VERIFIED", "collation_status": "COLLATION_CONFIRMED",
                    "topic_review_status": "CONFIRMED", "human_approved_topics": "伤寒与温病",
                    "review_notes": "人工核验完成", "evidence_reference": "EV-001",
                },
                {
                    "document": "book/b.sy", "reviewer": "reviewer-2",
                    "empty_body_status": "UNRESOLVED",
                    "review_notes": "原始 .sy 待检查", "evidence_reference": "EV-002",
                },
            ])

            def update_rows(path, key, key_value, updates):
                file_path = generated / path
                with file_path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                target = next(row for row in rows if row[key] == key_value)
                target.update(updates)
                self.write(file_path, list(target), rows)

            update_rows("document_review.csv", "document", "book/a.sy", {
                "title_review_status": "CONFIRMED", "source_status": "PARTIAL",
                "source_version_status": "VERIFIED", "collation_status": "COLLATION_CONFIRMED",
                "topic_review_status": "CONFIRMED", "human_approved_topics": "伤寒与温病",
                "reviewer": "reviewer-1", "review_notes": "人工核验完成",
                "evidence_reference": "EV-001",
            })
            update_rows("document_review.csv", "document", "book/b.sy", {
                "reviewer": "reviewer-2", "review_notes": "原始 .sy 待检查",
                "evidence_reference": "EV-002",
            })
            shared = {
                "reviewer": "reviewer-1", "review_notes": "人工核验完成",
                "evidence_reference": "EV-001",
            }
            update_rows("title_review_candidates.csv", "document", "book/a.sy", {
                "review_status": "CONFIRMED", **shared,
            })
            update_rows("topic_review.csv", "document", "book/a.sy", {
                "review_status": "CONFIRMED", "human_approved_topics": "伤寒与温病", **shared,
            })
            update_rows("topic_review_batches.csv", "document", "book/a.sy", {
                "review_status": "CONFIRMED", "human_approved_topics": "伤寒与温病", **shared,
            })
            update_rows("empty_body_review.csv", "document", "book/b.sy", {
                "review_status": "UNRESOLVED", "reviewer": "reviewer-2",
                "review_notes": "原始 .sy 待检查", "evidence_reference": "EV-002",
            })
            validator.validate_catalogue(generated, source, assets, decisions)

    def test_accepts_consistent_catalogue_and_review_queues(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.fixture(Path(temp))
            self.assertEqual(validator.validate_catalogue(*paths), {
                "documents": 2, "asset_references": 1, "document_review": 2,
                "empty_body_review": 1, "title_review_candidates": 1,
                "topic_review": 1, "asset_review_queue": 1, "source_review_queue": 1,
            })

    def test_accepts_independent_source_identity_status_when_queue_and_input_match(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            with source.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["source_identity_status"] = "PARTIAL"
            rows[0]["source_identity_evidence_reference"] = "EV-001"
            self.write(source, list(rows[0]), rows)
            queue_fields = list(rows[0])
            self.write(generated / "source_review_queue.csv", queue_fields, rows)
            self.assertEqual(validator.validate_catalogue(generated, source, assets)["source_review_queue"], 1)

    def test_rejects_source_status_without_its_own_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            with source.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["source_version_status"] = "PARTIAL"
            self.write(source, list(rows[0]), rows)
            self.write(generated / "source_review_queue.csv", list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "source_version_status 已有结论但缺少"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_confirmed_asset_match_without_content_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            queue_path = generated / "asset_review_queue.csv"
            source_path = assets
            for path in (queue_path, source_path):
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                rows[0]["manual_status"] = "CONFIRMED_MATCH"
                rows[0]["content_evidence_reference"] = ""
                self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "缺少 content_evidence_reference"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_topic_evidence_source_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "documents.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["title_topic_matched_terms"] = ""
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "主题命中词汇总与标题/正文证据不一致"):
                validator.validate_catalogue(generated, source, assets)

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
            self.write(path, ["document", "title", "topics", "parse_status", "title_review_status", "topic_review_status", "source_status", "source_version_status", "collation_status", "human_corrected_title", "human_approved_topics", "reviewer", "review_notes", "evidence_reference", "parent_document", "document_depth", "child_document_count"], [])
            with self.assertRaisesRegex(ValueError, "文档集合不一致"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_asset_queue_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "asset_review_queue.csv"
            self.write(path, [
                "reference", "candidate_paths", "candidate_status", "candidate_count",
                "manual_status", "content_evidence_reference",
            ], [
                {"reference": "assets/missing", "candidate_paths": "",
                 "candidate_status": "NO_CANDIDATE", "candidate_count": "0",
                 "manual_status": "NEEDS_INSPECTION", "content_evidence_reference": ""},
            ])
            with self.assertRaisesRegex(ValueError, "附件候选队列"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_asset_candidate_path_projection_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "asset_review_queue.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["candidate_paths"] = "assets/other.png"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "附件候选队列与原始候选表不一致"):
                validator.validate_catalogue(generated, source, assets)


    def test_rejects_review_conclusion_without_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "document_review.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["source_status"] = "VERIFIED"
            rows[0]["reviewer"] = "reviewer-1"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "缺少 evidence_reference"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_duplicate_document_in_topic_batches(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "topic_review_batches.csv"
            self.write(path, ["document", "batch_id", "batch_position", "batch_size", "review_status", "human_approved_topics", "reviewer", "review_notes", "evidence_reference"], [
                {"document": "book/a.sy", "batch_id": "TOPIC-001", "batch_position": "1", "batch_size": "2", "review_status": "NOT_REVIEWED", "human_approved_topics": "", "reviewer": "", "review_notes": "", "evidence_reference": ""},
                {"document": "book/a.sy", "batch_id": "TOPIC-001", "batch_position": "2", "batch_size": "2", "review_status": "NOT_REVIEWED", "human_approved_topics": "", "reviewer": "", "review_notes": "", "evidence_reference": ""},
            ])
            with self.assertRaisesRegex(ValueError, "重复 document"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_missing_multi_topic_document_from_topic_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            self.write(generated / "topic_review.csv", [
                "document", "catalog_topics", "catalog_topic_count", "review_bucket",
                "review_status", "catalog_matched_terms", "catalog_title_matched_terms",
                "catalog_body_matched_terms", "human_approved_topics", "reviewer",
                "review_notes", "evidence_reference",
            ], [])
            self.write(generated / "topic_review_batches.csv", [
                "document", "batch_id", "batch_position", "batch_size", "review_status",
                "human_approved_topics", "reviewer", "review_notes", "evidence_reference",
            ], [])
            with self.assertRaisesRegex(ValueError, "topic_review.csv 与多主题文档集合不一致"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_invalid_empty_body_review_status(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "empty_body_review.csv"
            self.write(path, ["document", "review_status", "parent_document", "document_depth", "child_document_count", "reviewer", "review_notes", "evidence_reference"], [
                {"document": "book/b.sy", "review_status": "MADE_UP",
                 "parent_document": "", "document_depth": "0", "child_document_count": "0",
                 "reviewer": "", "review_notes": "", "evidence_reference": ""},
            ])
            with self.assertRaisesRegex(ValueError, "review_status 无效"):
                validator.validate_catalogue(generated, source, assets)


    def test_rejects_missing_title_candidate_from_title_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            self.write(generated / "title_review_candidates.csv", [
                "document", "review_status", "human_corrected_title",
                "reviewer", "review_notes", "evidence_reference",
            ], [])
            with self.assertRaisesRegex(ValueError, "title_review_candidates.csv 与标题候选文档集合不一致"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_title_queue_reviewer_projection_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "title_review_candidates.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["reviewer"] = "reviewer-1"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "标题复核队列 reviewer"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_topic_queue_approved_topics_projection_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "topic_review.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["human_approved_topics"] = "伤寒与温病"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "主题复核队列 human_approved_topics"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_topic_batch_reviewer_projection_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "topic_review_batches.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["reviewer"] = "reviewer-1"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "主题批次 reviewer"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_active_document_conclusion_without_reviewer(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "document_review.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["source_status"] = "PARTIAL"
            rows[0]["evidence_reference"] = "EV-001"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "缺少 reviewer"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_topic_conclusion_without_approved_topics(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "document_review.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["topic_review_status"] = "CONFIRMED"
            rows[0]["reviewer"] = "reviewer-1"
            rows[0]["evidence_reference"] = "EV-001"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "缺少 human_approved_topics"):
                validator.validate_catalogue(generated, source, assets)

    def test_accepts_partial_document_source_status_with_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "document_review.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            target = next(row for row in rows if row["document"] == "book/a.sy")
            target["source_status"] = "PARTIAL"
            target["reviewer"] = "reviewer-1"
            target["evidence_reference"] = "EV-001"
            self.write(path, list(target), rows)
            for queue_name in ("title_review_candidates.csv", "topic_review.csv", "topic_review_batches.csv"):
                queue_path = generated / queue_name
                with queue_path.open(encoding="utf-8-sig", newline="") as stream:
                    queue_rows = list(csv.DictReader(stream))
                queue_target = next(row for row in queue_rows if row["document"] == "book/a.sy")
                queue_target["reviewer"] = "reviewer-1"
                queue_target["evidence_reference"] = "EV-001"
                self.write(queue_path, list(queue_target), queue_rows)
            validator.validate_catalogue(generated, source, assets)

    def test_rejects_topic_queue_status_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "topic_review.csv"
            self.write(path, ["document", "catalog_topics", "catalog_topic_count", "review_bucket", "review_status", "catalog_matched_terms", "catalog_title_matched_terms", "catalog_body_matched_terms", "human_approved_topics", "reviewer", "review_notes", "evidence_reference"], [
                {"document": "book/a.sy", "catalog_topics": "经典与理论;伤寒与温病", "catalog_topic_count": "2", "review_bucket": "2_TOPICS", "review_status": "CONFIRMED",
                 "catalog_matched_terms": "伤寒与温病:伤寒论;经典与理论:阴阳",
                 "catalog_title_matched_terms": "伤寒与温病:伤寒论",
                 "catalog_body_matched_terms": "经典与理论:阴阳"},
            ])
            with self.assertRaisesRegex(ValueError, "主题复核队列状态"):
                validator.validate_catalogue(generated, source, assets)

    def test_rejects_duplicate_csv_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "documents.csv"
            path.write_text("path,path,title,title_source,topics,parse_status,asset_ref_count,search_text\\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "重复列名"):
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


    def test_rejects_hierarchy_context_drift_in_review_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "document_review.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["parent_document"] = "book/missing-parent.sy"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "document_review.parent_document"):
                validator.validate_catalogue(generated, source, assets)

        with tempfile.TemporaryDirectory() as temp:
            generated, source, assets = self.fixture(Path(temp))
            path = generated / "empty_body_review.csv"
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["child_document_count"] = "1"
            self.write(path, list(rows[0]), rows)
            with self.assertRaisesRegex(ValueError, "empty_body_review.child_document_count"):
                validator.validate_catalogue(generated, source, assets)


if __name__ == "__main__":
    unittest.main()
