import csv
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_formula_herb_relation_candidates.py")
SPEC = importlib.util.spec_from_file_location("build_formula_herb_relation_candidates", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class FormulaHerbRelationCandidateTests(unittest.TestCase):
    def test_requires_ingredient_phrase_and_supports_reverse_composition_order(self):
        formula = {"character_start": "7", "character_end": "10"}
        herbs = [
            {"character_start": "0", "character_end": "2", "matched_text": "桂枝"},
            {"character_start": "3", "character_end": "5", "matched_text": "芍药"},
        ]
        reverse = "桂枝、芍药组成桂枝汤"
        selected = module.explicit_composition(formula, herbs, reverse, 0)
        self.assertEqual([item["matched_text"] for item in selected], ["桂枝", "芍药"])

        misleading = "真武汤在少阴篇会有包含小便不利，而我们通常是麻黄发汗之后"
        distant_formula = {"character_start": "0", "character_end": "3"}
        distant_herb = {
            "character_start": str(misleading.index("麻黄")),
            "character_end": str(misleading.index("麻黄") + 2),
            "matched_text": "麻黄",
        }
        self.assertEqual(
            module.explicit_composition(distant_formula, [distant_herb], misleading, 0),
            [],
        )

    def test_nearby_formula_requires_an_explicit_formula_anchor(self):
        evidence_unit = {
            "unit_id": "composition",
            "source": {"tree_position": "0.0"},
        }
        incidental = {
            "mention_id": "incidental-m", "unit_id": "context", "tree_position": "0.2",
            "character_start": "0", "character_end": "3",
            "matched_text": "真武汤", "_source_text": "真武汤在少阴篇会有包含小便不利",
            "_unit_type": "SOURCE_PARAGRAPH",
        }
        self.assertIsNone(module.nearby_formula([incidental], evidence_unit))

        explicit = {
            "mention_id": "explicit-m", "unit_id": "indication", "tree_position": "0.2",
            "character_start": "9", "character_end": "12",
            "matched_text": "黄土汤", "_source_text": "【15.6】下血，黄土汤主之",
            "_unit_type": "SOURCE_PARAGRAPH",
        }
        self.assertEqual(module.nearby_formula([explicit], evidence_unit), explicit)

    def test_secondary_main_indication_is_explicit_but_two_formulas_are_ambiguous(self):
        evidence_unit = {
            "unit_id": "composition",
            "source": {"tree_position": "0.0"},
        }
        text = "柏叶汤主之；黄土汤亦主之"
        baiye = {
            "mention_id": "baiye", "unit_id": "indication", "tree_position": "0.2",
            "character_start": "0", "character_end": "3",
            "matched_text": "柏叶汤", "_source_text": text,
            "_unit_type": "SOURCE_PARAGRAPH",
        }
        huangtu = {
            "mention_id": "huangtu", "unit_id": "indication", "tree_position": "0.2",
            "character_start": "6", "character_end": "9",
            "matched_text": "黄土汤", "_source_text": text,
            "_unit_type": "SOURCE_PARAGRAPH",
        }
        self.assertTrue(module.has_explicit_formula_context(baiye))
        self.assertTrue(module.has_explicit_formula_context(huangtu))
        self.assertIsNone(module.nearby_formula([baiye, huangtu], evidence_unit))
        # Ingredient-name overlap with a formula title cannot disambiguate
        # equally near formula anchors; the candidate must remain unlinked.
        self.assertIsNone(module.nearby_formula([baiye, huangtu], evidence_unit))

        incidental = {
            "mention_id": "white-tiger", "unit_id": "context", "tree_position": "0.2",
            "character_start": "0", "character_end": "3",
            "matched_text": "白虎汤", "_source_text": "白虎汤证对不对",
            "_unit_type": "SOURCE_PARAGRAPH",
        }
        self.assertFalse(module.has_explicit_formula_context(incidental))

    def test_rejects_formula_suffixes_embedded_in_longer_formula_names(self):
        cases = [
            ("乌头桂枝汤主之", "桂枝汤"),
            ("人参附子汤主之", "附子汤"),
            ("厚朴四物汤主之", "四物汤"),
            ("桂枝芍药知母甘草汤主之", "甘草汤"),
        ]
        for text, term in cases:
            with self.subTest(text=text, term=term):
                start = text.index(term)
                mention = {
                    "character_start": str(start),
                    "character_end": str(start + len(term)),
                    "matched_text": term,
                    "_source_text": text,
                    "_unit_type": "SOURCE_PARAGRAPH",
                }
                self.assertFalse(module.has_explicit_formula_context(mention))

    def test_accepts_formula_name_after_a_grammatical_introducer(self):
        for text in ("用桂枝汤主之", "宜桂枝汤主之", "服用桂枝汤主之"):
            with self.subTest(text=text):
                start = text.index("桂枝汤")
                mention = {
                    "character_start": str(start),
                    "character_end": str(start + len("桂枝汤")),
                    "matched_text": "桂枝汤",
                    "_source_text": text,
                    "_unit_type": "SOURCE_PARAGRAPH",
                }
                self.assertTrue(module.has_explicit_formula_context(mention))

    def test_links_composition_list_to_unique_nearby_formula_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            mentions = root / "mentions.csv.gz"
            output = root / "relations.csv"
            source_hash = "b" * 64
            unit_rows = [
                {
                    "unit_id": "composition",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "book/a.sy", "sha256": source_hash,
                               "tree_position": "0.0", "block_id": "b1"},
                    "content": {"source_text": "组成：桂枝、芍药"},
                },
                {
                    "unit_id": "formula",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "book/a.sy", "sha256": source_hash,
                               "tree_position": "0.2", "block_id": "b2"},
                    "content": {"source_text": "桂枝汤主之"},
                },
                {
                    "unit_id": "formula-alt",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "book/a.sy", "sha256": source_hash,
                               "tree_position": "0.3", "block_id": "b3"},
                    "content": {"source_text": "桂枝汤主之"},
                },
            ]
            with gzip.open(units, "wt", encoding="utf-8") as stream:
                for unit in unit_rows:
                    stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id", "content_type", "section_path",
                "lexicon_version", "extraction_method", "resolution_status",
            ]
            rows = [
                ("formula-m", "formula", "FORMULA", "桂枝汤", 0, 3, "0.2", "b2"),
                ("formula-alt", "formula-alt", "FORMULA", "桂枝汤", 0, 3, "0.3", "b3"),
                ("herb-1", "composition", "HERB", "桂枝", 3, 5, "0.0", "b1"),
                ("herb-2", "composition", "HERB", "芍药", 6, 8, "0.0", "b1"),
            ]
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, unit_id, kind, term, start, end, position, block_id in rows:
                    writer.writerow({
                        "mention_id": mid, "unit_id": unit_id, "entity_type": kind,
                        "matched_text": term, "character_start": start, "character_end": end,
                        "document": "book/a.sy", "source_sha256": source_hash,
                        "tree_position": position, "block_id": block_id,
                        "content_type": "PARAGRAPH", "section_path": "",
                        "lexicon_version": "1.0.0", "extraction_method": "EXACT_LEXICON_MATCH",
                        "resolution_status": "UNRESOLVED_CANDIDATE",
                    })
            result = module.extract(mentions, units, output)
            self.assertEqual(result["relation_candidates"], 2)
            self.assertEqual(module.validate(output, units, mentions), 2)
            with output.open("r", encoding="utf-8", newline="") as stream:
                found = list(csv.DictReader(stream))
            self.assertTrue(all(row["subject_mention_id"] == "formula-m" for row in found))

            # A relation may not point to a fabricated candidate ID even when
            # its text and character offsets happen to match the source.
            fabricated = root / "fabricated-relations.csv"
            fabricated_rows = [dict(row) for row in found]
            fabricated_rows[0]["subject_mention_id"] = "fabricated-formula-id"
            with fabricated.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=module.FIELDS)
                writer.writeheader()
                writer.writerows(fabricated_rows)
            with self.assertRaisesRegex(ValueError, "relation mention reference not found"):
                module.validate(fabricated, units, mentions)

            # A different, real formula candidate with identical text and a
            # valid nearby source block is still not the candidate referenced
            # by the original relation identity.
            swapped = root / "swapped-real-candidate.csv"
            swapped_rows = [dict(row) for row in found]
            swapped_rows[0]["subject_mention_id"] = "formula-alt"
            with swapped.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=module.FIELDS)
                writer.writeheader()
                writer.writerows(swapped_rows)
            with self.assertRaisesRegex(ValueError, "relation ID does not match referenced source candidate IDs"):
                module.validate(swapped, units, mentions)

            self.assertTrue(all(row["unit_id"] == "composition" for row in found))
            self.assertTrue(all(row["extraction_rule"] == "FORMULA_COMPOSITION_NEARBY_BLOCK_V1" for row in found))
            with gzip.open(mentions, "rt", encoding="utf-8", newline="") as stream:
                corrupted = list(csv.DictReader(stream))
            corrupted[2]["source_sha256"] = "c" * 64
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(corrupted)
            with self.assertRaisesRegex(ValueError, "object mention provenance mismatch"):
                module.validate(output, units, mentions)
            corrupted[2]["source_sha256"] = source_hash
            corrupted[0]["document"] = "book/other.sy"
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(corrupted)
            with self.assertRaisesRegex(ValueError, "subject mention provenance mismatch"):
                module.validate(output, units, mentions)

    def test_nearby_composition_block_is_split_into_sentence_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            mentions = root / "mentions.csv.gz"
            output = root / "relations.csv"
            source_hash = "d" * 64
            composition_text = "组成：桂枝、芍药。此方用于调和营卫。"
            unit_rows = [
                {
                    "unit_id": "composition",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "book/multi.sy", "sha256": source_hash,
                               "tree_position": "0.0", "block_id": "c1"},
                    "content": {"source_text": composition_text},
                },
                {
                    "unit_id": "formula",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "book/multi.sy", "sha256": source_hash,
                               "tree_position": "0.1", "block_id": "c2"},
                    "content": {"source_text": "桂枝汤主之"},
                },
            ]
            with gzip.open(units, "wt", encoding="utf-8") as stream:
                for unit in unit_rows:
                    stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id", "content_type", "section_path",
                "lexicon_version", "extraction_method", "resolution_status",
            ]
            rows = [
                ("formula-m", "formula", "FORMULA", "桂枝汤", 0, 3, "0.1", "c2"),
                ("herb-1", "composition", "HERB", "桂枝", 3, 5, "0.0", "c1"),
                ("herb-2", "composition", "HERB", "芍药", 6, 8, "0.0", "c1"),
            ]
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, unit_id, kind, term, start, end, position, block_id in rows:
                    writer.writerow({
                        "mention_id": mid, "unit_id": unit_id, "entity_type": kind,
                        "matched_text": term, "character_start": start, "character_end": end,
                        "document": "book/multi.sy", "source_sha256": source_hash,
                        "tree_position": position, "block_id": block_id,
                        "content_type": "PARAGRAPH", "section_path": "",
                        "lexicon_version": "1.0.0", "extraction_method": "EXACT_LEXICON_MATCH",
                        "resolution_status": "UNRESOLVED_CANDIDATE",
                    })
            self.assertEqual(module.extract(mentions, units, output)["relation_candidates"], 2)
            self.assertEqual(module.validate(output, units, mentions), 2)
            with output.open("r", encoding="utf-8", newline="") as stream:
                found = list(csv.DictReader(stream))
            expected_evidence = "组成：桂枝、芍药。"
            self.assertTrue(all(row["evidence_text"] == expected_evidence for row in found))
            self.assertTrue(all(int(row["sentence_start"]) == 0 for row in found))
            self.assertTrue(all(int(row["sentence_end"]) == len(expected_evidence) for row in found))
            self.assertTrue(all("此方用于调和营卫" not in row["evidence_text"] for row in found))

    def test_extracts_only_explicit_composition_with_traceable_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            mentions = root / "mentions.csv.gz"
            output = root / "relations.csv"
            text = "桂枝汤由桂枝、芍药组成。另有麻黄汤。"
            unit = {
                "unit_id": "u1",
                "unit_type": "SOURCE_PARAGRAPH",
                "source": {"document": "a.sy", "sha256": "a" * 64,
                           "tree_position": "0.1", "block_id": "b1"},
                "content": {"source_text": text},
            }
            with gzip.open(units, "wt", encoding="utf-8") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id", "content_type", "section_path",
                "lexicon_version", "extraction_method", "resolution_status",
            ]
            rows = [
                ("f1", "FORMULA", "桂枝汤", 0, 3),
                ("h1", "HERB", "桂枝", 4, 6),
                ("h2", "HERB", "芍药", 7, 9),
                ("f2", "FORMULA", "麻黄汤", 14, 17),
            ]
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, kind, term, start, end in rows:
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u1", "entity_type": kind,
                        "matched_text": term, "character_start": start, "character_end": end,
                        "document": "a.sy", "source_sha256": "a" * 64,
                        "tree_position": "0.1", "block_id": "b1",
                        "content_type": "PARAGRAPH", "section_path": "经方",
                        "lexicon_version": "1.0.0", "extraction_method": "EXACT_LEXICON_MATCH",
                        "resolution_status": "UNRESOLVED_CANDIDATE",
                    })
            result = module.extract(mentions, units, output)
            self.assertEqual(result["relation_candidates"], 2)
            self.assertEqual(module.validate(output, units, mentions), 2)
            with output.open("r", encoding="utf-8", newline="") as stream:
                found = list(csv.DictReader(stream))
            self.assertEqual([row["object_text"] for row in found], ["桂枝", "芍药"])
            self.assertTrue(all(row["evidence_text"] == "桂枝汤由桂枝、芍药组成。" for row in found))
            self.assertTrue(all(row["resolution_status"] == "UNRESOLVED_CANDIDATE" for row in found))



    def test_fullwidth_period_splits_formula_herb_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            mentions = root / "mentions.csv.gz"
            output = root / "relations.csv"
            text = "桂枝汤由桂枝组成．麻黄汤由麻黄组成"
            source_hash = "e" * 64
            unit = {
                "unit_id": "u1",
                "unit_type": "SOURCE_PARAGRAPH",
                "source": {"document": "a.sy", "sha256": source_hash,
                           "tree_position": "0.0", "block_id": "b1"},
                "content": {"source_text": text},
            }
            with gzip.open(units, "wt", encoding="utf-8") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id", "content_type", "section_path",
                "lexicon_version", "extraction_method", "resolution_status",
            ]
            rows = [
                ("f1", "FORMULA", "桂枝汤", 0, 3),
                ("h1", "HERB", "桂枝", 4, 6),
                ("f2", "FORMULA", "麻黄汤", 9, 12),
                ("h2", "HERB", "麻黄", 13, 15),
            ]
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, kind, term, start, end in rows:
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u1", "entity_type": kind,
                        "matched_text": term, "character_start": start, "character_end": end,
                        "document": "a.sy", "source_sha256": source_hash,
                        "tree_position": "0.0", "block_id": "b1",
                        "content_type": "PARAGRAPH", "section_path": "",
                        "lexicon_version": "1.0.0", "extraction_method": "EXACT_LEXICON_MATCH",
                        "resolution_status": "UNRESOLVED_CANDIDATE",
                    })
            result = module.extract(mentions, units, output)
            self.assertEqual(result["relation_candidates"], 2)
            self.assertEqual(module.validate(output, units, mentions), 2)
            with output.open("r", encoding="utf-8", newline="") as stream:
                found = list(csv.DictReader(stream))
            self.assertEqual(
                [row["evidence_text"] for row in found],
                ["桂枝汤由桂枝组成．", "麻黄汤由麻黄组成"],
            )

    def test_author_attribution_boundary_recognizes_yun_and_named_books(self):
        formula = {
            "mention_id": "formula-m", "unit_id": "formula",
            "matched_text": "桂枝汤", "character_start": "0", "character_end": "3",
        }
        herb = {
            "mention_id": "herb-m", "unit_id": "composition",
            "matched_text": "桂枝", "character_start": "3", "character_end": "5",
        }
        for marker in ("张三曰：", "某氏云：", "《伤寒论》曰∶", "《金匮要略》云："):
            with self.subTest(marker=marker):
                units = {
                    "formula": {
                        "unit_id": "formula",
                        "source": {"document": "a.sy", "sha256": "hash", "tree_position": "0.0", "block_id": "b0"},
                        "content": {"source_text": "桂枝汤"},
                    },
                    "attribution": {
                        "unit_id": "attribution",
                        "source": {"document": "a.sy", "sha256": "hash", "tree_position": "0.1", "block_id": "b1"},
                        "content": {"source_text": marker},
                    },
                    "composition": {
                        "unit_id": "composition",
                        "source": {"document": "a.sy", "sha256": "hash", "tree_position": "0.2", "block_id": "b2"},
                        "content": {"source_text": "组成：桂枝"},
                    },
                }
                self.assertTrue(
                    module.crosses_author_attribution_boundary(formula, herb, units)
                )



    def test_sibling_unit_index_is_revision_scoped_and_matches_direct_boundary_check(self):
        formula = {
            "mention_id": "formula-m", "unit_id": "formula",
            "matched_text": "桂枝汤", "character_start": "0", "character_end": "3",
        }
        herb = {
            "mention_id": "herb-m", "unit_id": "composition",
            "matched_text": "桂枝", "character_start": "3", "character_end": "5",
        }
        units = {
            "formula": {
                "unit_id": "formula",
                "source": {"document": "a.sy", "sha256": "rev-a", "tree_position": "0.0", "block_id": "b0"},
                "content": {"source_text": "桂枝汤"},
            },
            "attribution": {
                "unit_id": "attribution",
                "source": {"document": "a.sy", "sha256": "rev-a", "tree_position": "0.1", "block_id": "b1"},
                "content": {"source_text": "张三曰："},
            },
            "composition": {
                "unit_id": "composition",
                "source": {"document": "a.sy", "sha256": "rev-a", "tree_position": "0.2", "block_id": "b2"},
                "content": {"source_text": "组成：桂枝"},
            },
            "unrelated-revision": {
                "unit_id": "unrelated-revision",
                "source": {"document": "a.sy", "sha256": "rev-b", "tree_position": "0.1", "block_id": "old-b1"},
                "content": {"source_text": "无关修订版本"},
            },
            "unrelated-document": {
                "unit_id": "unrelated-document",
                "source": {"document": "b.sy", "sha256": "rev-a", "tree_position": "0.1", "block_id": "other-b1"},
                "content": {"source_text": "无关文档"},
            },
        }
        index = module.build_sibling_unit_index(units)
        self.assertTrue(module.crosses_author_attribution_boundary(formula, herb, units))
        self.assertTrue(module.crosses_author_attribution_boundary(formula, herb, units, index))

        # Removing the same-revision attribution sibling must allow the
        # unrelated revision/document rows to remain irrelevant.
        del units["attribution"]
        index = module.build_sibling_unit_index(units)
        self.assertFalse(module.crosses_author_attribution_boundary(formula, herb, units, index))

    def test_nearby_formula_relation_cannot_cross_author_attribution_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            mentions = root / "mentions.csv.gz"
            output = root / "relations.csv"
            source_hash = "f" * 64
            unit_rows = [
                {
                    "unit_id": "formula",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "a.sy", "sha256": source_hash,
                               "tree_position": "0.0", "block_id": "b0"},
                    "content": {"source_text": "桂枝汤主之"},
                },
                {
                    "unit_id": "attribution",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "a.sy", "sha256": source_hash,
                               "tree_position": "0.1", "block_id": "b1"},
                    "content": {"source_text": "丹溪曰："},
                },
                {
                    "unit_id": "composition",
                    "unit_type": "SOURCE_PARAGRAPH",
                    "source": {"document": "a.sy", "sha256": source_hash,
                               "tree_position": "0.2", "block_id": "b2"},
                    "content": {"source_text": "组成：桂枝"},
                },
            ]
            with gzip.open(units, "wt", encoding="utf-8") as stream:
                for unit in unit_rows:
                    stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id", "content_type", "section_path",
                "lexicon_version", "extraction_method", "resolution_status",
            ]
            mention_rows = [
                ("formula-m", "formula", "FORMULA", "桂枝汤", 0, 3, "0.0", "b0"),
                ("herb-m", "composition", "HERB", "桂枝", 3, 5, "0.2", "b2"),
            ]
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, unit_id, kind, term, start, end, position, block_id in mention_rows:
                    writer.writerow({
                        "mention_id": mid, "unit_id": unit_id, "entity_type": kind,
                        "matched_text": term, "character_start": start, "character_end": end,
                        "document": "a.sy", "source_sha256": source_hash,
                        "tree_position": position, "block_id": block_id,
                        "content_type": "PARAGRAPH", "section_path": "",
                        "lexicon_version": "1.0.0", "extraction_method": "EXACT_LEXICON_MATCH",
                        "resolution_status": "UNRESOLVED_CANDIDATE",
                    })

            self.assertEqual(module.extract(mentions, units, output)["relation_candidates"], 0)
            self.assertEqual(module.validate(output, units, mentions), 0)

            formula = {
                "mention_id": "formula-m", "unit_id": "formula",
                "matched_text": "桂枝汤", "character_start": "0", "character_end": "3",
            }
            herb = {
                "mention_id": "herb-m", "unit_id": "composition",
                "matched_text": "桂枝", "character_start": "3", "character_end": "5",
            }
            evidence_unit = unit_rows[2]
            with output.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=module.FIELDS)
                writer.writeheader()
                module.make_relation(
                    writer, set(), formula, herb, evidence_unit, 0, 5,
                    "组成：桂枝", "FORMULA_COMPOSITION_NEARBY_BLOCK_V1",
                )
            with self.assertRaisesRegex(ValueError, "author-attribution boundary"):
                module.validate(output, units, mentions)


if __name__ == "__main__":
    unittest.main()
