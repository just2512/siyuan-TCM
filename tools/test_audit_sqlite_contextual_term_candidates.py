from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("audit_sqlite_contextual_term_candidates.py")
SPEC = importlib.util.spec_from_file_location("audit_sqlite_contextual_term_candidates", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


class SQLiteContextualTermAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "index.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.connection.executescript("""
            CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE content_blocks (
                document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                content_text TEXT
            );
            CREATE TABLE contextual_term_type_candidates (
                candidate_id TEXT, term TEXT, candidate_type TEXT, rule_id TEXT,
                evidence_document TEXT, source_sha256 TEXT, tree_position TEXT, block_id TEXT,
                unit_id TEXT, character_start INTEGER, character_end INTEGER,
                evidence_start INTEGER, evidence_text TEXT, classification_status TEXT
            );
        """)
        locator = ("book/a.sy", "sha-a", "0.0", "p1")
        self.unit_id = hashlib.sha256("\0".join(locator).encode()).hexdigest()
        source = "前文，症见头痛伴恶心，后文"
        start = source.index("头痛")
        evidence_start = max(0, start - 12)
        evidence_text = source[evidence_start:min(len(source), start + 2 + 12)]
        self.connection.execute(
            "INSERT INTO content_blocks VALUES (?, ?, ?, ?, ?)", (*locator, source)
        )
        self.connection.execute(
            "INSERT INTO contextual_term_type_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("cid", "头痛", "SYMPTOM", "SYMPTOM_CONTEXT_01", *locator[:3], locator[3],
             self.unit_id, start, start + 2, evidence_start, evidence_text, "CONTEXT_RULE_CANDIDATE"),
        )
        self.connection.execute(
            "INSERT INTO index_metadata VALUES ('contextual_term_type_candidates', '1')"
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_validates_exact_term_and_evidence_slices(self):
        result = module.audit(self.db)
        self.assertEqual(result["checked_contextual_term_candidates"], 1)
        self.assertEqual(result["candidate_counts_by_type"], {"SYMPTOM": 1})

    def test_rejects_term_offset_substitution(self):
        self.connection.execute(
            "UPDATE contextual_term_type_candidates SET character_start=character_start+1"
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "source span mismatch"):
            module.audit(self.db)

    def test_rejects_evidence_text_drift(self):
        self.connection.execute(
            "UPDATE contextual_term_type_candidates SET evidence_text='伪造证据'"
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "evidence offset/text mismatch"):
            module.audit(self.db)

    def test_rejects_wrong_rule_for_type(self):
        self.connection.execute(
            "UPDATE contextual_term_type_candidates SET rule_id='FORMULA_CONTEXT_01'"
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "rule/type mismatch"):
            module.audit(self.db)

    def test_rejects_unit_id_not_derived_from_locator(self):
        self.connection.execute(
            "UPDATE contextual_term_type_candidates SET unit_id='wrong'"
        )
        self.connection.commit()
        with self.assertRaisesRegex(ValueError, "unit_id/source locator mismatch"):
            module.audit(self.db)


    def test_keeps_repeated_term_occurrences_at_distinct_offsets(self):
        source = "前文，症见头痛，复见头痛，后文"
        self.connection.execute("UPDATE content_blocks SET content_text=?", (source,))
        first = source.index("头痛")
        second = source.index("头痛", first + 2)
        for index, start in enumerate((first, second)):
            evidence_start = max(0, start - 12)
            evidence_text = source[evidence_start:min(len(source), start + 2 + 12)]
            if index == 0:
                self.connection.execute(
                    "UPDATE contextual_term_type_candidates "
                    "SET character_start=?, character_end=?, evidence_start=?, evidence_text=?",
                    (start, start + 2, evidence_start, evidence_text),
                )
            else:
                self.connection.execute(
                    "INSERT INTO contextual_term_type_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("cid", "头痛", "SYMPTOM", "SYMPTOM_CONTEXT_01",
                     "book/a.sy", "sha-a", "0.0", "p1", self.unit_id,
                     start, start + 2, evidence_start, evidence_text, "CONTEXT_RULE_CANDIDATE"),
                )
        self.connection.execute(
            "UPDATE index_metadata SET value='2' WHERE key='contextual_term_type_candidates'"
        )
        self.connection.commit()
        result = module.audit(self.db)
        self.assertEqual(result["checked_contextual_term_candidates"], 2)
        self.assertEqual(result["candidate_counts_by_type"], {"SYMPTOM": 2})


if __name__ == "__main__":
    unittest.main()
