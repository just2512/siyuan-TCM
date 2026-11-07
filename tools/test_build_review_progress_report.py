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
    def test_report_aggregates_parallel_content_audit_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {name: root / f"{name}.csv" for name in (
                "decisions", "sources", "assets", "evidence", "anomalies",
                "paragraphs", "dosages", "sections", "blocks"
            )}
            paths["decisions"].write_text("document\na.sy\n", encoding="utf-8")
            paths["sources"].write_text("path\na.pdf\n", encoding="utf-8")
            paths["assets"].write_text("reference\na.png\n", encoding="utf-8")
            paths["evidence"].write_text("evidence_id\nEV-1\n", encoding="utf-8")
            paths["anomalies"].write_text(
                "document,anomaly_flags\na.sy,VERY_SHORT_EXTRACTED_TEXT\nb.sy,NO_STATIC_SIGNAL\n",
                encoding="utf-8"
            )
            paths["paragraphs"].write_text("document,finding\na.sy,EXACT_DUPLICATE_PARAGRAPH\n", encoding="utf-8")
            paths["dosages"].write_text("document,review_status\na.sy,NOT_REVIEWED\n", encoding="utf-8")
            paths["sections"].write_text("document,heading_title\na.sy,第一章\n", encoding="utf-8")
            paths["blocks"].write_text("node_type,node_count\nNodeText,2\n", encoding="utf-8")
            report = module.render_report(
                paths["decisions"], paths["sources"], paths["assets"], paths["evidence"],
                content_anomalies=paths["anomalies"],
                paragraph_anomalies=paths["paragraphs"],
                dosage_candidates=paths["dosages"], sections=paths["sections"],
                block_types=paths["blocks"],
            )
            self.assertIn("内容异常扫描文档：2；有静态信号：1", report)
            self.assertIn("段落级异常候选：1", report)
            self.assertIn("剂量样式表达候选：1", report)
            self.assertIn("章节级索引记录：1", report)
            self.assertIn("块类型覆盖记录：1", report)

    def test_report_separates_static_audits_from_human_decision_projections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {name: root / f"{name}.csv" for name in (
                "decisions", "sources", "assets", "evidence", "topics", "titles",
                "empty", "topic_review", "title_review"
            )}
            paths["decisions"].write_text(
                "document,title_review_status,topic_review_status,source_status,"
                "source_version_status,collation_status,empty_body_status\\n"
                "a.sy,CONFIRMED,CONFIRMED,UNVERIFIED,UNVERIFIED,NOT_REVIEWED,NEEDS_SOURCE_INSPECTION\\n",
                encoding="utf-8",
            )
            paths["sources"].write_text("path\\na.pdf\\n", encoding="utf-8")
            paths["assets"].write_text("reference\\na.png\\n", encoding="utf-8")
            paths["evidence"].write_text("evidence_id\\nEV-001\\n", encoding="utf-8")
            paths["topics"].write_text(
                "document,topic,review_status\\na.sy,伤寒与温病,NOT_REVIEWED\\n",
                encoding="utf-8",
            )
            paths["titles"].write_text(
                "document,review_status\\na.sy,NOT_REVIEWED\\n", encoding="utf-8"
            )
            paths["empty"].write_text(
                "document,review_status\\na.sy,NEEDS_SOURCE_INSPECTION\\n", encoding="utf-8"
            )
            paths["topic_review"].write_text(
                "document,review_status,human_approved_topics,reviewer,evidence_reference\\n"
                "a.sy,CONFIRMED,伤寒与温病,reviewer-1,EV-001\\n",
                encoding="utf-8",
            )
            paths["title_review"].write_text(
                "document,review_status,reviewer,evidence_reference\\n"
                "a.sy,CONFIRMED,reviewer-1,EV-001\\n",
                encoding="utf-8",
            )
            report = module.render_report(
                paths["decisions"], paths["sources"], paths["assets"], paths["evidence"],
                paths["topics"], paths["titles"], paths["empty"],
                topic_review=paths["topic_review"], title_review=paths["title_review"],
            )
            self.assertIn("静态风险审计信号（不承载人工决策状态）", report)
            self.assertIn("逐文档—主题审计：1 条（机器规则命中线索", report)
            self.assertIn("标题风险审计：1 条（标题抽取风险线索", report)
            self.assertIn("逐文档—主题复核：1 条；CONFIRMED: 1", report)
            self.assertIn("标题候选复核：1 条；CONFIRMED: 1", report)
            self.assertIn("review-decisions.csv 为唯一持久化来源", report)

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
                "path,source_identity_status,source_identity_evidence_reference,source_version_status,source_version_evidence_reference,collation_status,collation_evidence_reference\n"
                "a.pdf,UNVERIFIED,,UNVERIFIED,,UNVERIFIED,\n"
                "b.pdf,CONFLICT,EV-001,UNRESOLVED,EV-002,UNVERIFIED,\n"
                "c.pdf,PARTIAL,EV-003,UNVERIFIED,,UNVERIFIED,\n"
                "d.pdf,VERIFIED,EV-004,UNVERIFIED,,UNVERIFIED,\n",
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
            self.assertIn("PARTIAL: 1", report)
            self.assertIn("VERIFIED: 1", report)
            self.assertIn("UNRESOLVED: 1", report)
            self.assertIn("NOT_MATCH: 1", report)
            self.assertIn("逐文档—主题审计：2 条", report)
            self.assertIn("标题风险审计：1 条", report)
            self.assertIn("空正文候选：1 条", report)
            self.assertIn("CI 通过不代表人工核验完成", report)


if __name__ == "__main__":
    unittest.main()
