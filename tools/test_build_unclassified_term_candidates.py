import csv
import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("build_unclassified_term_candidates.py")
SPEC = importlib.util.spec_from_file_location("build_unclassified_term_candidates", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write_units(path, records):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def make_unit(unit_id, document, text):
    return {
        "unit_id": unit_id,
        "source": {
            "document": document,
            "sha256": (unit_id[0] * 64)[:64],
            "tree_position": "0.1",
            "block_id": unit_id,
        },
        "content": {"source_text": text},
    }


class UnclassifiedTermCandidateTests(unittest.TestCase):
    def test_mines_repeated_terms_with_traceable_spans(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            records = [
                make_unit("u1", "a.sy", "太阳中风，桂枝汤主之。"),
                make_unit("u2", "b.sy", "太阳中风，桂枝汤证。"),
                make_unit("u3", "c.sy", "太阳中风，桂枝汤加减。"),
            ]
            write_units(source, records)

            result = module.mine(source, output, min_occurrences=3, min_documents=2)
            self.assertEqual(result["knowledge_units_scanned"], 3)
            self.assertEqual(result["documents_scanned"], 3)
            self.assertGreater(result["unclassified_term_candidates"], 0)
            if module.resource is not None:
                self.assertGreater(result["peak_rss_kib"], 0)
            self.assertEqual(
                module.validate(output), result["unclassified_term_candidates"]
            )
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            row = next(item for item in rows if item["term"] == "太阳中风")
            self.assertEqual(row["candidate_status"], "UNCLASSIFIED_TERM_CANDIDATE")
            self.assertEqual(row["occurrence_count"], "3")
            self.assertEqual(row["unit_count"], "3")
            self.assertEqual(row["document_count"], "3")
            samples = json.loads(row["sample_evidence"])
            self.assertEqual(len(samples), 3)
            self.assertIn("太阳中风", samples[0]["evidence_text"])
            self.assertEqual(samples[0]["matched_text"], "太阳中风")

    def test_document_counts_are_unique_within_sorted_documents_and_sample_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            records = [
                make_unit("u1", "a.sy", "经络辨证"),
                make_unit("u2", "a.sy", "经络辨证"),
                make_unit("u3", "b.sy", "经络辨证"),
                make_unit("u4", "c.sy", "经络辨证"),
            ]
            write_units(source, records)

            result = module.mine(
                source, output, min_occurrences=4, min_documents=3, sample_limit=2
            )
            self.assertEqual(result["knowledge_units_scanned"], 4)
            self.assertEqual(result["documents_scanned"], 3)
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            row = next(item for item in rows if item["term"] == "经络辨证")
            self.assertEqual(row["occurrence_count"], "4")
            self.assertEqual(row["unit_count"], "4")
            self.assertEqual(row["document_count"], "3")
            samples = json.loads(row["sample_evidence"])
            self.assertEqual(len(samples), 2)
            self.assertEqual([item["document"] for item in samples], ["a.sy", "b.sy"])

    def test_accepts_non_monotonic_document_order_and_counts_unique_documents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            records = [
                make_unit("u1", "a.sy", "经络辨证"),
                make_unit("u2", "b.sy", "经络辨证"),
                make_unit("u3", "a.sy", "经络辨证"),
            ]
            write_units(source, records)
            result = module.mine(
                source, output, min_occurrences=3, min_documents=2, sample_limit=2
            )
            self.assertEqual(result["knowledge_units_scanned"], 3)
            self.assertEqual(result["documents_scanned"], 2)
            self.assertEqual(result["aggregation_strategy"], "sqlite_term_document_upsert")
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                row = next(item for item in csv.DictReader(stream) if item["term"] == "经络辨证")
            self.assertEqual(row["occurrence_count"], "3")
            self.assertEqual(row["unit_count"], "3")
            self.assertEqual(row["document_count"], "2")
            samples = json.loads(row["sample_evidence"])
            self.assertEqual(len(samples), 2)
            self.assertEqual({item["document"] for item in samples}, {"a.sy", "b.sy"})

    def test_sample_limit_one_is_exact_across_repeated_and_out_of_order_documents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            records = [
                make_unit("u1", "z.sy", "经络辨证"),
                make_unit("u2", "a.sy", "经络辨证"),
                make_unit("u3", "z.sy", "经络辨证"),
                make_unit("u4", "m.sy", "经络辨证"),
            ]
            write_units(source, records)
            module.mine(source, output, min_occurrences=4, min_documents=3, sample_limit=1)
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                row = next(item for item in csv.DictReader(stream) if item["term"] == "经络辨证")
            self.assertEqual(row["occurrence_count"], "4")
            self.assertEqual(row["unit_count"], "4")
            self.assertEqual(row["document_count"], "3")
            samples = json.loads(row["sample_evidence"])
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["document"], "a.sy")

    def test_rejects_non_positive_sample_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            write_units(source, [make_unit("u1", "a.sy", "经络辨证")])
            with self.assertRaisesRegex(ValueError, "sample_limit must be positive"):
                module.mine(source, output, sample_limit=0)

    def test_excludes_terms_already_present_in_entity_lexicon(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            lexicon = root / "lexicon.csv"
            records = [
                make_unit("u1", "a.sy", "桂枝汤太阳中风"),
                make_unit("u2", "b.sy", "桂枝汤太阳中风"),
            ]
            write_units(source, records)
            lexicon.write_text(
                "entity_type,term,lexicon_version\nFORMULA,桂枝汤,1.3.0\n",
                encoding="utf-8",
            )

            result = module.mine(
                source, output, min_occurrences=2, min_documents=2,
                lexicon_path=lexicon
            )
            with gzip.open(output, "rt", encoding="utf-8", newline="") as stream:
                terms = {row["term"] for row in csv.DictReader(stream)}
            self.assertNotIn("桂枝汤", terms)
            self.assertIn("太阳中风", terms)
            self.assertGreater(result["known_lexicon_occurrences_skipped"], 0)

    def test_ignores_terms_seen_in_only_one_document(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "units.jsonl.gz"
            output = root / "terms.csv.gz"
            records = [
                make_unit("u1", "a.sy", "罕见证候罕见证候罕见证候"),
            ]
            write_units(source, records)

            result = module.mine(source, output, min_occurrences=2, min_documents=2)
            self.assertEqual(result["unclassified_term_candidates"], 0)
            self.assertEqual(module.validate(output), 0)


if __name__ == "__main__":
    unittest.main()
