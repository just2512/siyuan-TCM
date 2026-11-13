from __future__ import annotations

import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from build_contextual_overlap_review_queue import build_review_queue


FIELDS = [
    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
    "character_end", "evidence_start", "evidence_text", "classification_status",
]


class ContextualOverlapReviewQueueTests(unittest.TestCase):
    def write_input(self, path: Path, rows: list[dict]) -> None:
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def row(self, *, candidate_id: str, term: str, kind: str, start: int,
            text: str = "患者咳嗽发热", rule: str = "RULE_A",
            document: str = "doc.sy", source_hash: str = "abc",
            tree_position: str = "0.1", block_id: str = "block",
            unit_id: str = "unit") -> dict:
        return {
            "candidate_id": candidate_id, "term": term, "candidate_type": kind,
            "rule_id": rule, "evidence_document": document,
            "source_sha256": source_hash, "tree_position": tree_position,
            "block_id": block_id, "unit_id": unit_id,
            "character_start": str(start), "character_end": str(start + len(term)),
            "evidence_start": "0", "evidence_text": text,
            "classification_status": "CONTEXT_RULE_CANDIDATE",
        }

    def test_exports_cross_type_overlap_with_exact_source_and_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, report = root / "terms.csv.gz", root / "review.csv", root / "report.json"
            self.write_input(source, [
                self.row(candidate_id="symptom-1", term="咳嗽", kind="SYMPTOM", start=2),
                self.row(candidate_id="pulse-1", term="咳嗽发", kind="PULSE", start=2),
            ])
            overlap_audit = root / "overlap-audit.json"
            overlap_audit.write_text(json.dumps({
                "overlap_pair_candidate_type_counts": {"PULSE|SYMPTOM": 1},
                "overlap_pair_type_relation_counts": {"cross_type": 1},
            }), encoding="utf-8")
            result = build_review_queue(source, output, report, overlap_audit)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(result["cross_type_overlap_pairs"], 1)
            self.assertEqual(result["reconciliation"]["status"], "PASS")
            self.assertEqual(rows[0]["candidate_type_pair"], "PULSE|SYMPTOM")
            self.assertEqual(rows[0]["left_start"], "2")
            self.assertEqual(rows[0]["right_end"], "5")
            self.assertEqual(rows[0]["evidence_text"], "患者咳嗽发热")
            self.assertEqual(rows[0]["review_status"], "UNREVIEWED")
            self.assertEqual(rows[0]["document"], "doc.sy")

    def test_rejects_review_queue_count_that_does_not_match_overlap_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, report = root / "terms.csv.gz", root / "review.csv", root / "report.json"
            self.write_input(source, [
                self.row(candidate_id="symptom-1", term="咳嗽", kind="SYMPTOM", start=2),
                self.row(candidate_id="pulse-1", term="咳嗽发", kind="PULSE", start=2),
            ])
            overlap_audit = root / "overlap-audit.json"
            overlap_audit.write_text(json.dumps({
                "overlap_pair_candidate_type_counts": {"PULSE|SYMPTOM": 2},
                "overlap_pair_type_relation_counts": {"cross_type": 2},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not reconcile"):
                build_review_queue(source, output, report, overlap_audit)

    def test_same_type_overlap_is_not_misreported_as_cross_type_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, report = root / "terms.csv.gz", root / "review.csv", root / "report.json"
            self.write_input(source, [
                self.row(candidate_id="s1", term="咳嗽", kind="SYMPTOM", start=2),
                self.row(candidate_id="s2", term="咳嗽发", kind="SYMPTOM", start=2),
            ])
            result = build_review_queue(source, output, report)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows, [])
            self.assertEqual(result["same_type_overlap_pairs_not_queued"], 1)

    def test_rejects_candidate_span_not_matching_exact_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, report = root / "terms.csv.gz", root / "review.csv", root / "report.json"
            self.write_input(source, [
                self.row(candidate_id="s1", term="咳嗽", kind="SYMPTOM", start=2),
                self.row(candidate_id="p1", term="发热", kind="PULSE", start=4),
            ])
            with gzip.open(source, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["evidence_text"] = "患者呕吐发热"
            self.write_input(source, rows)
            with self.assertRaisesRegex(ValueError, "candidate span/evidence text mismatch"):
                build_review_queue(source, output, report)

    def test_rejects_overlapping_candidates_with_different_source_locators(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, report = root / "terms.csv.gz", root / "review.csv", root / "report.json"
            self.write_input(source, [
                self.row(candidate_id="s1", term="咳嗽", kind="SYMPTOM", start=2),
                self.row(candidate_id="p1", term="咳嗽发", kind="PULSE", start=2, block_id="other"),
            ])
            with self.assertRaisesRegex(ValueError, "different source locators"):
                build_review_queue(source, output, report)

    def test_pair_ids_distinguish_same_lexical_span_classified_as_multiple_types(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, report = root / "terms.csv.gz", root / "review.csv", root / "report.json"
            # candidate_id is lexical-term identity. Three types can legitimately
            # classify the same term at the same offset, yielding three distinct
            # cross-type pairs that must have distinct pair IDs.
            self.write_input(source, [
                self.row(candidate_id="same-lexical-id", term="咳嗽", kind="HERB", start=2),
                self.row(candidate_id="same-lexical-id", term="咳嗽", kind="PULSE", start=2),
                self.row(candidate_id="same-lexical-id", term="咳嗽", kind="SYMPTOM", start=2),
            ])
            result = build_review_queue(source, output, report)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(result["cross_type_overlap_pairs"], 3)
            self.assertEqual(len(rows), 3)
            self.assertEqual(len({row["pair_id"] for row in rows}), 3)
            self.assertEqual(
                {row["candidate_type_pair"] for row in rows},
                {"HERB|PULSE", "HERB|SYMPTOM", "PULSE|SYMPTOM"},
            )

    def test_duplicate_rule_rows_for_same_occurrence_are_collapsed_not_double_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, report = root / "terms.csv.gz", root / "review.csv", root / "report.json"
            self.write_input(source, [
                self.row(candidate_id="s1", term="咳嗽", kind="SYMPTOM", start=2, rule="RULE_A"),
                self.row(candidate_id="s1", term="咳嗽", kind="SYMPTOM", start=2, rule="RULE_B"),
                self.row(candidate_id="p1", term="咳嗽发", kind="PULSE", start=2),
            ])
            result = build_review_queue(source, output, report)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(result["cross_type_overlap_pairs"], 1)
            self.assertEqual(rows[0]["left_rule_ids"], "RULE_A;RULE_B")


if __name__ == "__main__":
    unittest.main()
