import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from audit_contextual_relation_coverage import audit
from build_contextual_relation_candidates import extract


class ContextualRelationCoverageAuditTests(unittest.TestCase):
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
            )
            second_sentence = source_text.index("头痛", source_text.index("。") + 1)
            second_syndrome = source_text.index("太阳中风", source_text.index("。") + 1)
            terms = [
                ("s1", "头痛", "SYMPTOM", source_text.index("头痛")),
                ("s2", "头痛", "SYMPTOM", second_sentence),
                ("y1", "太阳中风", "SYNDROME", source_text.index("太阳中风")),
                ("y2", "太阳中风", "SYNDROME", second_syndrome),
                ("t1", "解肌发表", "TREATMENT", source_text.index("解肌发表")),
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
            self.assertEqual(result["predicates"]["TREATMENT_TO_FORMULA"]["eligible_pairs"], 1)
            self.assertTrue(report.is_file())
            parsed = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(parsed["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
