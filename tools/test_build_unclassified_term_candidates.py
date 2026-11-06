import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_unclassified_term_candidates.py")
SPEC = importlib.util.spec_from_file_location("build_unclassified_term_candidates", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class UnclassifiedTermCandidateTests(unittest.TestCase):
    def test_mines_repeated_terms_with_traceable_spans(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            records = [
                {"unit_id": "u1", "source": {"document": "a.sy", "sha256": "a" * 64, "tree_position": "0.1", "block_id": "b1"},
                 "content": {"source_text": "太阳中风，桂枝汤主之。"}},
                {"unit_id": "u2", "source": {"document": "b.sy", "sha256": "b" * 64, "tree_position": "0.2", "block_id": "b2"},
                 "content": {"source_text": "太阳中风，桂枝汤证。"}},
                {"unit_id": "u3", "source": {"document": "c.sy", "sha256": "c" * 64, "tree_position": "0.3", "block_id": "b3"},
                 "content": {"source_text": "太阳中风，桂枝汤加减。"}},
            ]
            with gzip.open(source, "wt", encoding="utf-8") as stream:
                for record in records:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            result = module.mine(source, output, min_occurrences=3, min_documents=2)
            self.assertEqual(result["knowledge_units_scanned"], 3)
            self.assertGreater(result["unclassified_term_candidates"], 0)
            self.assertEqual(module.validate(output), result["unclassified_term_candidates"])
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                rows = list(__import__("csv").DictReader(stream))
            row = next(item for item in rows if item["term"] == "太阳中风")
            self.assertEqual(row["candidate_status"], "UNCLASSIFIED_TERM_CANDIDATE")
            samples = json.loads(row["sample_evidence"])
            self.assertIn("太阳中风", samples[0]["evidence_text"])

    def test_ignores_terms_seen_in_only_one_document(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            records = [
                {"unit_id": "u1", "source": {"document": "a.sy"}, "content": {"source_text": "罕见证候罕见证候罕见证候"}},
            ]
            with gzip.open(source, "wt", encoding="utf-8") as stream:
                for record in records:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            result = module.mine(source, output, min_occurrences=2, min_documents=2)
            self.assertEqual(result["unclassified_term_candidates"], 0)
            self.assertEqual(module.validate(output), 0)


if __name__ == "__main__":
    unittest.main()
