import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_relation_candidates import PREDICATES, extract, validate


class ContextualRelationCandidateTests(unittest.TestCase):
    def test_ambiguous_classical_markers_are_not_treatment_relation_predicates(self):
        marker = PREDICATES["SYNDROME_TO_TREATMENT"]
        self.assertIsNone(marker.search("法当腹满"))
        self.assertIsNone(marker.search("宜用救急稀涎散"))
        self.assertIsNotNone(marker.search("治宜温中健脾"))
        self.assertIsNotNone(marker.search("当以健脾为主"))

    def test_extracts_only_explicit_predicates_with_source_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "症见头痛，辨证为太阳中风，治宜解肌发表，方用桂枝汤。"
            terms = [
                ("symptom-1", "头痛", "SYMPTOM"),
                ("syndrome-1", "太阳中风", "SYNDROME"),
                ("treatment-1", "解肌发表", "TREATMENT"),
            ]
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
                for candidate_id, term, candidate_type in terms:
                    start = source_text.index(term)
                    writer.writerow({
                        "candidate_id": candidate_id, "term": term,
                        "candidate_type": candidate_type, "rule_id": candidate_type + "_RULE",
                        "evidence_document": "book/a.sy", "source_sha256": "sha-a",
                        "tree_position": "0.0", "block_id": "b1", "unit_id": "u1",
                        "character_start": start, "character_end": start + len(term),
                        "evidence_start": 0, "evidence_text": source_text,
                        "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
                start = source_text.index("桂枝汤")
                writer.writerow({
                    "mention_id": "formula-1", "unit_id": "u1", "entity_type": "FORMULA",
                    "matched_text": "桂枝汤", "character_start": start,
                    "character_end": start + 3, "document": "book/a.sy",
                    "source_sha256": "sha-a", "tree_position": "0.0", "block_id": "b1",
                })
            unit = {
                "unit_id": "u1",
                "source": {"document": "book/a.sy", "sha256": "sha-a",
                           "tree_position": "0.0", "block_id": "b1"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            result = extract(context, mentions, units, output)
            self.assertEqual(result["contextual_relation_candidates"], 3)
            self.assertEqual(validate(output, units), 3)
            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual({row["predicate"] for row in rows}, {
                "SYMPTOM_TO_SYNDROME", "SYNDROME_TO_TREATMENT", "TREATMENT_TO_FORMULA",
            })
            self.assertTrue(all(row["resolution_status"] == "UNRESOLVED_CANDIDATE" for row in rows))
            self.assertTrue(all(row["evidence_text"] == source_text for row in rows))

    def test_collapses_overlapping_ngrams_but_preserves_repeated_occurrence_spans(self):
        from build_contextual_relation_candidates import canonicalize_spans

        text = "症见头痛加剧明显，症见头痛，辨证为太阳中风。"
        first = text.index("头痛")
        second = text.rindex("头痛")
        spans = [
            (first, first + 2, {"candidate_id": "short-1", "candidate_type": "SYMPTOM", "term": "头痛"}),
            (first, first + 4, {"candidate_id": "long-1", "candidate_type": "SYMPTOM", "term": "头痛加剧"}),
            (first + 2, first + 6, {"candidate_id": "partial-1", "candidate_type": "SYMPTOM", "term": "加剧明显"}),
            (second, second + 2, {"candidate_id": "short-2", "candidate_type": "SYMPTOM", "term": "头痛"}),
        ]
        retained = canonicalize_spans(spans)
        self.assertEqual([(start, end) for start, end, _ in retained], [
            (first, first + 4), (first + 2, first + 6), (second, second + 2),
        ])
        self.assertEqual([row["term"] for _, _, row in retained], ["头痛加剧", "加剧明显", "头痛"])

    def test_rejects_negated_predicate_and_preserves_direction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "症见头痛，不宜辨证为太阳中风。"
            terms = [("s1", "头痛", "SYMPTOM"), ("z1", "太阳中风", "SYNDROME")]
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
                for cid, term, typ in terms:
                    start = source_text.index(term)
                    writer.writerow({
                        "candidate_id": cid, "term": term, "candidate_type": typ, "rule_id": "R1",
                        "evidence_document": "a.sy", "source_sha256": "sha", "tree_position": "0",
                        "block_id": "b", "unit_id": "u", "character_start": start,
                        "character_end": start + len(term), "evidence_start": 0,
                        "evidence_text": source_text, "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
            unit = {"unit_id": "u", "source": {"document": "a.sy", "sha256": "sha",
                    "tree_position": "0", "block_id": "b"},
                    "content": {"source_text": source_text}}
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            result = extract(context, mentions, units, output)
            self.assertEqual(result["contextual_relation_candidates"], 0)
            self.assertEqual(validate(output, units), 0)

    def test_does_not_infer_relation_from_cooccurrence_without_predicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "头痛，太阳中风，解肌发表。"
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
                for cid, term, typ in [("s1", "头痛", "SYMPTOM"), ("z1", "太阳中风", "SYNDROME")]:
                    start = source_text.index(term)
                    writer.writerow({
                        "candidate_id": cid, "term": term, "candidate_type": typ, "rule_id": "R1",
                        "evidence_document": "a.sy", "source_sha256": "sha", "tree_position": "0",
                        "block_id": "b", "unit_id": "u", "character_start": start,
                        "character_end": start + len(term), "evidence_start": 0,
                        "evidence_text": source_text, "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
            unit = {"unit_id": "u", "source": {"document": "a.sy", "sha256": "sha",
                    "tree_position": "0", "block_id": "b"},
                    "content": {"source_text": source_text}}
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            result = extract(context, mentions, units, output)
            self.assertEqual(result["contextual_relation_candidates"], 0)
            self.assertEqual(validate(output, units), 0)

    def test_does_not_link_prior_syndromes_to_later_attributed_treatment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = (
                "水肿有余者与不足者宜分别治之，然其源多由中气不足而起，"
                "丹溪曰：水病当以健脾为主。"
            )
            terms = [
                ("syndrome-1", "有余", "SYNDROME"),
                ("syndrome-2", "不足", "SYNDROME"),
                ("treatment-1", "健脾为主", "TREATMENT"),
            ]
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
                for cid, term, typ in terms:
                    start = source_text.index(term)
                    writer.writerow({
                        "candidate_id": cid, "term": term, "candidate_type": typ, "rule_id": "R1",
                        "evidence_document": "a.sy", "source_sha256": "sha", "tree_position": "0",
                        "block_id": "b", "unit_id": "u", "character_start": start,
                        "character_end": start + len(term), "evidence_start": 0,
                        "evidence_text": source_text, "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
            unit = {
                "unit_id": "u",
                "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")

            result = extract(context, mentions, units, output)
            self.assertEqual(result["contextual_relation_candidates"], 0)
            self.assertEqual(validate(output, units), 0)

    def test_treatment_to_formula_requires_explicit_between_endpoint_predicate(self):
        def extract_case(source_text, treatment_term, formula_terms):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                context = root / "context.csv.gz"
                mentions = root / "mentions.csv.gz"
                units = root / "units.jsonl.gz"
                output = root / "relations.csv"
                start = source_text.index(treatment_term)
                with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=[
                        "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                        "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                        "character_end", "evidence_start", "evidence_text", "classification_status",
                    ])
                    writer.writeheader()
                    writer.writerow({
                        "candidate_id": "treatment-1", "term": treatment_term,
                        "candidate_type": "TREATMENT", "rule_id": "R1",
                        "evidence_document": "a.sy", "source_sha256": "sha",
                        "tree_position": "0", "block_id": "b", "unit_id": "u",
                        "character_start": start, "character_end": start + len(treatment_term),
                        "evidence_start": 0, "evidence_text": source_text,
                        "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
                with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=[
                        "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                        "character_end", "document", "source_sha256", "tree_position", "block_id",
                    ])
                    writer.writeheader()
                    for index, formula in enumerate(formula_terms):
                        formula_start = source_text.index(formula)
                        writer.writerow({
                            "mention_id": f"formula-{index}", "unit_id": "u",
                            "entity_type": "FORMULA", "matched_text": formula,
                            "character_start": formula_start,
                            "character_end": formula_start + len(formula),
                            "document": "a.sy", "source_sha256": "sha",
                            "tree_position": "0", "block_id": "b",
                        })
                unit = {
                    "unit_id": "u",
                    "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                    "content": {"source_text": source_text},
                }
                with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                    stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
                result = extract(context, mentions, units, output)
                self.assertEqual(validate(output, units), result["contextual_relation_candidates"])
                with output.open(encoding="utf-8", newline="") as stream:
                    return list(csv.DictReader(stream))

        explicit = extract_case(
            "治法为温中健脾，方用桂枝汤。",
            "温中健脾",
            ["桂枝汤"],
        )
        self.assertEqual(len(explicit), 1)
        self.assertEqual(explicit[0]["predicate"], "TREATMENT_TO_FORMULA")
        self.assertEqual(explicit[0]["subject_text"], "温中健脾")
        self.assertEqual(explicit[0]["object_text"], "桂枝汤")
        self.assertEqual(explicit[0]["predicate_text"], "方用")

        cooccurrence_only = extract_case(
            "热盛者以咸寒，气坚者以咸软之，故仲景大陷胸汤、大承气汤。",
            "咸寒",
            ["大陷胸汤", "大承气汤"],
        )
        self.assertEqual(cooccurrence_only, [])

    def test_preserves_repeated_subject_mentions_as_distinct_relations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "症见头痛加剧，症见头痛，辨证为太阳中风。"
            symptom_starts = [i for i in range(len(source_text)) if source_text.startswith("头痛", i)]
            syndrome_start = source_text.index("太阳中风")
            rows = [
                ("symptom-short-1", "头痛", "SYMPTOM", symptom_starts[0]),
                ("symptom-long-1", "头痛加剧", "SYMPTOM", symptom_starts[0]),
                ("symptom-2", "头痛", "SYMPTOM", symptom_starts[1]),
                ("syndrome-1", "太阳中风", "SYNDROME", syndrome_start),
            ]
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
                for cid, term, typ, start in rows:
                    writer.writerow({
                        "candidate_id": cid, "term": term, "candidate_type": typ, "rule_id": "R1",
                        "evidence_document": "a.sy", "source_sha256": "sha", "tree_position": "0",
                        "block_id": "b", "unit_id": "u", "character_start": start,
                        "character_end": start + len(term), "evidence_start": 0,
                        "evidence_text": source_text, "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
            unit = {
                "unit_id": "u",
                "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")

            result = extract(context, mentions, units, output)
            self.assertEqual(result["contextual_relation_candidates"], 2)
            self.assertEqual(validate(output, units), 2)
            with output.open(encoding="utf-8", newline="") as stream:
                relations = list(csv.DictReader(stream))
            self.assertEqual(len({row["relation_id"] for row in relations}), 2)
            self.assertEqual(
                {int(row["subject_start"]) for row in relations},
                set(symptom_starts),
            )
            self.assertEqual(
                {row["subject_text"] for row in relations},
                {"头痛加剧", "头痛"},
            )


if __name__ == "__main__":
    unittest.main()
