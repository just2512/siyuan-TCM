import csv
import json
import gzip
import hashlib
import tempfile
import unittest
from pathlib import Path

from audit_entity_mention_overlaps import audit


class EntityMentionOverlapAuditTests(unittest.TestCase):
    def test_distinguishes_nested_formula_herb_and_same_type_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            rows = [
                ("f1", "u", "FORMULA", "桂枝汤", 0, 3),
                ("h1", "u", "HERB", "桂枝", 0, 2),
                ("f2", "u", "FORMULA", "芍药甘草汤", 10, 15),
                ("f3", "u", "FORMULA", "甘草汤", 12, 15),
                ("h2", "u", "HERB", "桂枝", 20, 22),
                ("h3", "u", "HERB", "桂枝", 30, 32),
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(fields)
                for mid, unit, kind, term, start, end in rows:
                    writer.writerow([mid, unit, kind, term, start, end,
                                     "a.sy", "a" * 64, "0.1", "b"])
            result = audit(source, output)
            self.assertEqual(result["total_mentions"], 6)
            self.assertEqual(result["overlap_pair_counts"]["nested_formula_herb_entity"], 1)
            self.assertEqual(result["overlap_pair_counts"]["nested_named_formula"], 1)
            self.assertEqual(result["repeated_term_groups"], 1)
            self.assertEqual(result["repeated_term_occurrences_in_groups"], 3)
            report = output.read_text(encoding="utf-8")
            self.assertIn('"start": 0', report)
            self.assertIn('"start": 30', report)

    def test_cross_references_nested_formula_herb_pair_to_relation_endpoint_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            relations = root / "relations.csv"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, kind, term, start, end in [
                    ("f1", "FORMULA", "桂枝汤", 0, 3),
                    ("h1", "HERB", "桂枝", 0, 2),
                    ("f2", "FORMULA", "小柴胡汤", 10, 14),
                    ("h2", "HERB", "柴胡", 11, 13),
                ]:
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u", "entity_type": kind,
                        "matched_text": term, "character_start": start, "character_end": end,
                        "document": "a.sy", "source_sha256": "a" * 64,
                        "tree_position": "0.1", "block_id": "b",
                    })
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "relation_id", "subject_mention_id", "object_mention_id",
                    "document", "source_sha256", "tree_position", "block_id", "unit_id",
                ])
                writer.writeheader()
                writer.writerow({
                    "relation_id": "r1", "subject_mention_id": "f1",
                    "object_mention_id": "h1", "document": "a.sy",
                    "source_sha256": "a" * 64, "tree_position": "0.1",
                    "block_id": "b", "unit_id": "u",
                })
            result = audit(source, output, relations_path=relations)
            crossref = json.loads(output.read_text(encoding="utf-8"))["relation_candidate_cross_reference"]
            self.assertEqual(result["overlap_pair_counts"]["nested_formula_herb_entity"], 2)
            self.assertEqual(crossref["relation_candidate_rows"], 1)
            self.assertEqual(crossref["linked_same_unit_nested_pairs"], 1)
            self.assertEqual(crossref["unlinked_same_unit_nested_pairs"], 1)
            self.assertEqual(
                crossref["endpoint_reference"]["source_locator_matched_relations"], 1
            )
            self.assertEqual(
                crossref["endpoint_reference"]["examples"][0]["object_character_start"], 0
            )

    def test_rejects_relation_endpoints_missing_from_input_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            relations = root / "relations.csv"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, kind, term in [
                    ("f1", "FORMULA", "桂枝汤"),
                    ("h1", "HERB", "桂枝"),
                ]:
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u", "entity_type": kind,
                        "matched_text": term, "character_start": 0,
                        "character_end": len(term), "document": "a.sy",
                        "source_sha256": "a" * 64, "tree_position": "0.1",
                        "block_id": "b",
                    })
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "relation_id", "subject_mention_id", "subject_text",
                    "object_mention_id", "object_text",
                ])
                writer.writeheader()
                writer.writerow({
                    "relation_id": "r1", "subject_mention_id": "missing",
                    "subject_text": "桂枝汤", "object_mention_id": "h1",
                    "object_text": "桂枝",
                })
            with self.assertRaisesRegex(ValueError, "not found in input mentions"):
                audit(source, output, relations_path=relations)

    def test_rejects_relation_object_from_different_evidence_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            relations = root / "relations.csv"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, kind, term, block in [
                    ("f1", "FORMULA", "桂枝汤", "formula"),
                    ("h1", "HERB", "桂枝", "other-block"),
                ]:
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u", "entity_type": kind,
                        "matched_text": term, "character_start": 0,
                        "character_end": len(term), "document": "a.sy",
                        "source_sha256": "a" * 64, "tree_position": "0.1",
                        "block_id": block,
                    })
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "relation_id", "subject_mention_id", "object_mention_id",
                    "document", "source_sha256", "tree_position", "block_id", "unit_id",
                ])
                writer.writeheader()
                writer.writerow({
                    "relation_id": "r1", "subject_mention_id": "f1",
                    "object_mention_id": "h1", "document": "a.sy",
                    "source_sha256": "a" * 64, "tree_position": "0.1",
                    "block_id": "evidence-block", "unit_id": "u",
                })
            with self.assertRaisesRegex(ValueError, "object source locator mismatch"):
                audit(source, output, relations_path=relations)

    def test_rejects_relation_endpoint_text_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            relations = root / "relations.csv"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid, kind, term in [
                    ("f1", "FORMULA", "桂枝汤"),
                    ("h1", "HERB", "桂枝"),
                ]:
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u", "entity_type": kind,
                        "matched_text": term, "character_start": 0,
                        "character_end": len(term), "document": "a.sy",
                        "source_sha256": "a" * 64, "tree_position": "0.1",
                        "block_id": "b",
                    })
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "relation_id", "subject_mention_id", "subject_text",
                    "object_mention_id", "object_text",
                ])
                writer.writeheader()
                writer.writerow({
                    "relation_id": "r1", "subject_mention_id": "f1",
                    "subject_text": "小柴胡汤", "object_mention_id": "h1",
                    "object_text": "桂枝",
                })
            with self.assertRaisesRegex(ValueError, "text does not match"):
                audit(source, output, relations_path=relations)

    def test_reports_same_type_exact_duplicate_window_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mentions.csv.gz"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(source, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                for mid in ("h1", "h2"):
                    writer.writerow({
                        "mention_id": mid, "unit_id": "u", "entity_type": "HERB",
                        "matched_text": "桂枝", "character_start": 0, "character_end": 2,
                        "document": "a.sy", "source_sha256": "a" * 64,
                        "tree_position": "0.1", "block_id": "b",
                    })
            result = audit(source, output)
            self.assertEqual(
                result["overlap_pair_counts"]["same_type_exact_duplicate_window"], 1
            )


    def test_rejects_unit_id_that_does_not_match_source_locator(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mentions = root / "mentions.csv.gz"
            content = root / "content.csv.gz"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "mention_id": "m1", "unit_id": "forged-unit-id",
                    "entity_type": "HERB", "matched_text": "桂枝",
                    "character_start": 2, "character_end": 4,
                    "document": "a.sy", "source_sha256": "a" * 64,
                    "tree_position": "0.1", "block_id": "b1",
                })
            content_fields = ["document", "source_sha256", "tree_position", "block_id", "content_text"]
            with gzip.open(content, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=content_fields)
                writer.writeheader()
                writer.writerow({
                    "document": "a.sy", "source_sha256": "a" * 64,
                    "tree_position": "0.1", "block_id": "b1",
                    "content_text": "症见桂枝，脉浮。",
                })
            with self.assertRaisesRegex(ValueError, "unit_id does not match source locator"):
                audit(mentions, output, content_index_path=content)

    def test_validates_every_mention_offset_against_exact_source_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mentions = root / "mentions.csv.gz"
            content = root / "content.csv.gz"
            output = root / "audit.json"
            fields = [
                "mention_id", "unit_id", "entity_type", "matched_text",
                "character_start", "character_end", "document", "source_sha256",
                "tree_position", "block_id",
            ]
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "mention_id": "m1", "unit_id": hashlib.sha256("\\0".join(("a.sy", "a" * 64, "0.1", "b1")).encode("utf-8")).hexdigest(), "entity_type": "HERB",
                    "matched_text": "桂枝", "character_start": 2, "character_end": 4,
                    "document": "a.sy", "source_sha256": "a" * 64,
                    "tree_position": "0.1", "block_id": "b1",
                })
            content_fields = ["document", "source_sha256", "tree_position", "block_id", "content_text"]
            with gzip.open(content, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=content_fields)
                writer.writeheader()
                writer.writerow({
                    "document": "a.sy", "source_sha256": "a" * 64,
                    "tree_position": "0.1", "block_id": "b1",
                    "content_text": "症见桂枝，脉浮。",
                })
            result = audit(mentions, output, content_index_path=content)
            self.assertEqual(result["source_span_validation"], {
                "source_blocks": 1, "checked_mentions": 1, "unit_identity_checked": 1, "status": "PASS",
            })
            with gzip.open(mentions, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "mention_id": "m1", "unit_id": "u1", "entity_type": "HERB",
                    "matched_text": "白芍", "character_start": 2, "character_end": 4,
                    "document": "a.sy", "source_sha256": "a" * 64,
                    "tree_position": "0.1", "block_id": "b1",
                })
            with self.assertRaisesRegex(ValueError, "mention source span does not match source text"):
                audit(mentions, output, content_index_path=content)


if __name__ == "__main__":
    unittest.main()
