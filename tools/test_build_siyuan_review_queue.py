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
                    "path", "notebook", "title", "title_source", "topics", "parse_status", "search_text"
                ])
                writer.writeheader()
                writer.writerow({
                    "path": "book/a.sy", "notebook": "书籍", "title": "伤寒论",
                    "title_source": "PROPERTY", "topics": "伤寒与温病;经典与理论", "parse_status": "PARSED",
                    "search_text": "伤寒论 太阳病 黄帝内经 阴阳",
                })
                writer.writerow({
                    "path": "book/b.sy", "notebook": "书籍", "title": "空白",
                    "title_source": "BODY_FIRST_LINE", "topics": "其他与待归类", "parse_status": "PARSED",
                    "search_text": "",
                })
            output = root / "out"
            result = review.build_review_queues(source, output)
            self.assertEqual(result["documents"], 2)
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
            with (output / "topic_review.csv").open(encoding="utf-8-sig", newline="") as stream:
                topics = list(csv.DictReader(stream))
            self.assertIn("matched_terms", topics[0])
            self.assertEqual(topics[0]["evidence_scope"], "TITLE_PLUS_FIRST_2000_BODY_CHARS")
            self.assertEqual(topics[0]["catalog_topics"], "伤寒与温病;经典与理论")
            self.assertEqual(topics[0]["review_status"], "NOT_REVIEWED")


if __name__ == "__main__":
    unittest.main()
