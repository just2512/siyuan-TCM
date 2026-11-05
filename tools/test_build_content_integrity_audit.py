import csv
import json
import tempfile
import unittest
from pathlib import Path

from build_content_integrity_audit import build


class ContentIntegrityAuditTests(unittest.TestCase):
    def test_reports_block_types_and_extracted_text_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            note_dir = root / "notebook"
            note_dir.mkdir()
            (note_dir / "note.sy").write_text(json.dumps({
                "Properties": {"title": "测试笔记"},
                "Children": [
                    {"Type": "NodeText", "Data": "正文内容"},
                    {"Type": "NodeHeading", "Children": [
                        {"Type": "NodeTextMark", "TextMarkTextContent": "标题文字"}
                    ]},
                    {"Type": "NodeImage", "Attrs": {"src": "assets/example.png"}},
                ],
            }, ensure_ascii=False), encoding="utf-8")

            output = root / "catalog" / "generated"
            result = build(root, output)

            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["parsed"], 1)
            self.assertEqual(result["parse_errors"], 0)

            with (output / "content_integrity_audit.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                documents = list(csv.DictReader(stream))
            self.assertEqual(documents[0]["parse_status"], "PARSED")
            self.assertEqual(documents[0]["extracted_payload_count"], "2")
            self.assertEqual(documents[0]["extracted_char_count"], "8")
            self.assertIn("src", documents[0]["unclassified_string_fields"])

            with (output / "block_type_inventory.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                inventory = {row["node_type"]: row for row in csv.DictReader(stream)}
            self.assertEqual(inventory["NodeImage"]["node_count"], "1")
            self.assertEqual(inventory["NodeImage"]["nodes_without_extracted_payload"], "1")
            self.assertEqual(inventory["NodeText"]["extracted_payload_count"], "1")

    def test_parse_error_is_reported_and_returns_nonzero_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "broken.sy").write_text("{broken", encoding="utf-8")
            result = build(root, root / "catalog" / "generated")
            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["parse_errors"], 1)


if __name__ == "__main__":
    unittest.main()
