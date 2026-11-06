import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_term_candidates import build, validate


class ContextualTermCandidateTests(unittest.TestCase):
    def test_builds_typed_candidates_with_source_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "terms.csv.gz"
            output = root / "typed.csv.gz"
            sample = {
                "unit_id": "unit-1", "document": "note.sy", "source_sha256": "abc",
                "tree_position": "1.2", "block_id": "b1", "character_start": 2,
                "character_end": 4, "evidence_start": 0,
                "matched_text": "头痛", "evidence_text": "症见头痛，舌红苔黄",
            }
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "sample_evidence", "candidate_status"
                ])
                writer.writeheader()
                writer.writerow({
                    "candidate_id": "term-1", "term": "头痛",
                    "sample_evidence": json.dumps([sample], ensure_ascii=False),
                    "candidate_status": "UNCLASSIFIED_TERM_CANDIDATE",
                })
            result = build(source, output)
            self.assertGreaterEqual(result["contextual_classification_candidates"], 1)
            self.assertEqual(validate(output), result["contextual_classification_candidates"])
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertIn("SYMPTOM", {row["candidate_type"] for row in rows})
            self.assertTrue(all(row["classification_status"] == "CONTEXT_RULE_CANDIDATE" for row in rows))

    def test_rejects_wrong_input_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "terms.csv.gz"
            output = root / "typed.csv.gz"
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "sample_evidence", "candidate_status"
                ])
                writer.writeheader()
                writer.writerow({
                    "candidate_id": "term-1", "term": "头痛",
                    "sample_evidence": "[]", "candidate_status": "CONFIRMED",
                })
            with self.assertRaisesRegex(ValueError, "non-unclassified"):
                build(source, output)


if __name__ == "__main__":
    unittest.main()
