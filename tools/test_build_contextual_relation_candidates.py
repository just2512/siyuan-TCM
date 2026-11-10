import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_relation_candidates import FIELDS, PREDICATES, extract, relation_identity, sentence_ranges, validate


class ContextualRelationCandidateTests(unittest.TestCase):
    def test_sentence_ranges_split_fullwidth_period_without_losing_offsets(self):
        source_text = "甲方。乙方．丙方！丁方"
        ranges = list(sentence_ranges(source_text))
        self.assertEqual([source_text[start:end] for start, end in ranges], ["甲方。", "乙方．", "丙方！", "丁方"])
        self.assertEqual([(start, end) for start, end in ranges], [(0, 3), (3, 6), (6, 9), (9, 11)])

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

    def test_rejects_negated_unusable_formula_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "温中健脾不可用桂枝汤。"
            term = "温中健脾"
            start = source_text.index(term)
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "candidate_id": "treatment-1", "term": term,
                    "candidate_type": "TREATMENT", "rule_id": "TREATMENT_RULE",
                    "evidence_document": "a.sy", "source_sha256": "sha",
                    "tree_position": "0", "block_id": "b", "unit_id": "u",
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
                formula_start = source_text.index("桂枝汤")
                writer.writerow({
                    "mention_id": "formula-1", "unit_id": "u", "entity_type": "FORMULA",
                    "matched_text": "桂枝汤", "character_start": formula_start,
                    "character_end": formula_start + len("桂枝汤"), "document": "a.sy",
                    "source_sha256": "sha", "tree_position": "0", "block_id": "b",
                })
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

    def test_extraction_rejects_author_attribution_crossings_for_all_predicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "头痛，张三曰：辨证为太阳中风。解表，张三曰：方用桂枝汤。"
            terms = [
                ("symptom-1", "头痛", "SYMPTOM"),
                ("syndrome-1", "太阳中风", "SYNDROME"),
                ("treatment-1", "解表", "TREATMENT"),
            ]
            context_fields = [
                "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                "character_end", "evidence_start", "evidence_text", "classification_status",
            ]
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=context_fields)
                writer.writeheader()
                for candidate_id, term, candidate_type in terms:
                    start = source_text.index(term)
                    writer.writerow({
                        "candidate_id": candidate_id, "term": term, "candidate_type": candidate_type,
                        "rule_id": "R1", "evidence_document": "a.sy", "source_sha256": "sha",
                        "tree_position": "0", "block_id": "b", "unit_id": "u",
                        "character_start": start, "character_end": start + len(term),
                        "evidence_start": 0, "evidence_text": source_text,
                        "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
            mention_fields = [
                "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                "character_end", "document", "source_sha256", "tree_position", "block_id",
            ]
            formula_start = source_text.index("桂枝汤")
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=mention_fields)
                writer.writeheader()
                writer.writerow({
                    "mention_id": "formula-1", "unit_id": "u", "entity_type": "FORMULA",
                    "matched_text": "桂枝汤", "character_start": formula_start,
                    "character_end": formula_start + len("桂枝汤"), "document": "a.sy",
                    "source_sha256": "sha", "tree_position": "0", "block_id": "b",
                })
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

    def test_does_not_link_prior_syndromes_to_later_attributed_treatment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = (
                "水肿有余者与不足者宜分别治之，然其源多由中气不足而起，"
                "丹溪曰∶水病当以健脾为主。"
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
                # Term-level candidate IDs legitimately repeat at distinct spans.
                ("term-headache", "头痛", "SYMPTOM", symptom_starts[0]),
                ("symptom-long-1", "头痛加剧", "SYMPTOM", symptom_starts[0]),
                ("term-headache", "头痛", "SYMPTOM", symptom_starts[1]),
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
            self.assertEqual(validate(output, units, context, mentions), 2)
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


    def test_canonicalize_spans_preserves_nested_named_formulas(self):
        from build_contextual_relation_candidates import canonicalize_spans

        spans = [
            (0, 10, {"candidate_id": "modified", "candidate_type": "FORMULA", "term": "加味芍药甘草汤"}),
            (2, 8, {"candidate_id": "base", "candidate_type": "FORMULA", "term": "芍药甘草汤"}),
        ]
        retained = canonicalize_spans(spans)
        self.assertEqual(
            [(start, end, row["candidate_id"]) for start, end, row in retained],
            [(0, 10, "modified"), (2, 8, "base")],
        )

    def test_validator_rejects_unknown_endpoint_candidate_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "头痛，辨证为太阳中风。"
            symptom_start = source_text.index("头痛")
            syndrome_start = source_text.index("太阳中风")
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id",
                    "character_start", "character_end", "classification_status",
                ])
                writer.writeheader()
                writer.writerows([
                    {"candidate_id": "symptom-real", "term": "头痛", "candidate_type": "SYMPTOM",
                     "evidence_document": "a.sy", "source_sha256": "sha", "tree_position": "0",
                     "block_id": "b", "unit_id": "u", "character_start": symptom_start,
                     "character_end": symptom_start + 2, "classification_status": "CONTEXT_RULE_CANDIDATE"},
                    {"candidate_id": "syndrome-real", "term": "太阳中风", "candidate_type": "SYNDROME",
                     "evidence_document": "a.sy", "source_sha256": "sha", "tree_position": "0",
                     "block_id": "b", "unit_id": "u", "character_start": syndrome_start,
                     "character_end": syndrome_start + 4, "classification_status": "CONTEXT_RULE_CANDIDATE"},
                ])
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps({
                    "unit_id": "u",
                    "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                    "content": {"source_text": source_text},
                }, ensure_ascii=False) + "\n")
            subject = {"candidate_id": "fabricated-subject", "character_start": str(symptom_start),
                       "character_end": str(symptom_start + 2)}
            obj = {"candidate_id": "syndrome-real", "character_start": str(syndrome_start),
                   "character_end": str(syndrome_start + 4)}
            row = {field: "" for field in FIELDS}
            row.update({
                "predicate": "SYMPTOM_TO_SYNDROME",
                "subject_candidate_id": subject["candidate_id"], "subject_text": "头痛",
                "subject_type": "SYMPTOM", "subject_start": subject["character_start"],
                "subject_end": subject["character_end"], "object_candidate_id": obj["candidate_id"],
                "object_text": "太阳中风", "object_type": "SYNDROME",
                "object_start": obj["character_start"], "object_end": obj["character_end"],
                "unit_id": "u", "document": "a.sy", "source_sha256": "sha",
                "tree_position": "0", "block_id": "b", "sentence_start": "0",
                "sentence_end": str(len(source_text)), "evidence_text": source_text,
                "predicate_text": "辨证为", "extraction_rule": "SYMPTOM_TO_SYNDROME_EXPLICIT_V1",
                "resolution_status": "UNRESOLVED_CANDIDATE",
            })
            row["relation_id"] = relation_identity(
                row["predicate"], subject, obj, "u", 0, len(source_text)
            )
            with output.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow(row)
            with self.assertRaisesRegex(ValueError, "candidate ID/span/type is absent"):
                validate(output, units, context, mentions)

    def test_validator_rejects_relation_evidence_spanning_multiple_sentences(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "太阳中风。丹溪曰：治宜健脾"
            unit = {
                "unit_id": "u",
                "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")

            subject_start = source_text.index("太阳中风")
            object_start = source_text.index("健脾")
            subject = {
                "candidate_id": "syndrome-1",
                "character_start": str(subject_start),
                "character_end": str(subject_start + len("太阳中风")),
            }
            obj = {
                "candidate_id": "treatment-1",
                "character_start": str(object_start),
                "character_end": str(object_start + len("健脾")),
            }
            row = {field: "" for field in FIELDS}
            row.update({
                "predicate": "SYNDROME_TO_TREATMENT",
                "subject_candidate_id": subject["candidate_id"],
                "subject_text": "太阳中风",
                "subject_type": "SYNDROME",
                "subject_start": subject["character_start"],
                "subject_end": subject["character_end"],
                "object_candidate_id": obj["candidate_id"],
                "object_text": "健脾",
                "object_type": "TREATMENT",
                "object_start": obj["character_start"],
                "object_end": obj["character_end"],
                "unit_id": "u",
                "document": "a.sy",
                "source_sha256": "sha",
                "tree_position": "0",
                "block_id": "b",
                "sentence_start": "0",
                "sentence_end": str(len(source_text)),
                "evidence_text": source_text,
                "predicate_text": "治宜",
                "extraction_rule": "SYNDROME_TO_TREATMENT_EXPLICIT_V1",
                "resolution_status": "UNRESOLVED_CANDIDATE",
            })
            row["relation_id"] = relation_identity(
                row["predicate"], subject, obj, "u", 0, len(source_text)
            )
            with output.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow(row)

            with self.assertRaisesRegex(ValueError, "source sentence boundary"):
                validate(output, units)

    def test_validator_rejects_relation_crossing_source_attribution_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            units = root / "units.jsonl.gz"
            output = root / "relations.csv"
            source_text = "太阳中风，丹溪曰：治宜健脾"
            unit = {
                "unit_id": "u",
                "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")

            subject_start = source_text.index("太阳中风")
            object_start = source_text.index("健脾")
            subject = {
                "candidate_id": "syndrome-1",
                "character_start": str(subject_start),
                "character_end": str(subject_start + len("太阳中风")),
            }
            obj = {
                "candidate_id": "treatment-1",
                "character_start": str(object_start),
                "character_end": str(object_start + len("健脾")),
            }
            row = {field: "" for field in FIELDS}
            row.update({
                "predicate": "SYNDROME_TO_TREATMENT",
                "subject_candidate_id": subject["candidate_id"],
                "subject_text": "太阳中风",
                "subject_type": "SYNDROME",
                "subject_start": subject["character_start"],
                "subject_end": subject["character_end"],
                "object_candidate_id": obj["candidate_id"],
                "object_text": "健脾",
                "object_type": "TREATMENT",
                "object_start": obj["character_start"],
                "object_end": obj["character_end"],
                "unit_id": "u",
                "document": "a.sy",
                "source_sha256": "sha",
                "tree_position": "0",
                "block_id": "b",
                "sentence_start": "0",
                "sentence_end": str(len(source_text)),
                "evidence_text": source_text,
                "predicate_text": "治宜",
                "extraction_rule": "SYNDROME_TO_TREATMENT_EXPLICIT_V1",
                "resolution_status": "UNRESOLVED_CANDIDATE",
            })
            row["relation_id"] = relation_identity(
                row["predicate"], subject, obj, "u", 0, len(source_text)
            )
            with output.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow(row)

            with self.assertRaisesRegex(ValueError, "source-attribution boundary"):
                validate(output, units)

if __name__ == "__main__":
    unittest.main()
