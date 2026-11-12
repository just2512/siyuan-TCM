import json
import tempfile
import unittest
from pathlib import Path

from build_section_index import build_sections, build


class SectionIndexTests(unittest.TestCase):
    def test_builds_heading_sections_with_source_block_ids_and_body(self):
        root = {
            "Children": [
                {"Type": "NodeParagraph", "Children": [
                    {"Type": "NodeText", "Data": "前言内容"}
                ]},
                {"Type": "NodeHeading", "ID": "h1", "HeadingLevel": 2, "Children": [
                    {"Type": "NodeText", "Data": "第一章"}
                ]},
                {"Type": "NodeParagraph", "Children": [
                    {"Type": "NodeText", "Data": "第一章正文"}
                ]},
                {"Type": "NodeHeading", "ID": "h2", "HeadingLevel": 3, "Children": [
                    {"Type": "NodeText", "Data": "第一节"}
                ]},
                {"Type": "NodeParagraph", "Children": [
                    {"Type": "NodeText", "Data": "第一节正文"}
                ]},
                {"Type": "NodeHeading", "ID": "h3", "HeadingLevel": 2, "Children": [
                    {"Type": "NodeText", "Data": "第二章"}
                ]},
                {"Type": "NodeParagraph", "Children": [
                    {"Type": "NodeText", "Data": "第二章正文"}
                ]},
            ]
        }
        rows = build_sections(root, "book/note.sy")
        self.assertEqual([row["heading_title"] for row in rows],
                         ["[未分节正文]", "第一章", "第一节", "第二章"])
        self.assertEqual([row["section_index"] for row in rows], [0, 1, 2, 3])
        self.assertEqual(rows[0]["body_excerpt"], "前言内容")
        self.assertEqual(rows[1]["body_excerpt"], "第一章正文")
        self.assertEqual(rows[2]["body_excerpt"], "第一节正文")
        self.assertEqual(rows[3]["body_excerpt"], "第二章正文")
        self.assertEqual(rows[1]["heading_block_id"], "h1")

    def test_build_scans_real_style_sy_files_and_writes_csv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "note.sy").write_text(json.dumps({
                "Children": [{"Type": "NodeHeading", "ID": "h1", "HeadingLevel": 1,
                              "Children": [{"Type": "NodeText", "Data": "标题"}]}]
            }, ensure_ascii=False), encoding="utf-8")
            result = build(root, root / "catalog" / "generated")
            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["sections"], 1)
            self.assertTrue((root / "catalog" / "generated" / "section_index.csv").is_file())


if __name__ == "__main__":
    unittest.main()
