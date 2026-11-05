import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_review_progress_report.py")
SPEC = importlib.util.spec_from_file_location("build_review_progress_report", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class ReviewProgressReportTests(unittest.TestCase):
    def test_report_keeps_pending_conflict_and_unresolved_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decisions = root / "decisions.csv"
            sources = root / "sources.csv"
            assets = root / "assets.csv"
            evidence = root / "evidence.csv"
            topics = root / "topics.csv"
            titles = root / "titles.csv"
            empty_body = root / "empty.csv"
            decisions.write_text(
                "document,topic_review_status,empty_body_status\n"
                "a.sy,,NEEDS_SOURCE_INSPECTION\n"
                "b.sy,UNRESOLVED,\n", encoding="utf-8"
            )
            sources.write_text(
                "path,verification_status\na.pdf,UNVERIFIED\nb.pdf,CONFLICT\n",
                encoding="utf-8"
            )
            assets.write_text(
                "reference,manual_status\na.png,NEEDS_INSPECTION\nb.png,NOT_MATCH\n",
                encoding="utf-8"
            )
            evidence.write_text(
                "evidence_id,evidence_kind\nEV-001,original_sy\n", encoding="utf-8"
            )
            topics.write_text(
                "document,topic,review_status\na.sy,主题甲,NOT_REVIEWED\nb.sy,主题乙,UNRESOLVED\n",
                encoding="utf-8"
            )
            titles.write_text(
                "document,review_status\na.sy,NOT_REVIEWED\n",
                encoding="utf-8"
            )
            empty_body.write_text(
                "document,review_status\na.sy,NEEDS_SOURCE_INSPECTION\n",
                encoding="utf-8"
            )
            report = module.render_report(decisions, sources, assets, evidence,
                                          topics, titles, empty_body)
            self.assertIn("NOT_REVIEWED: 1", report)
            self.assertIn("NEEDS_SOURCE_INSPECTION: 1", report)
            self.assertIn("CONFLICT: 1", report)
            self.assertIn("UNRESOLVED: 1", report)
            self.assertIn("NOT_MATCH: 1", report)
            self.assertIn("逐文档—主题审计：2 条", report)
            self.assertIn("标题风险审计：1 条", report)
            self.assertIn("空正文候选：1 条", report)
            self.assertIn("CI 通过不代表人工核验完成", report)


if __name__ == "__main__":
    unittest.main()
