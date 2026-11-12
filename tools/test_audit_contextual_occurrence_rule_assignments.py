from __future__ import annotations

import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from audit_contextual_occurrence_rule_assignments import audit


FIELDS = [
    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
    "character_end", "evidence_start", "evidence_text", "classification_status",
]


class ContextualOccurrenceRuleAssignmentAuditTests(unittest.TestCase):
    def write_input(self, path: Path, rows: list[dict]) -> None:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, *, start: int, rule: str = "RULE_A", unit: str = "unit",
            evidence: str = "患者咳嗽发热", term: str = "咳嗽",
            candidate_id: str = "term-cough") -> dict:
        return {
            "candidate_id": candidate_id, "term": term, "candidate_type": "SYMPTOM",
            "rule_id": rule, "evidence_document": "doc.sy", "source_sha256": "sha",
            "tree_position": "0.1", "block_id": "block", "unit_id": unit,
            "character_start": str(start), "character_end": str(start + len(term)),
            "evidence_start": "0", "evidence_text": evidence,
            "classification_status": "CONTEXT_RULE_CANDIDATE",
        }

    def test_multiple_rules_for_one_span_are_one_occurrence_with_two_assignments(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            self.write_input(path, [
                self.row(start=2, rule="RULE_A"),
                self.row(start=2, rule="RULE_B"),
            ])
            result = audit(path)
            self.assertEqual(result["candidate_rows"], 2)
            self.assertEqual(result["distinct_occurrences"], 1)
            self.assertEqual(result["multi_rule_occurrence_groups"], 1)
            self.assertEqual(result["extra_rule_assignments"], 1)
            self.assertEqual(result["multi_rule_occurrence_groups_by_type"], {"SYMPTOM": 1})

    def test_same_term_at_different_offsets_remains_two_occurrences(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            source = "患者咳嗽，复有咳嗽"
            second = source.rindex("咳嗽")
            self.write_input(path, [
                self.row(start=2, evidence=source),
                self.row(start=second, evidence=source),
            ])
            result = audit(path)
            self.assertEqual(result["candidate_rows"], 2)
            self.assertEqual(result["distinct_occurrences"], 2)
            self.assertEqual(result["multi_rule_occurrence_groups"], 0)

    def test_rejects_duplicate_same_rule_row(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            row = self.row(start=2)
            self.write_input(path, [row, row.copy()])
            with self.assertRaisesRegex(ValueError, "duplicate occurrence/rule rows"):
                audit(path)

    def test_rejects_conflicting_source_provenance_for_same_occurrence(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            first = self.row(start=2, rule="RULE_A")
            second = self.row(start=2, rule="RULE_B")
            second["source_sha256"] = "different"
            self.write_input(path, [first, second])
            with self.assertRaisesRegex(ValueError, "conflicting text/provenance"):
                audit(path)

    def test_rejects_evidence_text_that_does_not_match_occurrence_offset(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "terms.csv.gz"
            self.write_input(path, [self.row(start=2, evidence="患者呕吐发热")])
            with self.assertRaisesRegex(ValueError, "exact evidence slice"):
                audit(path)


if __name__ == "__main__":
    unittest.main()
