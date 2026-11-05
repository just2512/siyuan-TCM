import unittest

from build_rule_extraction_audit import (
    build_audits,
    parse_evidence,
    title_audit_reason,
)


class RuleExtractionAuditTests(unittest.TestCase):
    def test_parse_evidence_preserves_topic_and_term_boundaries(self):
        self.assertEqual(
            parse_evidence("方剂与用药:方剂、用药;诊断与辨证:问诊"),
            {"方剂与用药": ["方剂", "用药"], "诊断与辨证": ["问诊"]},
        )

    def test_title_audit_flags_fallback_generic_and_sentence_without_rewriting(self):
        self.assertEqual(
            title_audit_reason("其他", "PROPERTY"),
            ["GENERIC_OR_PLACEHOLDER_TITLE"],
        )
        self.assertIn(
            "TITLE_RESEMBLES_BODY_SENTENCE",
            title_audit_reason("这里是一句正文。", "PROPERTY"),
        )
        self.assertIn("TITLE_IS_FALLBACK", title_audit_reason("1、", "BODY_FIRST_LINE"))

    def test_topic_audit_marks_broad_only_and_separates_title_body(self):
        docs = [{
            "path": "book/a.sy",
            "notebook": "书籍",
            "title": "方剂",
            "title_source": "PROPERTY",
            "topics": "方剂与用药;诊断与辨证",
            "title_topic_matched_terms": "方剂与用药:方剂",
            "body_topic_matched_terms": "诊断与辨证:辨证;方剂与用药:用药",
        }]
        _, rows = build_audits(docs)
        formula = next(row for row in rows if row["topic"] == "方剂与用药")
        self.assertIn("BROAD_TERM_ONLY", formula["audit_flags"])
        self.assertIn("MULTI_TOPIC_DOCUMENT", formula["audit_flags"])
        self.assertEqual(formula["title_matched_terms"], "方剂")
        self.assertEqual(formula["body_matched_terms"], "用药")

    def test_topic_audit_does_not_call_static_signal_a_false_positive(self):
        docs = [{
            "path": "book/b.sy",
            "title": "伤寒论",
            "title_source": "PROPERTY",
            "topics": "伤寒与温病",
            "title_topic_matched_terms": "伤寒与温病:伤寒论",
            "body_topic_matched_terms": "",
        }]
        _, rows = build_audits(docs)
        self.assertEqual(rows[0]["audit_flags"], "TITLE_ONLY_MATCH")
        self.assertEqual(rows[0]["review_status"], "NOT_REVIEWED")


if __name__ == "__main__":
    unittest.main()
