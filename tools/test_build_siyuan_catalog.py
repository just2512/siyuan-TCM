import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_siyuan_catalog.py")
SPEC = importlib.util.spec_from_file_location("build_siyuan_catalog", MODULE_PATH)
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class CatalogueBuilderTests(unittest.TestCase):
    def test_extracts_title_and_nested_text_from_siyuan_json(self):
        payload = {
            "Properties": {"title": "伤寒论·太阳病"},
            "Children": [
                {"Type": "NodeParagraph", "Children": [
                    {"Type": "NodeText", "Data": "太阳病，脉浮，头项强痛"}
                ]}
            ],
        }
        self.assertEqual(catalog.extract_title(payload, "fallback"), "伤寒论·太阳病")
        self.assertIn("太阳病，脉浮，头项强痛", catalog.extract_text(payload))

    def test_uses_first_visible_line_when_document_title_is_generic_and_ignores_ial(self):
        payload = {
            "Properties": {"title": "笔记"},
            "Children": [
                {"Type": "NodeParagraph", "Children": [
                    {"Type": "NodeTextMark", "TextMarkTextContent": "小柴胡汤证"},
                    {"Type": "NodeKramdownSpanIAL", "Data": "{: style=color-red}"}
                ]}
            ],
        }
        self.assertEqual(catalog.extract_title(payload, "fallback"), "小柴胡汤证")
        self.assertEqual(catalog.extract_title_with_source(payload, "fallback"), ("小柴胡汤证", "BODY_FIRST_LINE"))
        self.assertEqual(catalog.extract_text(payload), "小柴胡汤证")

    def test_counts_child_node_types_without_metadata_nodes(self):
        payload = {
            "Properties": {"title": "空文档"},
            "Children": [
                {"Type": "NodeParagraph", "Properties": {"id": "p1"}},
                {"Type": "NodeParagraph", "Properties": {"id": "p2"}},
            ],
        }
        self.assertEqual(catalog.collect_child_node_types(payload), {"NodeParagraph": 2})

    def test_extracts_asset_paths_without_eating_trailing_punctuation(self):
        raw = '![图](assets/herb.png) and ../assets/pulse.jpg，'
        refs = sorted({m.rstrip(catalog.TRAILING) for m in catalog.ASSET_RE.findall(raw)})
        self.assertEqual(refs, ["../assets/pulse.jpg", "assets/herb.png"])

    def test_resolves_assets_exactly_and_marks_ambiguous_basenames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "assets"
            (root / "nested-a").mkdir(parents=True)
            (root / "nested-b").mkdir(parents=True)
            (root / "nested-a" / "same.png").write_bytes(b"a")
            (root / "nested-b" / "same.png").write_bytes(b"b")
            (root / "unique.jpg").write_bytes(b"c")
            lookup = catalog.build_asset_lookup(root)
            self.assertEqual(
                catalog.resolve_asset_reference("assets/nested-a/same.png", root, lookup)[0],
                "FOUND",
            )
            self.assertEqual(
                catalog.resolve_asset_reference("../assets/same.png", root, lookup)[0],
                "AMBIGUOUS",
            )
            self.assertEqual(
                catalog.resolve_asset_reference("assets/unique.jpg", root, lookup)[0],
                "FOUND",
            )
            self.assertEqual(
                catalog.resolve_asset_reference("../assets/../../outside.txt", root, lookup)[0],
                "INVALID_REFERENCE",
            )
            self.assertEqual(
                catalog.resolve_asset_reference(r"..\\assets\\..\\..\\outside.txt", root, lookup)[0],
                "INVALID_REFERENCE",
            )

    def test_builds_document_topic_and_asset_indexes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            doc_dir = root / "notebook-a"
            doc_dir.mkdir(parents=True)
            (doc_dir / "doc.sy").write_text(json.dumps({
                "Properties": {"title": "神农本草经"},
                "Children": [{"Type": "NodeText", "Data": "本草药性 assets/herb.png"}],
            }, ensure_ascii=False), encoding="utf-8")
            output = Path(temp) / "out"
            result = catalog.build(root, output, None, {"notebook-a": "本草资料"})
            self.assertEqual(result["documents"], 1)
            self.assertTrue((output / "documents.csv").is_file())
            self.assertTrue((output / "topic_index.csv").is_file())
            self.assertTrue((output / "asset_references.csv").is_file())
            self.assertIn("NOT_CHECKED", (output / "asset_references.csv").read_text(encoding="utf-8-sig"))
            csv_text = (output / "documents.csv").read_text(encoding="utf-8-sig")
            self.assertIn("本草资料", csv_text)
            self.assertIn("title_source", csv_text)
            self.assertIn("PROPERTY", csv_text)
            self.assertIn("node_types", csv_text)
            self.assertIn("NodeText:1", csv_text)


    def test_build_uses_safe_asset_resolver_for_generated_reference_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            doc_dir = root / "notebook-a"
            doc_dir.mkdir(parents=True)
            (doc_dir / "doc.sy").write_text(json.dumps({
                "Properties": {"title": "附件映射验证"},
                "Children": [{
                    "Type": "NodeParagraph",
                    "Data": "assets/nested-a/same.png ../assets/same.png assets/unique.jpg",
                }],
            }, ensure_ascii=False), encoding="utf-8")

            assets = Path(temp) / "assets"
            (assets / "nested-a").mkdir(parents=True)
            (assets / "nested-b").mkdir(parents=True)
            (assets / "nested-a" / "same.png").write_bytes(b"a")
            (assets / "nested-b" / "same.png").write_bytes(b"b")
            (assets / "unique.jpg").write_bytes(b"c")

            output = Path(temp) / "out"
            catalog.build(root, output, assets, {})
            import csv
            with (output / "asset_references.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))

            by_reference = {row["reference"]: row for row in rows}
            self.assertEqual(by_reference["assets/nested-a/same.png"]["local_status"], "FOUND")
            self.assertEqual(
                by_reference["assets/nested-a/same.png"]["match_method"],
                "EXACT_RELATIVE_PATH",
            )
            self.assertEqual(by_reference["../assets/same.png"]["local_status"], "AMBIGUOUS")
            self.assertEqual(
                by_reference["../assets/same.png"]["match_method"],
                "DUPLICATE_BASENAME",
            )
            self.assertEqual(by_reference["assets/unique.jpg"]["local_status"], "FOUND")
            self.assertEqual(
                by_reference["assets/unique.jpg"]["match_method"],
                "EXACT_RELATIVE_PATH",
            )


if __name__ == "__main__":
    unittest.main()
