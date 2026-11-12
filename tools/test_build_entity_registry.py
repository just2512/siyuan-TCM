import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_entity_registry.py")
SPEC = importlib.util.spec_from_file_location("build_entity_registry", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class EntityRegistryTests(unittest.TestCase):
    def test_builds_stable_distinct_lexical_ids_without_merging_alias_like_terms(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lexicon = root / "lexicon.csv"
            output = root / "registry.csv"
            with lexicon.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["entity_type", "term", "lexicon_version"])
                writer.writeheader()
                writer.writerows([
                    {"entity_type": "HERB", "term": "黄芪", "lexicon_version": "1.3.0"},
                    {"entity_type": "HERB", "term": "黄耆", "lexicon_version": "1.3.0"},
                    {"entity_type": "FORMULA", "term": "桂枝汤", "lexicon_version": "1.3.0"},
                ])
            result = module.build(lexicon, output)
            self.assertEqual(result, {"lexical_entities": 3, "unique_entity_ids": 3})
            self.assertEqual(module.validate(output, lexicon), 3)
            with output.open("r", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            by_term = {row["lexical_form"]: row for row in rows}
            self.assertNotEqual(by_term["黄芪"]["entity_id"], by_term["黄耆"]["entity_id"])
            self.assertEqual(by_term["黄芪"]["identity_status"], "LEXICAL_ID_ONLY")
            self.assertEqual(
                by_term["黄芪"]["entity_id"],
                module.stable_entity_id("HERB", "黄芪"),
            )

    def test_rejects_duplicate_lexicon_terms(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lexicon = root / "lexicon.csv"
            output = root / "registry.csv"
            with lexicon.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["entity_type", "term", "lexicon_version"])
                writer.writeheader()
                writer.writerows([
                    {"entity_type": "HERB", "term": "桂枝", "lexicon_version": "1.0"},
                    {"entity_type": "HERB", "term": "桂枝", "lexicon_version": "1.0"},
                ])
            with self.assertRaises(ValueError):
                module.build(lexicon, output)


if __name__ == "__main__":
    unittest.main()
