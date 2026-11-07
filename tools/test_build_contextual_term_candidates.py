import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_term_candidates import build, validate, classify_sample


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

    def test_does_not_borrow_tongue_context_from_adjacent_symptom(self):
        sample = {
            "unit_id": "unit-2", "document": "note.sy", "source_sha256": "abc",
            "tree_position": "1.3", "block_id": "b2", "character_start": 2,
            "character_end": 4, "evidence_start": 0,
            "matched_text": "头痛", "evidence_text": "症见头痛，舌红苔黄",
        }
        found = classify_sample(sample)
        self.assertIn(("SYMPTOM", "SYMPTOM_CONTEXT_01"), found)
        self.assertNotIn(("TONGUE", "TONGUE_CONTEXT_01"), found)

    def test_classifies_overlapping_types_only_when_each_cue_targets_candidate(self):
        symptom = {
            "unit_id": "unit-3", "document": "note.sy", "source_sha256": "abc",
            "tree_position": "1.4", "block_id": "b3", "character_start": 2,
            "character_end": 4, "evidence_start": 0,
            "matched_text": "头痛", "evidence_text": "症见头痛",
        }
        syndrome = {
            "unit_id": "unit-4", "document": "note.sy", "source_sha256": "abc",
            "tree_position": "1.5", "block_id": "b4", "character_start": 3,
            "character_end": 6, "evidence_start": 0,
            "matched_text": "少阳证", "evidence_text": "辨证属少阳证",
        }
        self.assertIn(("SYMPTOM", "SYMPTOM_CONTEXT_01"), classify_sample(symptom))
        self.assertIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_sample(syndrome))
        self.assertNotIn(("SYMPTOM", "SYMPTOM_CONTEXT_01"), classify_sample(syndrome))

    def test_punctuation_boundary_prevents_borrowing_context_from_previous_clause(self):
        sample = {
            "unit_id": "unit-5", "document": "note.sy", "source_sha256": "abc",
            "tree_position": "1.6", "block_id": "b5", "character_start": 5,
            "character_end": 7, "evidence_start": 0,
            "matched_text": "脉弦", "evidence_text": "舌红苔黄，脉弦",
        }
        self.assertEqual(
            classify_sample(sample),
            [("PULSE", "PULSE_CONTEXT_01")],
        )

    def test_same_lexical_candidate_can_keep_distinct_evidence_backed_labels(self):
        symptom_context = {
            "unit_id": "unit-6", "document": "note.sy", "source_sha256": "abc",
            "tree_position": "1.7", "block_id": "b6", "character_start": 2,
            "character_end": 5, "evidence_start": 0,
            "matched_text": "少阳证", "evidence_text": "症见少阳证",
        }
        syndrome_context = {
            "unit_id": "unit-7", "document": "note.sy", "source_sha256": "abc",
            "tree_position": "1.8", "block_id": "b7", "character_start": 2,
            "character_end": 5, "evidence_start": 0,
            "matched_text": "少阳证", "evidence_text": "证属少阳证",
        }
        self.assertEqual(
            classify_sample(symptom_context),
            [("SYMPTOM", "SYMPTOM_CONTEXT_01")],
        )
        self.assertEqual(
            classify_sample(syndrome_context),
            [("SYNDROME", "SYNDROME_CONTEXT_01")],
        )

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
