import csv
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_node_semantic_index.py")
SPEC = importlib.util.spec_from_file_location("build_node_semantic_index", MODULE_PATH)
indexer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(indexer)


class NodeSemanticIndexTests(unittest.TestCase):
    def test_separates_text_html_media_and_link_targets(self):
        payload = {"Children": [
            {"ID": "p1", "Type": "NodeParagraph", "Children": [
                {"ID": "t1", "Type": "NodeText", "Data": "太阳病"},
                {"ID": "m1", "Type": "NodeTextMark",
                 "TextMarkType": "inline-math",
                 "TextMarkInlineMathContent": "x^2"},
                {"ID": "h1", "Type": "NodeHTMLBlock",
                 "Data": "<p>可见<strong>HTML</strong>文本</p>"},
                {"ID": "v1", "Type": "NodeVideo", "Data": "assets/lesson.mp4"},
                {"ID": "i1", "Type": "NodeImage", "Data": "span"},
                {"ID": "d1", "Type": "NodeLinkDest", "Data": "https://example.test"},
            ]}
        ]}
        rows = []
        unknown = indexer.Counter()
        indexer.walk_nodes(payload, "book/doc.sy", "abc", rows, unknown)
        by_id = {row["block_id"]: row for row in rows}
        self.assertEqual(by_id["t1"]["text"], "太阳病")
        self.assertEqual(by_id["m1"]["semantic_role"], "INLINE_MATH")
        self.assertEqual(by_id["h1"]["text"], "可见 HTML 文本")
        self.assertEqual(by_id["h1"]["raw_payload"], "<p>可见<strong>HTML</strong>文本</p>")
        self.assertEqual(by_id["v1"]["semantic_role"], "MEDIA_REFERENCE")
        self.assertEqual(by_id["v1"]["text"], "")
        self.assertEqual(by_id["i1"]["semantic_role"], "IMAGE_LAYOUT")
        self.assertEqual(by_id["d1"]["semantic_role"], "LINK_TARGET")
        self.assertEqual(by_id["d1"]["text"], "")


    def test_html_index_omits_script_and_style_payloads(self):
        payload = {"Type": "NodeHTMLBlock",
                   "Data": "<p>可见内容<script>alert(1)</script><style>.x{}</style></p>"}
        role, text, raw = indexer.direct_payload(payload)
        self.assertEqual(role, "HTML")
        self.assertEqual(text, "可见内容")
        self.assertIn("alert(1)", raw)

    def test_preserves_parent_child_and_tree_position(self):
        payload = {"Children": [{"ID": "p", "Type": "NodeParagraph",
            "Children": [{"ID": "t", "Type": "NodeText", "Data": "内容"}]}]}
        rows = []
        indexer.walk_nodes(payload, "d.sy", "hash", rows, indexer.Counter())
        child = next(row for row in rows if row["block_id"] == "t")
        self.assertEqual(child["parent_block_id"], "p")
        self.assertEqual(child["parent_node_type"], "NodeParagraph")
        self.assertEqual(child["tree_position"], "0.0.0")

    def test_table_and_list_containers_keep_structure_and_aggregate_text(self):
        payload = {"Children": [
            {"ID": "table", "Type": "NodeTable", "Children": [
                {"ID": "cell", "Type": "NodeTableCell", "Children": [
                    {"ID": "cell-text", "Type": "NodeText", "Data": "药名"}
                ]}
            ]},
            {"ID": "list", "Type": "NodeList", "Children": [
                {"ID": "item", "Type": "NodeListItem", "Children": [
                    {"ID": "item-text", "Type": "NodeText", "Data": "桂枝汤"}
                ]}
            ]}
        ]}
        rows = []
        indexer.walk_nodes(payload, "d.sy", "hash", rows, indexer.Counter())
        by_id = {row["block_id"]: row for row in rows}
        self.assertEqual(by_id["table"]["semantic_role"], "STRUCTURE")
        self.assertEqual(by_id["cell"]["container_text"], "药名")
        self.assertEqual(by_id["list"]["semantic_role"], "STRUCTURE")
        self.assertEqual(by_id["item"]["container_text"], "桂枝汤")

    def test_unmapped_fields_are_reported_not_silently_indexed_as_text(self):
        payload = {"Children": [{"ID": "x", "Type": "NodeTextMark",
            "TextMarkTextContent": "正文", "TextMarkType": "text",
            "TextMarkBlockRefID": "target-id"}]}
        rows = []
        unknown = indexer.Counter()
        indexer.walk_nodes(payload, "d.sy", "hash", rows, unknown)
        self.assertEqual(rows[0]["text"], "正文")
        self.assertEqual(rows[0]["mark_type"], "text")
        self.assertEqual(rows[0]["block_ref_id"], "target-id")
        self.assertEqual(unknown["NodeTextMark.TextMarkType"], 0)
        self.assertEqual(unknown["NodeTextMark.TextMarkBlockRefID"], 0)


    def test_structural_fields_are_classified_without_becoming_prose(self):
        payload = {"Children": [
            {"ID": "br", "Type": "NodeBr", "Data": "br"},
            {"ID": "ial", "Type": "NodeKramdownSpanIAL", "Data": "{: style=color-red}"},
            {"ID": "cell", "Type": "NodeTableCell", "Data": "span"},
            {"ID": "escape", "Type": "NodeBackslashContent", "Data": "*"},
        ]}
        rows = []
        unknown = indexer.Counter()
        indexer.walk_nodes(payload, "d.sy", "hash", rows, unknown)
        by_id = {row["block_id"]: row for row in rows}
        self.assertEqual(by_id["br"]["semantic_role"], "LINE_BREAK")
        self.assertEqual(by_id["ial"]["semantic_role"], "INLINE_STYLE_METADATA")
        self.assertEqual(by_id["cell"]["semantic_role"], "TABLE_CELL_LAYOUT")
        self.assertEqual(by_id["escape"]["semantic_role"], "ESCAPED_CONTENT")
        self.assertTrue(all(not row["text"] for row in rows))
        self.assertEqual(len(unknown), 0)




    def test_assigns_heading_ancestry_to_searchable_blocks(self):
        rows = [
            {"document": "d.sy", "content_type": "HEADING", "heading_level": 1,
             "content_text": "经方总论", "block_id": "h1"},
            {"document": "d.sy", "content_type": "PARAGRAPH", "heading_level": "",
             "content_text": "正文一", "block_id": "p1"},
            {"document": "d.sy", "content_type": "HEADING", "heading_level": 2,
             "content_text": "桂枝汤", "block_id": "h2"},
            {"document": "d.sy", "content_type": "TABLE_CELL", "heading_level": "",
             "content_text": "芍药", "block_id": "c1"},
            {"document": "d.sy", "content_type": "HEADING", "heading_level": 1,
             "content_text": "中药", "block_id": "h3"},
            {"document": "d.sy", "content_type": "PARAGRAPH", "heading_level": "",
             "content_text": "正文二", "block_id": "p2"},
        ]
        indexer.assign_section_context(rows)
        self.assertEqual(rows[1]["section_path"], "经方总论")
        self.assertEqual(rows[3]["section_path"], "经方总论 / 桂枝汤")
        self.assertEqual(rows[3]["section_heading_block_ids"], "h1;h2")
        self.assertEqual(rows[5]["section_path"], "中药")

    def test_builds_resolvable_block_and_resource_relationship_edges(self):
        payload = {"ID": "doc", "Type": "NodeDocument", "Children": [
            {"ID": "source", "Type": "NodeParagraph", "Children": [
                {"ID": "mark", "Type": "NodeTextMark",
                 "TextMarkType": "block-ref",
                 "TextMarkBlockRefID": "target",
                 "TextMarkBlockRefSubtype": "d",
                 "TextMarkAHref": "https://example.test/ref"},
                {"ID": "dest", "Type": "NodeLinkDest",
                 "Data": "assets/herb.png"},
                {"ID": "media", "Type": "NodeVideo",
                 "Data": "assets/lesson.mp4"}
            ]},
            {"ID": "target", "Type": "NodeParagraph", "Children": [
                {"ID": "target-text", "Type": "NodeText", "Data": "目标块"}
            ]}
        ]}
        rows = []
        indexer.walk_nodes(payload, "book/doc.sy", "hash", rows, indexer.Counter())
        edges = indexer.build_relationship_rows(rows)
        block = next(edge for edge in edges if edge["relation_type"] == "BLOCK_REFERENCE")
        self.assertEqual(block["target"], "target")
        self.assertEqual(block["target_document"], "book/doc.sy")
        self.assertEqual(block["resolution"], "RESOLVED_IN_CORPUS")
        href = next(edge for edge in edges if edge["relation_type"] == "HYPERLINK")
        self.assertEqual(href["resolution"], "EXTERNAL_URL")
        asset = next(edge for edge in edges if edge["relation_type"] == "LINK_DESTINATION")
        self.assertEqual(asset["resolution"], "ASSET_REFERENCE")
        media = next(edge for edge in edges if edge["relation_type"] == "MEDIA_REFERENCE")
        self.assertEqual(media["resolution"], "REFERENCE_RECORDED_NOT_FILE_VERIFIED")

    def test_marks_missing_and_ambiguous_block_references_explicitly(self):
        rows = [
            {"document": "a.sy", "source_sha256": "a", "tree_position": "0",
             "block_id": "duplicate", "parent_block_id": "", "node_type": "NodeParagraph",
             "block_ref_id": "", "block_ref_subtype": "", "link_href": "",
             "link_title": "", "raw_payload": ""},
            {"document": "b.sy", "source_sha256": "b", "tree_position": "0",
             "block_id": "duplicate", "parent_block_id": "", "node_type": "NodeParagraph",
             "block_ref_id": "", "block_ref_subtype": "", "link_href": "",
             "link_title": "", "raw_payload": ""},
            {"document": "c.sy", "source_sha256": "c", "tree_position": "0.0",
             "block_id": "", "parent_block_id": "source", "node_type": "NodeTextMark",
             "block_ref_id": "duplicate", "block_ref_subtype": "d", "link_href": "",
             "link_title": "", "raw_payload": ""},
            {"document": "c.sy", "source_sha256": "c", "tree_position": "0.1",
             "block_id": "", "parent_block_id": "source", "node_type": "NodeTextMark",
             "block_ref_id": "missing", "block_ref_subtype": "d", "link_href": "",
             "link_title": "", "raw_payload": ""},
        ]
        edges = indexer.build_relationship_rows(rows)
        statuses = {edge["target"]: edge["resolution"] for edge in edges}
        self.assertEqual(statuses["duplicate"], "AMBIGUOUS_BLOCK_ID")
        self.assertEqual(statuses["missing"], "NOT_FOUND_IN_CORPUS")

    def test_builds_searchable_content_blocks_with_source_location(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            doc_dir = root / "book"
            doc_dir.mkdir(parents=True)
            (doc_dir / "doc.sy").write_text(json.dumps({
                "ID": "doc", "Type": "NodeDocument", "Children": [
                    {"ID": "h", "Type": "NodeHeading", "HeadingLevel": 1,
                     "Children": [{"ID": "ht", "Type": "NodeText", "Data": "经方"}]},
                    {"ID": "p", "Type": "NodeParagraph", "Children": [
                        {"ID": "t1", "Type": "NodeText", "Data": "桂枝汤"},
                        {"ID": "t2", "Type": "NodeText", "Data": "主治太阳中风"}
                    ]},
                    {"ID": "cell", "Type": "NodeTableCell", "Children": [
                        {"ID": "ct", "Type": "NodeText", "Data": "芍药"}
                    ]}
                ]
            }, ensure_ascii=False), encoding="utf-8")
            output = Path(temp) / "out"
            result = indexer.build(root, output)
            self.assertEqual(result["content_blocks"], 3)
            with gzip.open(output / "content_block_index.csv.gz", "rt",
                           encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            by_id = {row["block_id"]: row for row in rows}
            self.assertEqual(by_id["p"]["content_text"], "桂枝汤 主治太阳中风")
            self.assertEqual(by_id["p"]["content_type"], "PARAGRAPH")
            self.assertEqual(by_id["p"]["section_path"], "经方")
            self.assertEqual(by_id["cell"]["content_text"], "芍药")
            self.assertEqual(by_id["cell"]["content_type"], "TABLE_CELL")
            self.assertEqual(by_id["p"]["document"], "book/doc.sy")
            self.assertTrue(by_id["p"]["source_sha256"])

    def test_build_writes_document_node_and_unmapped_field_indexes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            doc_dir = root / "book"
            doc_dir.mkdir(parents=True)
            (doc_dir / "doc.sy").write_text(json.dumps({
                "ID": "doc", "Type": "NodeDocument", "Children": [
                    {"ID": "p", "Type": "NodeParagraph", "Children": [
                        {"ID": "t", "Type": "NodeText", "Data": "麻黄汤"}
                    ]}
                ]
            }, ensure_ascii=False), encoding="utf-8")
            output = Path(temp) / "out"
            result = indexer.build(root, output)
            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["parse_errors"], 0)
            with gzip.open(output / "node_semantic_index.csv.gz", "rt", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 3)
            self.assertEqual(next(row for row in rows if row["block_id"] == "t")["text"], "麻黄汤")
            with (output / "document_semantic_summary.csv").open(encoding="utf-8-sig", newline="") as stream:
                docs = list(csv.DictReader(stream))
            self.assertEqual(docs[0]["node_count"], "3")
            self.assertTrue((output / "node_semantic_index.md").is_file())
            self.assertTrue((output / "node_field_mapping.csv").is_file())
            self.assertTrue((output / "node_relationship_index.csv.gz").is_file())


if __name__ == "__main__":
    unittest.main()
