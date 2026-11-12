import json
import tempfile
import unittest
from pathlib import Path

from build_content_anomaly_audit import build


class ContentAnomalyAuditTests(unittest.TestCase):
    def test_reports_duplicate_and_long_paragraphs_with_source_locator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            notebook = root / "notebook"
            notebook.mkdir()
            repeated = "这是一段用于验证重复段落检测的测试文本。" * 4
            long_text = "长段落内容" * 700
            payload = {
                "Properties": {"title": "内容质量审计"},
                "Children": [
                    {"Type": "NodeParagraph", "Children": [
                        {"Type": "NodeText", "Data": repeated}
                    ]},
                    {"Type": "NodeParagraph", "Children": [
                        {"Type": "NodeText", "Data": repeated}
                    ]},
                    {"Type": "NodeParagraph", "Children": [
                        {"Type": "NodeText", "Data": long_text}
                    ]},
                ],
            }
            (notebook / "note.sy").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            result = build(root, root / "catalog" / "generated")
            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["parse_errors"], 0)
            self.assertEqual(result["paragraph_findings"], 2)

            import csv
            with (root / "catalog" / "generated" / "paragraph_anomaly_audit.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({row["finding"] for row in rows}, {
                "EXACT_DUPLICATE_PARAGRAPH", "VERY_LONG_PARAGRAPH"
            })
            self.assertTrue(all(row["document"] == "notebook/note.sy" for row in rows))

    def test_parse_errors_are_counted_without_fabricating_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.sy").write_text("{bad", encoding="utf-8")
            result = build(root, root / "catalog" / "generated")
            self.assertEqual(result["parse_errors"], 1)
            self.assertEqual(result["paragraph_findings"], 0)


if __name__ == "__main__":
    unittest.main()
