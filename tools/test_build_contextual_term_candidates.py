import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_term_candidates import build, validate, classify_sample, classify_span
from build_unclassified_term_candidates import candidate_id


def write_candidates(path: Path, terms: list[str]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "candidate_id", "term", "candidate_status"
        ])
        writer.writeheader()
        for term in terms:
            writer.writerow({
                "candidate_id": candidate_id(term),
                "term": term,
                "candidate_status": "UNCLASSIFIED_TERM_CANDIDATE",
            })


def write_units(path: Path, text: str) -> None:
    unit = {
        "unit_id": "unit-1",
        "source": {
            "document": "note.sy",
            "sha256": "sha-1",
            "tree_position": "1.2",
            "block_id": "block-1",
        },
        "content": {"source_text": text},
    }
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        stream.write(json.dumps(unit, ensure_ascii=False) + "\n")


class ContextualTermCandidateTests(unittest.TestCase):
    def test_classifies_every_source_occurrence_not_only_saved_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "terms.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "typed.csv.gz"
            text = "症见头痛，平素无不适。另见症见头痛，伴有恶心。"
            write_candidates(source, ["头痛", "恶心"])
            write_units(units, text)

            result = build(source, output, units)
            self.assertEqual(result["source_units_scanned"], 1)
            self.assertEqual(result["candidate_terms_loaded"], 2)
            self.assertEqual(result["distinct_terms_classified"], 2)
            self.assertGreaterEqual(result["contextual_classification_candidates"], 3)
            self.assertEqual(validate(output), result["contextual_classification_candidates"])

            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            headache_rows = [row for row in rows if row["term"] == "头痛"]
            self.assertEqual(len(headache_rows), 2)
            self.assertEqual(
                {int(row["character_start"]) for row in headache_rows},
                {text.index("头痛"), text.rindex("头痛")},
            )
            self.assertTrue(all(row["classification_status"] == "CONTEXT_RULE_CANDIDATE" for row in rows))
            self.assertTrue(all(row["evidence_document"] == "note.sy" for row in rows))

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
        self.assertEqual(classify_sample(sample), [("PULSE", "PULSE_CONTEXT_01")])

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
        self.assertEqual(classify_sample(symptom_context), [("SYMPTOM", "SYMPTOM_CONTEXT_01")])
        self.assertEqual(classify_sample(syndrome_context), [("SYNDROME", "SYNDROME_CONTEXT_01")])

    def test_does_not_classify_the_context_cue_itself_as_a_syndrome(self):
        self.assertNotIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("证属不足", 0, 4))
        self.assertIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("辨证属少阳证", 3, 6))

    def test_treatment_and_formula_cues_must_precede_candidate_span(self):
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span("治法", 0, 2))
        self.assertIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span("治法为温中健脾", 3, 7))
        self.assertNotIn(("FORMULA", "FORMULA_CONTEXT_01"), classify_span("方用", 0, 2))
        self.assertIn(("FORMULA", "FORMULA_CONTEXT_01"), classify_span("方用桂枝汤", 2, 5))

    def test_prefix_cues_do_not_type_unrelated_later_terms_in_same_clause(self):
        text = "治法：喷粉法-洗净患者肠内容物"
        self.assertIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, 3, 5))
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, 7, 9))

    def test_prefix_cue_may_be_separated_from_candidate_by_small_punctuation(self):
        text = "治法：温中健脾"
        self.assertIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, 3, 7))

    def test_recognizes_relation_predicate_prefix_forms_for_typed_endpoints(self):
        self.assertIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("辨证为太阳中风", 3, 7))
        self.assertIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("辨为太阳中风", 2, 6))
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span("宜用解肌发表", 2, 6))
        self.assertIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span("当以温中健脾", 2, 6))

    def test_symptom_label_is_not_itself_a_symptom_and_list_items_keep_context(self):
        text = "初诊时症状是，眼多赤筋，呕心，头昏。"
        cue_start = text.index("症状")
        self.assertNotIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, cue_start, cue_start + len("症状")),
        )
        self.assertNotIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, cue_start - 1, cue_start + len("症状")),
        )
        first_item = text.index("眼多赤筋")
        self.assertIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, first_item, first_item + len("眼多赤筋")),
        )
        second_item = text.index("呕心")
        self.assertIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, second_item, second_item + len("呕心")),
        )

    def test_does_not_classify_generic_bianzheng_as_a_syndrome_prefix(self):
        self.assertNotIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("辨证为主", 2, 4))
        self.assertIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("辨证为太阳中风", 3, 7))

    def test_does_not_classify_fadang_as_treatment_prefix(self):
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span("法当腹满", 2, 4))

    def test_yiyong_does_not_turn_a_formula_name_fragment_into_treatment(self):
        text = "此证风涎潮于上，膈痹气不通，宜用救急稀涎散。"
        start = text.index("救急")
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, start, start + 2))

    def test_dangyi_remains_a_valid_treatment_prefix(self):
        text = "证属不足，当以健脾为主。"
        start = text.index("健脾")
        self.assertIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, start, start + 2))

    def test_rejects_invalid_candidate_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "terms.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "typed.csv.gz"
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_status"
                ])
                writer.writeheader()
                writer.writerow({
                    "candidate_id": "wrong-id", "term": "头痛",
                    "candidate_status": "UNCLASSIFIED_TERM_CANDIDATE",
                })
            write_units(units, "症见头痛")
            with self.assertRaisesRegex(ValueError, "invalid candidate identity"):
                build(source, output, units)


if __name__ == "__main__":
    unittest.main()
