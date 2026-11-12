import gzip
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("audit_contextual_term_overlaps.py")
SPEC = importlib.util.spec_from_file_location("audit_contextual_term_overlaps", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ContextualTermOverlapAuditTests(unittest.TestCase):
    def write_rows(self, path, rows):
        fields = ["candidate_id","term","candidate_type","rule_id","unit_id","character_start","character_end","classification_status"]
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            import csv
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, term, kind, start, end, candidate=None, rule="R1"):
        return {"candidate_id": candidate or term, "term": term, "candidate_type": kind,
                "rule_id": rule, "unit_id": "unit-1", "character_start": str(start),
                "character_end": str(end), "classification_status": "CONTEXT_RULE_CANDIDATE"}

    def test_repeated_term_at_distinct_offsets_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            self.write_rows(path, [self.row("气虚","SYNDROME",0,2), self.row("气虚","SYNDROME",8,10)])
            result = module.audit(path)
            self.assertEqual(result["distinct_occurrence_rows"], 2)
            self.assertEqual(result["repeated_lexical_forms_with_multiple_occurrences"], 1)
            self.assertEqual(result["overlap_pair_counts"], {})

    def test_nested_and_partial_overlaps_are_reported_not_collapsed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            self.write_rows(path, [
                self.row("脾气虚","SYNDROME",0,3),
                self.row("气虚","SYNDROME",1,3),
                self.row("虚证","SYNDROME",2,4),
                self.row("脾气","SYMPTOM",0,2),
            ])
            result = module.audit(path)
            self.assertEqual(result["distinct_occurrence_rows"], 4)
            self.assertGreater(result["overlap_pair_counts"]["current_nested"], 0)
            self.assertGreater(result["overlap_pair_counts"]["partial_overlap"], 0)

    def test_duplicate_same_rule_occurrence_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            row = self.row("气虚","SYNDROME",0,2)
            self.write_rows(path, [row,row])
            with self.assertRaisesRegex(ValueError, "duplicate contextual occurrence"):
                module.audit(path)


if __name__ == "__main__":
    unittest.main()
