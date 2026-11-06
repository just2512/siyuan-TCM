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
    def test_extracts_only_explicit_composition_with_traceable_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            mentions = root / "mentions.csv.gz"
            output = root / "relations.csv"
            text = "桂枝汤由桂枝、芍药组成。另有麻黄汤。"
            unit = {
                "unit_id": "u1",
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


if __name__ == "__main__":
    unittest.main()
