import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from audit_contextual_relation_coverage import audit
from build_contextual_relation_candidates import extract


class ContextualRelationCoverageAuditTests(unittest.TestCase):
    def test_classic_coverage_audit_counts_source_note_links_without_treating_them_as_classic_predicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            relations = root / "relations.csv"
            report = root / "coverage.json"
            source_text = "月经痛：针灸关元穴。"
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
            unit = {
                "unit_id": "u1",
                "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "relation_id", "predicate", "predicate_text", "extraction_rule", "resolution_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "relation_id": "source-note-1",
                    "predicate": "SOURCE_NOTE_ASSOCIATES",
                    "predicate_text": "：",
                    "extraction_rule": "SOURCE_NOTE_ASSOCIATES_LABEL_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })
            result = audit(context, mentions, units, relations, report)
            self.assertEqual(result["source_note_association_rows"], 1)
            parsed = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(parsed["source_note_association_rows"], 1)
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "relation_id", "predicate", "predicate_text", "extraction_rule", "resolution_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "relation_id": "source-note-1",
                    "predicate": "SOURCE_NOTE_ASSOCIATES",
                    "predicate_text": "错",
                    "extraction_rule": "SOURCE_NOTE_ASSOCIATES_LABEL_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })
            with self.assertRaisesRegex(ValueError, "invalid source-note association row contract"):
                audit(context, mentions, units, relations, report)

    def test_classical_attribution_rows_are_counted_separately_from_classic_predicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            relations = root / "relations.csv"
            report = root / "coverage.json"
            source_text = "内经说气街。"
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
                    "character_end", "document", "source_sha256", "tree_position", "block_id",
                ])
                writer.writeheader()
            unit = {
                "unit_id": "u1",
                "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "relation_id", "predicate", "subject_type", "object_type",
                    "predicate_text", "extraction_rule", "resolution_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "relation_id": "classical-attribution-1", "predicate": "SOURCE_NOTE_ASSOCIATES",
                    "subject_type": "CLASSICAL_SOURCE", "object_type": "CLASSICAL_THEORY",
                    "predicate_text": "说",
                    "extraction_rule": "SOURCE_NOTE_ASSOCIATES_CLASSICAL_ATTRIBUTION_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })
            result = audit(context, mentions, units, relations, report)
            self.assertEqual(result["source_note_association_rows"], 1)
            parsed = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(parsed["source_note_association_rows"], 1)

    def test_reports_predicate_coverage_and_matches_extractor_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = root / "context.csv.gz"
            mentions = root / "mentions.csv.gz"
            units = root / "units.jsonl.gz"
            relations = root / "relations.csv"
            report = root / "coverage.json"
            source_text = (
                "症见头痛，辨证为太阳中风，治宜解肌发表，方用桂枝汤。"
                "头痛，不宜辨证为太阳中风。"
                "治宜解肌发表。"
                "太阳中风，治宜丹溪曰∶解肌发表。"
            )
            second_sentence = source_text.index("头痛", source_text.index("。") + 1)
            second_syndrome = source_text.index("太阳中风", source_text.index("。") + 1)
            terms = [
                ("s1", "头痛", "SYMPTOM", source_text.index("头痛")),
                ("s2", "头痛", "SYMPTOM", second_sentence),
                ("y1", "太阳中风", "SYNDROME", source_text.index("太阳中风")),
                ("y2", "太阳中风", "SYNDROME", second_syndrome),
                ("t1", "解肌发表", "TREATMENT", source_text.index("解肌发表")),
                ("t2", "解肌发表", "TREATMENT", source_text.index("解肌发表", source_text.index("。", source_text.index("。") + 1) + 1)),
                ("y3", "太阳中风", "SYNDROME", source_text.rindex("太阳中风")),
                ("t3", "解肌发表", "TREATMENT", source_text.rindex("解肌发表")),
            ]
            with gzip.open(context, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                    "character_end", "evidence_start", "evidence_text", "classification_status",
                ])
                writer.writeheader()
                for cid, term, typ, start in terms:
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
                start = source_text.index("桂枝汤")
                writer.writerow({
                    "mention_id": "f1", "unit_id": "u", "entity_type": "FORMULA",
                    "matched_text": "桂枝汤", "character_start": start, "character_end": start + 3,
                    "document": "a.sy", "source_sha256": "sha", "tree_position": "0", "block_id": "b",
                })
            unit = {
                "unit_id": "u",
                "source": {"document": "a.sy", "sha256": "sha", "tree_position": "0", "block_id": "b"},
                "content": {"source_text": source_text},
            }
            with gzip.open(units, "wt", encoding="utf-8", newline="") as stream:
                stream.write(json.dumps(unit, ensure_ascii=False) + "\n")

            extract(context, mentions, units, relations)
            result = audit(context, mentions, units, relations, report)
            self.assertEqual(result["source_units_scanned"], 1)
            self.assertEqual(result["predicates"]["SYMPTOM_TO_SYNDROME"]["eligible_pairs"], 1)
            self.assertEqual(result["predicates"]["SYMPTOM_TO_SYNDROME"]["extracted_rows"], 1)
            self.assertEqual(result["predicates"]["SYMPTOM_TO_SYNDROME"]["negated_pairs"], 1)
            self.assertEqual(result["predicates"]["SYNDROME_TO_TREATMENT"]["eligible_pairs"], 1)
            self.assertEqual(result["predicates"]["SYNDROME_TO_TREATMENT"]["scope_break_pairs"], 1)
            self.assertEqual(result["predicates"]["TREATMENT_TO_FORMULA"]["eligible_pairs"], 1)
            # Matching counts alone are insufficient: a fabricated row with
            # the same predicate/count must not pass the independent audit.
            with relations.open("r", encoding="utf-8", newline="") as stream:
                relation_reader = csv.DictReader(stream)
                relation_fields = relation_reader.fieldnames
                relation_rows = list(relation_reader)
            original_relation_id = relation_rows[0]["relation_id"]
            relation_rows[0]["relation_id"] = "fabricated-relation-id"
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=relation_fields)
                writer.writeheader()
                writer.writerows(relation_rows)
            with self.assertRaisesRegex(ValueError, "not an independently eligible pair"):
                audit(context, mentions, units, relations, report)
            relation_rows[0]["relation_id"] = original_relation_id
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=relation_fields)
                writer.writeheader()
                writer.writerows(relation_rows)
            result = audit(context, mentions, units, relations, report)
            self.assertTrue(report.is_file())
            parsed = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(parsed["schema_version"], 3)
            diagnostic = parsed["predicates"]["SYMPTOM_TO_SYNDROME"]
            self.assertEqual(diagnostic["marker_sentences_with_both_endpoint_types"], 2)
            self.assertEqual(diagnostic["marker_sentences_without_subject_type"], 0)
            self.assertEqual(diagnostic["marker_sentences_without_object_type"], 0)
            treatment_diagnostic = parsed["predicates"]["SYNDROME_TO_TREATMENT"]
            examples = parsed["diagnostic_examples"]["SYNDROME_TO_TREATMENT"]
            self.assertEqual(len(examples["missing_subject_type"]), 1)
            sample = examples["missing_subject_type"][0]
            self.assertEqual(sample["document"], "a.sy")
            self.assertEqual(sample["source_sha256"], "sha")
            self.assertIn("治宜解肌发表", sample["sentence_text"])
            self.assertEqual(sample["typed_candidate_spans"][0]["candidate_type"], "TREATMENT")
            marker_spans = sample["predicate_marker_spans"]
            self.assertTrue(marker_spans)
            for marker_span in marker_spans:
                self.assertEqual(
                    source_text[marker_span["start"]:marker_span["end"]],
                    marker_span["text"],
                )
            self.assertGreaterEqual(
                treatment_diagnostic["typed_candidate_mentions_by_type_in_marker_sentences"]["TREATMENT"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
