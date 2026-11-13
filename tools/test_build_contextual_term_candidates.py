import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_term_candidates import (
    FormulaSpanIndex, build, validate, classify_sample, classify_span, evidence_window,
)
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

    def test_intrinsic_clinical_cues_must_be_inside_the_candidate_span(self):
        # “咳嗽” belongs to the preceding clause, not the following n-gram.
        text = "咳嗽症状了，这是疾病在做最后挣扎阶段"
        start = text.index("这是疾病")
        self.assertNotIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_02"),
            classify_span(text, start, start + len("这是疾病")),
        )

        # Pulse/tongue cues also cannot be borrowed from adjacent text.
        text = "脉弦之后出现另一段叙述"
        start = text.index("之后")
        self.assertNotIn(
            ("PULSE", "PULSE_CONTEXT_01"),
            classify_span(text, start, start + len("之后")),
        )
        text = "舌红之后出现另一段叙述"
        start = text.index("之后")
        self.assertNotIn(
            ("TONGUE", "TONGUE_CONTEXT_01"),
            classify_span(text, start, start + len("之后")),
        )

    def test_intrinsic_clinical_cues_inside_candidate_remain_classifiable(self):
        self.assertIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_02"),
            classify_span("咳嗽", 0, 2),
        )
        self.assertIn(
            ("PULSE", "PULSE_CONTEXT_01"),
            classify_span("脉弦", 0, 2),
        )
        self.assertIn(
            ("TONGUE", "TONGUE_CONTEXT_01"),
            classify_span("舌红", 0, 2),
        )

    def test_discovers_source_grounded_acupoint_candidates_without_promoting_them_to_entities(self):
        positive = [
            "关元穴", "中脘穴", "血海穴", "风府穴", "中府穴", "云门穴", "百会穴",
        ]
        for term in positive:
            self.assertIn(
                ("ACUPOINT", "ACUPOINT_CONTEXT_01"),
                classify_span(term, 0, len(term)),
                term,
            )
        for term in ("穴位", "穴道", "穴名", "此穴", "该穴"):
            self.assertNotIn(
                ("ACUPOINT", "ACUPOINT_CONTEXT_01"),
                classify_span(term, 0, len(term)),
                term,
            )

    def test_discovers_explicit_acupuncture_technique_terms_and_rejects_negated_ones(self):
        positive = [
            "针灸", "针刺", "艾灸", "隔姜灸", "隔盐灸", "隔蒜灸",
            "米粒灸", "梅花灸", "十宣放血法", "放血", "透穴", "留针",
            "捻针", "运气法", "导引法", "补泻", "开四关",
        ]
        for term in positive:
            self.assertIn(
                ("ACUPUNCTURE_TECHNIQUE", "ACUPUNCTURE_TECHNIQUE_CONTEXT_01"),
                classify_span(term, 0, len(term)),
                term,
            )

        text = "热症不宜针灸"
        start = text.index("针灸")
        self.assertNotIn(
            ("ACUPUNCTURE_TECHNIQUE", "ACUPUNCTURE_TECHNIQUE_CONTEXT_01"),
            classify_span(text, start, start + len("针灸")),
        )

    def test_adds_common_pain_and_discomfort_terms_without_generalizing_to_all_words(self):
        for term in ("头痛", "痛经", "月经痛", "胃痛", "印堂痛", "气喘", "麻木不仁"):
            self.assertIn(
                ("SYMPTOM", "SYMPTOM_CONTEXT_02"),
                classify_span(term, 0, len(term)),
                term,
            )
        self.assertNotIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_02"),
            classify_span("心脏病", 0, len("心脏病")),
        )

    def test_validation_rejects_rule_from_another_candidate_type(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "typed.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id",
                    "evidence_document", "source_sha256", "tree_position", "block_id",
                    "unit_id", "character_start", "character_end", "evidence_start",
                    "evidence_text", "classification_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "candidate_id": candidate_id("少阳证"), "term": "少阳证",
                    "candidate_type": "SYNDROME", "rule_id": "PULSE_CONTEXT_01",
                    "evidence_document": "note.sy", "source_sha256": "sha",
                    "tree_position": "1", "block_id": "b1", "unit_id": "u1",
                    "character_start": 0, "character_end": 3, "evidence_start": 0,
                    "evidence_text": "少阳证", "classification_status": "CONTEXT_RULE_CANDIDATE",
                })
            with self.assertRaisesRegex(ValueError, "rule does not belong"):
                validate(path)

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

    def test_bare_treatment_label_requires_a_delimiter_before_its_value(self):
        text = "但是晚上这个治法的这个方子啊"
        start = text.index("的这个方子")
        self.assertNotIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, start, start + len("的这个方子")),
        )
        self.assertIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span("治法：温中健脾", 3, 7),
        )
        self.assertIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span("治法为温中健脾", 3, 7),
        )

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
        third_item = text.index("头昏")
        self.assertIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, third_item, third_item + len("头昏")),
        )

    def test_symptom_list_context_stops_at_non_symptom_narrative_clause(self):
        text = "初诊时症状是，眼多赤筋，呕心，头昏，西医认为是自体免疫系统不全。"
        false_term = "西医认为是"
        start = text.index(false_term)
        self.assertNotIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, start, start + len(false_term)),
        )

        text = "症状是四肢肌肉强直，足外翻，双手内屈，无法言语，赴大陆之前无法直立，经过治疗目前可以走路，可见大陆医师经验丰富。"
        false_term = "大陆医"
        start = text.index(false_term)
        self.assertNotIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, start, start + len(false_term)),
        )

        text = "可见大陆医师经验丰富。"
        start = text.index("大陆医")
        self.assertNotIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, start, start + len("大陆医")),
        )

    def test_does_not_classify_generic_bianzheng_as_a_syndrome_prefix(self):
        self.assertNotIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("辨证为主", 2, 4))
        self.assertIn(("SYNDROME", "SYNDROME_CONTEXT_01"), classify_span("辨证为太阳中风", 3, 7))

    def test_embedded_book_title_bianwei_does_not_type_following_phrase_as_syndrome(self):
        text = "处方依据是以温病条辨为主要依据"
        start = text.index("主要依据")
        self.assertNotIn(
            ("SYNDROME", "SYNDROME_CONTEXT_01"),
            classify_span(text, start, start + len("主要依据")),
        )
        self.assertIn(
            ("SYNDROME", "SYNDROME_CONTEXT_01"),
            classify_span("今乃辨为太阳中风", 4, 8),
        )

        text = "余意以为一气耳，今乃辨为六名，余不知其所以然。"
        start = text.index("六名")
        self.assertNotIn(
            ("SYNDROME", "SYNDROME_CONTEXT_01"),
            classify_span(text, start, start + len("六名")),
        )

    def test_symptom_list_intro_does_not_type_narrative_connectors_as_symptoms(self):
        for text, term in [
            ("尤其季节一变换，则许多人打喷嚏、流鼻水、鼻痒、流眼泪等症状相继出现", "相继"),
            ("同样是抽搐的症状，只是由于患者抽搐的频率和程度比先前严重", "只是由于"),
            ("同样是抽搐的症状，只是由于患者抽搐的频率和程度比先前严重", "只是由"),
        ]:
            start = text.index(term)
            self.assertNotIn(
                ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
                classify_span(text, start, start + len(term)),
            )

        text = "症状是头痛、恶心、呕吐"
        start = text.index("头痛")
        self.assertIn(
            ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
            classify_span(text, start, start + len("头痛")),
        )

    def test_does_not_classify_fadang_as_treatment_prefix(self):
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span("法当腹满", 2, 4))

    def test_yiyong_does_not_turn_a_formula_name_fragment_into_treatment(self):
        text = "此证风涎潮于上，膈痹气不通，宜用救急稀涎散。"
        start = text.index("救急")
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, start, start + 2))

    def test_ke_yong_is_not_a_treatment_but_following_method_remains_valid(self):
        text = "治法可用温中健脾"
        start = text.index("可用")
        self.assertNotIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, start, start + 2))

        text = "治法：温中健脾"
        start = text.index("温中健脾")
        self.assertIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, start, start + 4))

    def test_dangyi_remains_a_valid_treatment_prefix(self):
        text = "证属不足，当以健脾为主。"
        start = text.index("健脾")
        self.assertIn(("TREATMENT", "TREATMENT_CONTEXT_01"), classify_span(text, start, start + 2))

    def test_day_outcome_phrase_is_not_a_treatment_method(self):
        text = "病程当以十五日愈"
        start = text.index("十五日愈")
        self.assertNotIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, start, start + len("十五日愈")),
        )

        # The exception must not disable a genuine treatment instruction.
        text = "证属不足，当以健脾为主。"
        start = text.index("健脾")
        self.assertIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, start, start + len("健脾")),
        )


    def test_formula_span_index_matches_interval_overlap_semantics(self):
        # A long earlier interval still overlaps even when the immediately
        # preceding interval does not; the prefix maximum must preserve it.
        spans = [(0, 10), (5, 6), (12, 14)]
        index = FormulaSpanIndex(spans)
        self.assertTrue(index.overlaps(8, 9))
        self.assertTrue(index.overlaps(5, 6))
        self.assertFalse(index.overlaps(10, 12))
        self.assertFalse(index.overlaps(14, 15))

    def test_indexed_formula_overlap_preserves_treatment_exclusion(self):
        text = "当以附子汤温之，另当以温药下之。"
        formula_start = text.index("附子汤")
        spans = [(formula_start, formula_start + len("附子汤"))]
        indexed = FormulaSpanIndex(spans)
        candidate_start = text.index("附子汤温")
        candidate_end = candidate_start + len("附子汤温")
        self.assertEqual(
            classify_span(text, candidate_start, candidate_end, spans),
            classify_span(text, candidate_start, candidate_end, indexed),
        )
        self.assertNotIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, candidate_start, candidate_end, indexed),
        )
        valid_start = text.index("温药下之")
        self.assertIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, valid_start, valid_start + len("温药下之"), indexed),
        )

    def test_formula_mention_span_prevents_overlapping_treatment_retyping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "terms.csv.gz"
            units = root / "units.jsonl.gz"
            mentions = root / "mentions.csv.gz"
            output = root / "typed.csv.gz"
            text = "当以附子汤温之，另当以温药下之。"
            write_candidates(source, ["附子汤温", "温药下之"])
            write_units(units, text)
            formula_start = text.index("附子汤")
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "unit_id", "entity_type", "character_start", "character_end",
                ])
                writer.writeheader()
                writer.writerow({
                    "unit_id": "unit-1", "entity_type": "FORMULA",
                    "character_start": formula_start,
                    "character_end": formula_start + len("附子汤"),
                })

            result = build(source, output, units, mentions)
            self.assertGreater(result["contextual_classification_candidates"], 0)
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            treatment_terms = {
                row["term"] for row in rows if row["candidate_type"] == "TREATMENT"
            }
            self.assertNotIn("附子汤温", treatment_terms)
            self.assertIn("温药下之", treatment_terms)

    def test_raw_state_phrase_is_not_a_treatment_method(self):
        text = "此等药中不可用之，当以一生者为佳。"
        start = text.index("一生")
        self.assertNotIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, start, start + len("一生")),
        )

        # The scope exception must not suppress a genuine treatment method.
        text = "证属不足，当以健脾为主。"
        start = text.index("健脾")
        self.assertIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, start, start + len("健脾")),
        )

    def test_evidence_window_stops_at_sentence_and_author_attribution_boundaries(self):
        text = "前文。张仲景曰：症见头痛，后文。"
        start = text.index("头痛")
        end = start + len("头痛")
        left, right = evidence_window(text, start, end)
        evidence = text[left:right]
        self.assertEqual(evidence, "症见头痛，后文")
        self.assertNotIn("张仲景曰：", evidence)
        self.assertNotIn("。", evidence)

        next_author = "症见头痛。李时珍云：另有记载"
        start = next_author.index("头痛")
        left, right = evidence_window(next_author, start, start + 2)
        self.assertNotIn("李时珍云：", next_author[left:right])

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


    def test_rejects_lexical_compound_tails_as_formula_herb_or_syndrome(self):
        cases = [
            (
                "跟地黄有一点点用药的方向上的差别",
                "的方向上",
                "向上",
                None,
            ),
            (
                "养这个血，其实在用药的方式上是比较高明一点",
                "的方式上",
                "式上是",
                None,
            ),
            (
                "桂枝汤也是属于可以用的方剂之一哦",
                None,
                "剂之一",
                "可以用的方剂",
            ),
            (
                "底那一块，有一块地方用药是一样的",
                "是一样的",
                "药是一样",
                None,
            ),
        ]
        for text, herb_term, formula_term, syndrome_term in cases:
            if herb_term:
                start = text.index(herb_term)
                self.assertNotIn(
                    ("HERB", "HERB_CONTEXT_01"),
                    classify_span(text, start, start + len(herb_term)),
                    (text, herb_term),
                )
            if formula_term:
                start = text.index(formula_term)
                self.assertNotIn(
                    ("FORMULA", "FORMULA_CONTEXT_01"),
                    classify_span(text, start, start + len(formula_term)),
                    (text, formula_term),
                )
            if syndrome_term:
                start = text.index(syndrome_term)
                self.assertNotIn(
                    ("SYNDROME", "SYNDROME_CONTEXT_01"),
                    classify_span(text, start, start + len(syndrome_term)),
                    (text, syndrome_term),
                )

    def test_formula_and_herb_overlap_queue_grammar_fragments_are_not_entities(self):
        false_fragments = [
            ("偏方草药、不用非处方用药及不憋尿", "用药及", "FORMULA", "FORMULA_CONTEXT_01"),
            ("偏方草药、不用非处方用药及不憋尿", "及不憋尿", "HERB", "HERB_CONTEXT_01"),
            ("使用中药复方来替人治病", "复方来", "HERB", "HERB_CONTEXT_01"),
            ("使用中药复方来替人治病", "来替", "FORMULA", "FORMULA_CONTEXT_01"),
            ("服用中药偏方而导致肾衰竭", "偏方而", "HERB", "HERB_CONTEXT_01"),
            ("服用中药偏方而导致肾衰竭", "而导致", "FORMULA", "FORMULA_CONTEXT_01"),
        ]
        for text, term, candidate_type, rule_id in false_fragments:
            start = text.index(term)
            self.assertNotIn(
                (candidate_type, rule_id),
                classify_span(text, start, start + len(term)),
                (text, term),
            )

        self.assertIn(
            ("FORMULA", "FORMULA_CONTEXT_01"),
            classify_span("方用桂枝汤", 2, 5),
        )
        self.assertIn(
            ("HERB", "HERB_CONTEXT_01"),
            classify_span("药用桂枝", 2, 4),
        )

    def test_symptom_and_pulse_candidates_do_not_absorb_neighboring_clauses(self):
        for text, term in [
            ("如果这个人是发热而脉沉", "这个人是发热"),
            ("如果这个人是发热而脉沉", "个人是发热"),
            ("如果这个人是发热而脉沉", "发热而"),
            ("如果这个人是发热而脉沉", "发热而脉沉"),
        ]:
            start = text.index(term)
            self.assertNotIn(
                ("SYMPTOM", "SYMPTOM_CONTEXT_02"),
                classify_span(text, start, start + len(term)),
                (text, term),
            )

        for term in ("发热而脉沉", "热而脉沉", "而脉沉"):
            text = f"如果这个人是{term}"
            start = text.index(term)
            self.assertNotIn(
                ("PULSE", "PULSE_CONTEXT_01"),
                classify_span(text, start, start + len(term)),
                (text, term),
            )

    def test_symptom_and_pulse_lexical_spans_remain_classifiable(self):
        for term in ("发热", "骨节疼痛", "反复咳嗽"):
            self.assertIn(
                ("SYMPTOM", "SYMPTOM_CONTEXT_02"),
                classify_span(term, 0, len(term)),
                term,
            )
        for term in ("脉沉", "脉沉细", "脉浮数"):
            self.assertIn(
                ("PULSE", "PULSE_CONTEXT_01"),
                classify_span(term, 0, len(term)),
                term,
            )

    def test_rejects_pulse_prefixes_with_discourse_suffixes(self):
        for term in ("脉象虽然", "脉象怎么", "脉浮的", "脉浮就", "脉浮紧而"):
            self.assertNotIn(
                ("PULSE", "PULSE_CONTEXT_01"),
                classify_span(term, 0, len(term)),
                term,
            )
        for term in ("脉象", "脉沉细", "脉浮数", "脉弦紧"):
            self.assertIn(
                ("PULSE", "PULSE_CONTEXT_01"),
                classify_span(term, 0, len(term)),
                term,
            )

    def test_symptom_list_context_does_not_retype_pulse_or_tongue_terms(self):
        text = "症状是怕冷，表证啊，怕冷是他有表证，脉象虽然不符的话"
        for term in ("脉象", "脉象虽然"):
            start = text.index(term)
            self.assertNotIn(
                ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
                classify_span(text, start, start + len(term)),
                (text, term),
            )

    def test_rejects_formula_or_herb_labels_on_ordinary_discourse_tails(self):
        cases = [
            ("汤这个药方，如果是用时方的本草的观点去解释它的话", "的本草的", "FORMULA"),
            ("汤这个药方，如果是用时方的本草的观点去解释它的话", "的观点", "HERB"),
            ("如果用药证相对论的话，就好像咳这个主证", "证相对", "HERB"),
        ]
        for text, term, candidate_type in cases:
            start = text.index(term)
            rule_id = "FORMULA_CONTEXT_01" if candidate_type == "FORMULA" else "HERB_CONTEXT_01"
            self.assertNotIn(
                (candidate_type, rule_id),
                classify_span(text, start, start + len(term)),
                (text, term),
            )


    def test_rejects_remaining_source_grounded_contextual_overlap_false_positives(self):
        symptom_cases = [
            ("症状，那人容易累，那至于说舌苔或者脉象到是没有什么明显", "那至于说"),
            ("然后咳嗽，然后呢，你看他舌苔，你如果平常有时候", "你看他"),
            ("的症状的时候，就是潮热、脉滑、吃不下饭", "脉滑"),
            ("到了承气汤证型症状都到了另外一边去了", "症状都"),
            ("虚满的症状当以温药，温的药，像胀满的时候", "当以温药"),
        ]
        for text, term in symptom_cases:
            start = text.index(term)
            self.assertNotIn(
                ("SYMPTOM", "SYMPTOM_CONTEXT_01"),
                classify_span(text, start, start + len(term)),
                (text, term),
            )

        ordinary_phrases = [
            ("因为经方用药有些药用的轻的没有像傅青主那", "药有些", {"FORMULA", "HERB"}),
            ("大概就是以经方用药来讲", "药来讲", {"FORMULA", "HERB"}),
            ("中药处方就是这样来的", "处方就", {"FORMULA", "HERB"}),
            ("中药处方就是这样来的", "就是这样", {"FORMULA", "HERB"}),
            ("中药处方就是这样来的", "就是这样", {"FORMULA", "HERB"}),
            ("可以用药方让阴阳和", "方让", {"FORMULA", "HERB"}),
            ("药，这一味本草使用的地方非常的多", "使用的地方非", {"FORMULA", "HERB"}),
            ("用药后疼痛减轻，炎症很快吸收或局限", "后疼痛减轻", {"HERB"}),
            ("生病或误用药导致呕吐不止，可用半夏止吐", "导致呕吐", {"HERB"}),
            ("药用治胀痛，破血而补", "治胀痛", {"HERB"}),
            ("经过我用经方治疗咳嗽时，是喝第一剂药就好转了", "治疗咳嗽", {"FORMULA"}),
        ]
        for text, term, rejected_types in ordinary_phrases:
            start = text.index(term)
            classified = {kind for kind, _ in classify_span(text, start, start + len(term))}
            self.assertTrue(rejected_types.isdisjoint(classified), (text, term, classified))

    def test_contextual_overlap_queue_grammar_fragments_are_not_entities(self):
        false_fragments = [
            ("我们把张仲景讲的症状或者脉象做成一个问卷", "或者脉", "SYMPTOM", "SYMPTOM_CONTEXT_01"),
            ("声，张口抬肩的症状，它的脉象怎样", "它的脉", "SYMPTOM", "SYMPTOM_CONTEXT_01"),
            ("匮要略》中形容它的症状为脉沉、腹满而不喘", "为脉", "SYMPTOM", "SYMPTOM_CONTEXT_01"),
            ("是说，到了承气汤证型症状都到了另外一边去了", "症状都", "SYNDROME", "SYNDROME_CONTEXT_01"),
            ("是说，到了承气汤证型症状都到了另外一边去了", "都到", "SYMPTOM", "SYMPTOM_CONTEXT_01"),
            ("肺，病的名字叫做厥，属于不能治的死症", "属于不", "SYMPTOM", "SYMPTOM_CONTEXT_01"),
            ("肺，病的名字叫做厥，属于不能治的死症", "不能治", "SYNDROME", "SYNDROME_CONTEXT_01"),
            ("有的表现为麻木不仁，证候表现千变万化", "证候表", "SYMPTOM", "SYMPTOM_CONTEXT_01"),
            ("有的表现为麻木不仁，证候表现千变万化", "表现", "SYNDROME", "SYNDROME_CONTEXT_01"),
            ("在表，也不单纯在里，属于表里同病", "属于表", "SYMPTOM", "SYMPTOM_CONTEXT_01"),
            ("痿肿痈，属于风寒咳嗽，短气鼻塞", "风寒咳", "SYNDROME", "SYNDROME_CONTEXT_01"),
        ]
        for text, term, candidate_type, rule_id in false_fragments:
            start = text.index(term)
            self.assertNotIn(
                (candidate_type, rule_id),
                classify_span(text, start, start + len(term)),
                (text, term),
            )

        valid_terms = [
            ("我们把张仲景讲的症状或者脉象做成一个问卷", "脉象", "PULSE", "PULSE_CONTEXT_01"),
            ("在表，也不单纯在里，属于表里同病", "表里同", "SYNDROME", "SYNDROME_CONTEXT_01"),
            ("痿肿痈，属于风寒咳嗽，短气鼻塞", "风寒咳嗽", "SYNDROME", "SYNDROME_CONTEXT_01"),
        ]
        for text, term, candidate_type, rule_id in valid_terms:
            start = text.index(term)
            self.assertIn(
                (candidate_type, rule_id),
                classify_span(text, start, start + len(term)),
                (text, term),
            )

    def test_negative_syndrome_cue_and_diagnostic_observation_are_not_entities(self):
        text = "噢，第一条是排除掉不属于呕吐的状况的条文"
        start = text.index("呕吐的状")
        self.assertNotIn(
            ("SYNDROME", "SYNDROME_CONTEXT_01"),
            classify_span(text, start, start + len("呕吐的状")),
        )
        text = "光的脸颊一样，就它是属于发热充血的状态的"
        start = text.index("发热充血")
        self.assertNotIn(
            ("SYNDROME", "SYNDROME_CONTEXT_01"),
            classify_span(text, start, start + len("发热充血")),
        )

        text = "应当以经脉为纲领，所有的经脉都是这样"
        start = text.index("经脉为")
        self.assertNotIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, start, start + len("经脉为")),
        )
        self.assertNotIn(
            ("PULSE", "PULSE_CONTEXT_01"),
            classify_span(text, start + 1, start + len("经脉为")),
        )
        text = "此当以舌苔之既自与黄腻辨之，而所泻"
        start = text.index("当以舌苔")
        self.assertNotIn(
            ("TREATMENT", "TREATMENT_CONTEXT_01"),
            classify_span(text, start, start + len("当以舌苔之")),
        )

if __name__ == "__main__":
    unittest.main()
