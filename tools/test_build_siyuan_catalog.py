import csv
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
                catalog.resolve_asset_reference(r"assets\nested-a\same.png", root, lookup)[0],
                "FOUND",
            )
            self.assertEqual(
                catalog.resolve_asset_reference(r"..\assets\..\..\outside.txt", root, lookup)[0],
                "INVALID_REFERENCE",
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
            self.assertEqual(
                catalog.resolve_asset_reference("../../assets/unique.jpg", root, lookup)[0],
                "INVALID_REFERENCE",
            )
            self.assertEqual(
                catalog.resolve_asset_reference("../assets/../../outside.txt", root, lookup)[0],
                "INVALID_REFERENCE",
            )

    def test_builds_document_topic_and_asset_indexes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            doc_dir = root / "notebook-a"
            doc_dir.mkdir(parents=True)
            (doc_dir / "doc.sy").write_text(json.dumps({
                "Properties": {"title": "神农本草经", "author": "测试作者", "publisher": ""},
                "Children": [{"Type": "NodeText", "Data": "本草药性 " + ("普通内容" * 600) + "针灸 assets/herb.png"}],
            }, ensure_ascii=False), encoding="utf-8")
            output = Path(temp) / "out"
            result = catalog.build(root, output, None, {"notebook-a": "本草资料"})
            self.assertEqual(result["documents"], 1)
            self.assertFalse(result["asset_scan_performed"])
            self.assertEqual(result["asset_prefix_candidates"], 0)
            self.assertTrue((output / "documents.csv").is_file())
            self.assertTrue((output / "topic_index.csv").is_file())
            self.assertTrue((output / "asset_references.csv").is_file())
            self.assertIn("NOT_CHECKED", (output / "asset_references.csv").read_text(encoding="utf-8-sig"))
            asset_audit = (output / "asset_audit.md").read_text(encoding="utf-8")
            self.assertIn("候选扫描状态：NOT_RUN", asset_audit)
            self.assertIn("未匹配引用唯一项：未执行本地映射，不能统计", asset_audit)
            csv_text = (output / "documents.csv").read_text(encoding="utf-8-sig")
            self.assertIn("本草资料", csv_text)
            self.assertIn("title_source", csv_text)
            self.assertIn("PROPERTY", csv_text)
            self.assertIn("node_types", csv_text)
            self.assertIn("NodeText:1", csv_text)
            self.assertIn("properties_fields", csv_text)
            self.assertIn("topic_matched_terms", csv_text)
            self.assertIn("针灸与经穴:针灸", csv_text)
            self.assertIn("title_topic_matched_terms", csv_text)
            self.assertIn("body_topic_matched_terms", csv_text)
            self.assertIn("经典与理论:神农本草经", csv_text)
            self.assertIn("针灸与经穴:针灸", csv_text)
            self.assertIn("author;title", csv_text)
            metadata_text = (output / "metadata_inventory.csv").read_text(encoding="utf-8-sig")
            self.assertIn("author,1", metadata_text)
            self.assertIn("title,1", metadata_text)
            self.assertNotIn("测试作者", metadata_text)


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


    def test_generated_reports_and_asset_rows_do_not_leak_local_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private-data-root"
            doc_dir = root / "notebook-a"
            doc_dir.mkdir(parents=True)
            (doc_dir / "doc.sy").write_text(json.dumps({
                "Properties": {"title": "路径隐私测试"},
                "Children": [{
                    "Type": "NodeParagraph",
                    "Data": "assets/private-image.png",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            assets = root / "assets"
            assets.mkdir()
            (assets / "private-image.png").write_bytes(b"image")
            output = Path(temp) / "generated"

            catalog.build(root, output, assets, {})

            report = (output / "catalog.md").read_text(encoding="utf-8")
            self.assertNotIn(str(root), report)
            self.assertNotIn(str(assets), report)
            with (output / "asset_references.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["local_status"], "FOUND")
            self.assertEqual(rows[0]["local_path"], "assets/private-image.png")
            self.assertNotIn(str(root), rows[0]["local_path"])


    def test_builds_non_committal_asset_prefix_candidates_from_local_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "data"
            doc_dir = root / "notebook-a"
            doc_dir.mkdir(parents=True)
            (doc_dir / "doc.sy").write_text(json.dumps({
                "Properties": {"title": "附件候选测试"},
                "Children": [{
                    "Type": "NodeParagraph",
                    "Data": "assets/single assets/multi assets/none assets/missing.png",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            assets = Path(temp) / "assets"
            assets.mkdir()
            (assets / "single-20260101-a.jpg").write_bytes(b"a")
            (assets / "multi-20260101-a.jpg").write_bytes(b"b")
            (assets / "multi-20260102-b.jpg").write_bytes(b"c")
            (assets / "unrelated.jpg").write_bytes(b"d")
            output = Path(temp) / "generated"

            result = catalog.build(root, output, assets, {})
            self.assertTrue(result["asset_scan_performed"])
            self.assertEqual(result["asset_prefix_candidates"], 4)

            with (output / "asset_prefix_candidates.csv").open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            by_ref = {row["reference"]: row for row in rows}
            self.assertEqual(by_ref["assets/single"]["candidate_status"], "ONE_CANDIDATE")
            self.assertEqual(by_ref["assets/single"]["candidate_count"], "1")
            self.assertEqual(
                by_ref["assets/multi"]["candidate_status"], "MULTIPLE_CANDIDATES"
            )
            self.assertEqual(by_ref["assets/none"]["candidate_status"], "NO_CANDIDATE")
            self.assertEqual(
                by_ref["assets/missing.png"]["candidate_status"], "NO_CANDIDATE"
            )
            self.assertEqual(
                by_ref["assets/single"]["candidate_paths"],
                "assets/single-20260101-a.jpg",
            )
            self.assertNotIn(str(temp), (output / "asset_prefix_candidates.csv").read_text(
                encoding="utf-8-sig"
            ))
            audit = (output / "asset_audit.md").read_text(encoding="utf-8")
            self.assertIn("未匹配引用唯一项：4", audit)
            self.assertIn("文件名候选唯一命中：1", audit)
            self.assertIn("文件名候选多重命中：1", audit)
            self.assertIn("文件名无候选：2", audit)
            catalog_report = (output / "catalog.md").read_text(encoding="utf-8")
            self.assertIn("asset_prefix_candidates.csv", catalog_report)

    def test_asset_lookup_and_candidates_exclude_symlinks_outside_assets_root(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            assets = base / "assets"
            assets.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (outside / "escape-20260101.jpg").write_bytes(b"outside")
            try:
                (assets / "escape-20260101.jpg").symlink_to(
                    outside / "escape-20260101.jpg"
                )
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this platform")
            exact, by_name = catalog.build_asset_lookup(assets)
            self.assertEqual(exact, {})
            self.assertEqual(dict(by_name), {})
            candidates = catalog.build_asset_prefix_candidates(
                [{
                    "reference": "assets/escape",
                    "local_status": "MISSING",
                    "document": "notebook/doc.sy",
                    "title": "外部符号链接测试",
                }],
                assets,
                (exact, by_name),
            )
            self.assertEqual(candidates[0]["candidate_status"], "NO_CANDIDATE")
            self.assertEqual(candidates[0]["candidate_paths"], "")


    def test_derives_nested_document_parent_and_child_counts(self):
        docs = [
            {"path": "book/parent.sy"},
            {"path": "book/parent/child.sy"},
            {"path": "book/parent/child/grandchild.sy"},
            {"path": "book/other.sy"},
        ]
        catalog.attach_document_hierarchy(docs)
        by_path = {row["path"]: row for row in docs}
        self.assertEqual(by_path["book/parent.sy"]["parent_document"], "")
        self.assertEqual(by_path["book/parent.sy"]["document_depth"], 0)
        self.assertEqual(by_path["book/parent.sy"]["child_document_count"], 1)
        self.assertEqual(by_path["book/parent/child.sy"]["parent_document"], "book/parent.sy")
        self.assertEqual(by_path["book/parent/child.sy"]["document_depth"], 1)
        self.assertEqual(by_path["book/parent/child.sy"]["child_document_count"], 1)
        self.assertEqual(by_path["book/parent/child/grandchild.sy"]["parent_document"], "book/parent/child.sy")
        self.assertEqual(by_path["book/parent/child/grandchild.sy"]["document_depth"], 2)
        self.assertEqual(by_path["book/other.sy"]["parent_document"], "")
        self.assertEqual(by_path["book/other.sy"]["child_document_count"], 0)


if __name__ == "__main__":
    unittest.main()
