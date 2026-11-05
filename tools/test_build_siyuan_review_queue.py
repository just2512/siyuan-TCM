import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_siyuan_review_queue.py")
SPEC = importlib.util.spec_from_file_location("build_siyuan_review_queue", MODULE_PATH)
review = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(review)


class ReviewQueueTests(unittest.TestCase):
    def test_builds_explicit_unverified_review_states_and_topic_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "documents.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "path", "notebook", "title", "title_source", "topics", "parse_status", "bytes", "asset_ref_count", "node_types", "child_node_count", "search_text", "topic_matched_terms"
                ])
                writer.writeheader()
                writer.writerow({
                    "path": "book/a.sy", "notebook": "书籍", "title": "伤寒论",
                    "title_source": "PROPERTY", "topics": "伤寒与温病;经典与理论", "parse_status": "PARSED",
                    "search_text": "伤寒论 太阳病 黄帝内经 阴阳",
                    "topic_matched_terms": "伤寒与温病:伤寒论;经典与理论:黄帝内经",
                })
                writer.writerow({
                    "path": "book/b.sy", "notebook": "书籍", "title": "空白",
                    "title_source": "BODY_FIRST_LINE", "topics": "其他与待归类", "parse_status": "PARSED",
                    "bytes": "100", "asset_ref_count": "0", "node_types": "NodeParagraph:1",
                    "child_node_count": "1", "search_text": "",
                })
                writer.writerow({
                    "path": "book/c.sy", "notebook": "书籍", "title": "方剂",
                    "title_source": "PROPERTY", "topics": "其他与待归类",
                    "parse_status": "PARSED", "search_text": "普通内容",
                })
            output = root / "out"
            result = review.build_review_queues(source, output)
            self.assertEqual(result["documents"], 3)
            self.assertEqual(result["empty_bodies"], 1)
            self.assertEqual(result["multi_topic_review"], 1)
            with (output / "document_review.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["title_source"], "PROPERTY")
            self.assertEqual(rows[1]["title_source"], "BODY_FIRST_LINE")
            self.assertEqual(rows[0]["source_status"], "UNVERIFIED")
            self.assertEqual(rows[0]["source_version_status"], "UNVERIFIED")
            self.assertEqual(rows[0]["collation_status"], "NOT_REVIEWED")
            self.assertEqual(rows[1]["body_status"], "EMPTY_BODY")
            with (output / "empty_body_review.csv").open(encoding="utf-8-sig", newline="") as stream:
                empty_rows = list(csv.DictReader(stream))
            self.assertEqual(len(empty_rows), 1)
            self.assertEqual(empty_rows[0]["document"], "book/b.sy")
            self.assertEqual(empty_rows[0]["review_status"], "NEEDS_SOURCE_INSPECTION")
            self.assertEqual(empty_rows[0]["structure_status"], "PARAGRAPH_NODES_WITHOUT_EXTRACTED_TEXT")
            with (output / "title_review_candidates.csv").open(encoding="utf-8-sig", newline="") as stream:
                title_candidates = list(csv.DictReader(stream))
            self.assertEqual(len(title_candidates), 2)
            self.assertEqual(title_candidates[0]["reason"], "FALLBACK_TITLE_SOURCE")
            self.assertEqual(title_candidates[1]["reason"], "POSSIBLE_SECTION_OR_PLACEHOLDER_TITLE")
            with (output / "topic_review.csv").open(encoding="utf-8-sig", newline="") as stream:
                topics = list(csv.DictReader(stream))
            self.assertIn("matched_terms", topics[0])
            self.assertEqual(topics[0]["evidence_scope"], "TITLE_PLUS_FIRST_2000_BODY_CHARS")
            self.assertEqual(topics[0]["catalog_topics"], "伤寒与温病;经典与理论")
            self.assertEqual(
                topics[0]["catalog_matched_terms"],
                "伤寒与温病:伤寒论;经典与理论:黄帝内经",
            )
            self.assertEqual(topics[0]["catalog_topic_count"], "2")
            self.assertEqual(topics[0]["excerpt_topic_count"], "2")
            self.assertEqual(topics[0]["review_bucket"], "2_TOPICS")
            self.assertIn("伤寒与温病:伤寒论", topics[0]["title_matched_terms"])
            self.assertIn("经典与理论:黄帝内经", topics[0]["body_excerpt_matched_terms"])
            self.assertEqual(topics[0]["review_status"], "NOT_REVIEWED")

    def test_assign_review_batches_is_stable_and_handles_boundaries(self):
        self.assertEqual(review.assign_review_batches([]), [])
        exact = review.assign_review_batches([{"document": f"d/{i:02}.sy"} for i in range(1, 101)])
        self.assertEqual(len(exact), 100)
        self.assertEqual(exact[0]["batch_id"], "TOPIC-001")
        self.assertEqual(exact[49]["batch_position"], 50)
        self.assertEqual(exact[50]["batch_id"], "TOPIC-002")
        self.assertEqual(exact[99]["batch_size"], 50)
        tail = review.assign_review_batches([{"document": f"d/{i:02}.sy"} for i in range(1, 53)])
        self.assertEqual(tail[50]["batch_id"], "TOPIC-002")
        self.assertEqual(tail[50]["batch_size"], 2)
        self.assertEqual(tail[51]["batch_position"], 2)
        shuffled = review.assign_review_batches([{"document": "z.sy"}, {"document": "a.sy"}])
        self.assertEqual([row["document"] for row in shuffled], ["a.sy", "z.sy"])
        with self.assertRaises(ValueError):
            review.assign_review_batches([], 0)

    def test_title_fallback_flags_body_sentences_and_number_only_lines(self):
        self.assertEqual(
            review.title_candidate_reason("1、", "BODY_FIRST_LINE"),
            "NUMBER_ONLY_BODY_FALLBACK",
        )
        self.assertEqual(
            review.title_candidate_reason("1、伤寒，出自难经第五十八难；（伤于寒的五种病）", "BODY_FIRST_LINE"),
            "BODY_SENTENCE_USED_AS_TITLE",
        )
        self.assertEqual(
            review.title_candidate_reason("伤寒论", "BODY_FIRST_LINE"),
            "FALLBACK_TITLE_SOURCE",
        )
        self.assertEqual(
            review.title_candidate_reason("方剂", "PROPERTY"),
            "POSSIBLE_SECTION_OR_PLACEHOLDER_TITLE",
        )

    def test_review_bucket_does_not_mislabel_single_catalog_topic(self):
        self.assertEqual(review.review_bucket(0), "0_TO_1_TOPICS")
        self.assertEqual(review.review_bucket(1), "0_TO_1_TOPICS")
        self.assertEqual(review.review_bucket(2), "2_TOPICS")
        self.assertEqual(review.review_bucket(4), "3_TO_4_TOPICS")
        self.assertEqual(review.review_bucket(5), "5_PLUS_TOPICS")

    def test_applies_human_decisions_without_overwriting_source_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "documents.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "path", "notebook", "title", "title_source", "topics",
                    "parse_status", "bytes", "asset_ref_count", "node_types",
                    "child_node_count", "search_text",
                ])
                writer.writeheader()
                writer.writerow({
                    "path": "book/a.sy", "notebook": "书籍", "title": "伤寒论",
                    "title_source": "PROPERTY", "topics": "伤寒与温病",
                    "parse_status": "PARSED", "search_text": "伤寒论",
                })
            decisions = root / "review-decisions.csv"
            with decisions.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=review.DECISION_COLUMNS)
                writer.writeheader()
                writer.writerow({
                    "document": "book/a.sy", "reviewer": "reviewer-1",
                    "title_review_status": "CONFIRMED",
                    "source_status": "VERIFIED", "source_version_status": "VERIFIED",
                    "collation_status": "COLLATION_CONFIRMED",
                    "topic_review_status": "CONFIRMED",
                    "human_approved_topics": "伤寒与温病",
                    "review_notes": "与底本目录一致",
                    "evidence_reference": "书名页 p.1；目录 p.3",
                })
            output = root / "out"
            review.build_review_queues(source, output, decisions)
            with (output / "document_review.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["source_status"], "VERIFIED")
            self.assertEqual(rows[0]["title_review_status"], "CONFIRMED")
            self.assertEqual(rows[0]["topic_review_status"], "CONFIRMED")
            self.assertEqual(rows[0]["human_approved_topics"], "伤寒与温病")
            self.assertEqual(rows[0]["evidence_reference"], "书名页 p.1；目录 p.3")
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                original = list(csv.DictReader(stream))
            self.assertEqual(original[0]["topics"], "伤寒与温病")

    def test_rejects_duplicate_decision_rows_and_invalid_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decisions = root / "review-decisions.csv"
            with decisions.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=review.DECISION_COLUMNS)
                writer.writeheader()
                writer.writerow({"document": "book/a.sy"})
                writer.writerow({"document": "book/a.sy"})
            with self.assertRaises(ValueError):
                review.load_decisions(decisions, {"book/a.sy"})
            with decisions.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=review.DECISION_COLUMNS)
                writer.writeheader()
                writer.writerow({"document": "book/a.sy", "source_status": "MAYBE"})
            with self.assertRaises(ValueError):
                review.load_decisions(decisions, {"book/a.sy"})


    def test_rejects_corrected_title_without_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            decisions = Path(temp) / "review-decisions.csv"
            with decisions.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=review.DECISION_COLUMNS)
                writer.writeheader()
                writer.writerow({
                    "document": "book/a.sy",
                    "human_corrected_title": "经方辨证",
                })
            with self.assertRaises(ValueError):
                review.load_decisions(decisions, {"book/a.sy"})

    def test_rejects_decision_without_evidence_or_unknown_document(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decisions = root / "review-decisions.csv"
            with decisions.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=review.DECISION_COLUMNS)
                writer.writeheader()
                writer.writerow({
                    "document": "missing.sy", "source_status": "VERIFIED",
                })
            with self.assertRaises(ValueError):
                review.load_decisions(decisions, {"book/a.sy"})


if __name__ == "__main__":
    unittest.main()
