import sqlite3
import tempfile
import unittest
from pathlib import Path

from search_classical_knowledge_paths import search_classical_knowledge_paths


def create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE classical_source_documents (
            source_document_id TEXT PRIMARY KEY,
            document TEXT NOT NULL UNIQUE,
            source_work TEXT NOT NULL,
            source_work_label TEXT NOT NULL,
            root_document TEXT NOT NULL,
            parent_document TEXT NOT NULL,
            notebook TEXT NOT NULL,
            title TEXT NOT NULL,
            document_depth INTEGER NOT NULL,
            document_role TEXT NOT NULL,
            chapter_path_json TEXT NOT NULL
        );
        CREATE TABLE classical_source_passages (
            passage_id TEXT PRIMARY KEY,
            source_document_id TEXT NOT NULL,
            document TEXT NOT NULL,
            source_work TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            tree_position TEXT NOT NULL,
            block_id TEXT NOT NULL,
            parent_block_id TEXT NOT NULL,
            content_type TEXT NOT NULL,
            section_path TEXT NOT NULL,
            character_start INTEGER NOT NULL,
            character_end INTEGER NOT NULL,
            passage_text TEXT NOT NULL,
            passage_kind TEXT NOT NULL
        );
        CREATE TABLE classical_source_passage_mentions (
            occurrence_id TEXT PRIMARY KEY,
            passage_id TEXT NOT NULL,
            source_document_id TEXT NOT NULL,
            reference_kind TEXT NOT NULL,
            reference_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            term_type TEXT NOT NULL,
            term_text TEXT NOT NULL,
            character_start INTEGER NOT NULL,
            character_end INTEGER NOT NULL,
            rule_ids_json TEXT NOT NULL,
            resolution_status TEXT NOT NULL
        );
        CREATE TABLE classical_source_passage_term_links (
            link_id TEXT PRIMARY KEY,
            passage_id TEXT NOT NULL,
            source_work TEXT NOT NULL,
            document TEXT NOT NULL,
            document_role TEXT NOT NULL,
            pair_key TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            subject_occurrence_id TEXT NOT NULL,
            object_occurrence_id TEXT NOT NULL
        );
        CREATE TABLE classical_source_document_references (
            reference_id TEXT PRIMARY KEY,
            source_document_id TEXT NOT NULL,
            target_document_id TEXT NOT NULL,
            source_document TEXT NOT NULL,
            target_document TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_tree_position TEXT NOT NULL,
            source_block_id TEXT NOT NULL,
            target_block_id TEXT NOT NULL,
            target_subtype TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            resolution TEXT NOT NULL
        );
        CREATE TABLE semantic_relation_candidates (
            relation_id TEXT PRIMARY KEY,
            unit_id TEXT NOT NULL,
            subject_mention_id TEXT NOT NULL,
            subject_text TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_mention_id TEXT NOT NULL,
            object_text TEXT NOT NULL,
            document TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            tree_position TEXT NOT NULL,
            block_id TEXT,
            sentence_start INTEGER NOT NULL,
            sentence_end INTEGER NOT NULL,
            evidence_text TEXT NOT NULL,
            extraction_rule TEXT NOT NULL,
            resolution_status TEXT NOT NULL
        );
        CREATE TABLE contextual_relation_candidates (
            relation_id TEXT PRIMARY KEY,
            predicate TEXT NOT NULL,
            subject_candidate_id TEXT NOT NULL,
            subject_text TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_start INTEGER NOT NULL,
            subject_end INTEGER NOT NULL,
            object_candidate_id TEXT NOT NULL,
            object_text TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_start INTEGER NOT NULL,
            object_end INTEGER NOT NULL,
            unit_id TEXT NOT NULL,
            document TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            tree_position TEXT NOT NULL,
            block_id TEXT,
            sentence_start INTEGER NOT NULL,
            sentence_end INTEGER NOT NULL,
            evidence_text TEXT NOT NULL,
            predicate_text TEXT NOT NULL,
            extraction_rule TEXT NOT NULL,
            resolution_status TEXT NOT NULL
        );
    """)

    connection.executemany(
        "INSERT INTO classical_source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "doc-sh", "shanghan/太阳.sy", "SHANG_HAN_LUN", "伤寒论",
                "root-sh", "root-sh", "倪海厦", "太阳篇", 1,
                "CLASSICAL_CHAPTER", '["伤寒论","太阳篇"]',
            ),
            (
                "doc-zj", "zhenjiu/针灸大成.sy", "ZHEN_JIU_DA_CHENG", "针灸大成",
                "root-zj", "root-zj", "书籍", "针灸大成", 1,
                "CLASSICAL_CHAPTER", '["针灸大成"]',
            ),
        ],
    )

    sh_text = "太阳病，恶寒，桂枝汤用桂枝。"
    zj_text = "恶寒，足三里针刺。"
    repeated_text = "恶寒恶寒。"
    connection.executemany(
        "INSERT INTO classical_source_passages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "p-sh-1", "doc-sh", "shanghan/太阳.sy", "SHANG_HAN_LUN",
                "sha-a", "0.1", "b1", "", "PARAGRAPH", "伤寒论/太阳篇",
                0, len(sh_text), sh_text, "SENTENCE_OR_CLAUSE",
            ),
            (
                "p-sh-2", "doc-sh", "shanghan/太阳.sy", "SHANG_HAN_LUN",
                "sha-a", "0.2", "b2", "", "PARAGRAPH", "伤寒论/太阳篇",
                0, len(repeated_text), repeated_text, "SENTENCE_OR_CLAUSE",
            ),
            (
                "p-zj-1", "doc-zj", "zhenjiu/针灸大成.sy", "ZHEN_JIU_DA_CHENG",
                "sha-zj", "0.1", "z1", "", "PARAGRAPH", "针灸大成",
                0, len(zj_text), zj_text, "SENTENCE_OR_CLAUSE",
            ),
        ],
    )

    def add_mention(
        occurrence_id: str, passage_id: str, source_document_id: str,
        reference_kind: str, reference_id: str, entity_id: str,
        term_type: str, term_text: str, source_text: str, start: int,
        rule_ids: str = "[]",
    ) -> None:
        connection.execute(
            "INSERT INTO classical_source_passage_mentions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                occurrence_id, passage_id, source_document_id, reference_kind,
                reference_id, entity_id, term_type, term_text, start,
                start + len(term_text), rule_ids, "UNRESOLVED_CANDIDATE",
            ),
        )

    add_mention(
        "occ-symptom", "p-sh-1", "doc-sh", "CONTEXTUAL_TERM_CANDIDATE",
        "ctx-symptom", "", "SYMPTOM", "恶寒", sh_text, sh_text.index("恶寒"),
    )
    add_mention(
        "occ-syndrome", "p-sh-1", "doc-sh", "CONTEXTUAL_TERM_CANDIDATE",
        "ctx-syndrome", "", "SYNDROME", "太阳病", sh_text, sh_text.index("太阳病"),
    )
    add_mention(
        "occ-formula", "p-sh-1", "doc-sh", "ENTITY_MENTION",
        "mention-formula", "entity-formula", "FORMULA", "桂枝汤",
        sh_text, sh_text.index("桂枝汤"),
    )
    add_mention(
        "occ-herb", "p-sh-1", "doc-sh", "ENTITY_MENTION",
        "mention-herb", "entity-herb", "HERB", "桂枝",
        sh_text, sh_text.rindex("桂枝"),
    )
    add_mention(
        "occ-repeat-1", "p-sh-2", "doc-sh", "CONTEXTUAL_TERM_CANDIDATE",
        "ctx-repeat-1", "", "SYMPTOM", "恶寒", repeated_text, 0,
    )
    add_mention(
        "occ-repeat-2", "p-sh-2", "doc-sh", "CONTEXTUAL_TERM_CANDIDATE",
        "ctx-repeat-2", "", "SYMPTOM", "恶寒", repeated_text, 2,
    )
    add_mention(
        "occ-symptom-zj", "p-zj-1", "doc-zj", "CONTEXTUAL_TERM_CANDIDATE",
        "ctx-symptom-zj", "", "SYMPTOM", "恶寒", zj_text, 0,
    )
    add_mention(
        "occ-point-zj", "p-zj-1", "doc-zj", "ENTITY_MENTION",
        "mention-point", "entity-point", "ACUPOINT", "足三里",
        zj_text, zj_text.index("足三里"),
    )
    add_mention(
        "occ-technique-zj", "p-zj-1", "doc-zj", "ENTITY_MENTION",
        "mention-technique", "entity-technique", "ACUPUNCTURE_TECHNIQUE", "针刺",
        zj_text, zj_text.index("针刺"),
    )

    connection.executemany(
        "INSERT INTO classical_source_passage_term_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "link-symptom-formula", "p-sh-1", "SHANG_HAN_LUN",
                "shanghan/太阳.sy", "CLASSICAL_CHAPTER", "SYMPTOM|FORMULA",
                "SAME_PASSAGE_CO_OCCURRENCE", "occ-symptom", "occ-formula",
            ),
            (
                "link-formula-herb", "p-sh-1", "SHANG_HAN_LUN",
                "shanghan/太阳.sy", "CLASSICAL_CHAPTER", "FORMULA|HERB",
                "SAME_PASSAGE_CO_OCCURRENCE", "occ-formula", "occ-herb",
            ),
            (
                "link-symptom-point", "p-zj-1", "ZHEN_JIU_DA_CHENG",
                "zhenjiu/针灸大成.sy", "CLASSICAL_CHAPTER", "SYMPTOM|ACUPOINT",
                "SAME_PASSAGE_CO_OCCURRENCE", "occ-symptom-zj", "occ-point-zj",
            ),
            (
                "link-symptom-technique", "p-zj-1", "ZHEN_JIU_DA_CHENG",
                "zhenjiu/针灸大成.sy", "CLASSICAL_CHAPTER",
                "SYMPTOM|ACUPUNCTURE_TECHNIQUE",
                "SAME_PASSAGE_CO_OCCURRENCE", "occ-symptom-zj", "occ-technique-zj",
            ),
        ],
    )

    connection.execute(
        "INSERT INTO semantic_relation_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rel-formula-herb", "unit-sh-1", "mention-formula", "桂枝汤",
            "FORMULA_CONTAINS_HERB", "mention-herb", "桂枝",
            "shanghan/太阳.sy", "sha-a", "0.1", "b1", 0, len(sh_text),
            sh_text, "FORMULA_COMPOSITION_EXPLICIT_V1", "UNRESOLVED_CANDIDATE",
        ),
    )
    connection.execute(
        "INSERT INTO contextual_relation_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "rel-symptom-syndrome", "SYMPTOM_TO_SYNDROME",
            "ctx-symptom", "恶寒", "SYMPTOM", sh_text.index("恶寒"),
            sh_text.index("恶寒") + 2, "ctx-syndrome", "太阳病", "SYNDROME",
            sh_text.index("太阳病"), sh_text.index("太阳病") + 3,
            "unit-sh-1", "shanghan/太阳.sy", "sha-a", "0.1", "b1",
            0, len(sh_text), sh_text, "辨证为",
            "SYMPTOM_TO_SYNDROME_EXPLICIT_V1", "UNRESOLVED_CANDIDATE",
        ),
    )
    connection.execute(
        "INSERT INTO classical_source_document_references VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "native-ref-1", "doc-sh", "doc-neijing",
            "shanghan/太阳.sy", "neijing/阴阳应象大论.sy",
            "sha-a", "0.1", "b1", "n1", "d",
            "BLOCK_REFERENCE", "RESOLVED_IN_CORPUS",
        ),
    )
    connection.commit()
    connection.close()


class ClassicalKnowledgePathQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "search.sqlite3"
        create_database(self.database)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_keeps_repeated_occurrences_and_returns_distinct_book_paths(self):
        result = search_classical_knowledge_paths(
            self.database, "恶寒", term_type="SYMPTOM"
        )
        self.assertEqual(result["matched_occurrences"], 4)
        ids = [item["match"]["occurrence_id"] for item in result["matches"]]
        self.assertEqual(len(ids), len(set(ids)))
        repeated = [
            item for item in result["matches"]
            if item["source"]["passage_id"] == "p-sh-2"
        ]
        self.assertEqual(
            [item["match"]["block_character_start"] for item in repeated], [0, 2]
        )
        self.assertTrue(all(
            item["match"]["source_span_matches_term"] for item in result["matches"]
        ))
        works = {item["source"]["source_work"] for item in result["matches"]}
        self.assertEqual(works, {"SHANG_HAN_LUN", "ZHEN_JIU_DA_CHENG"})

    def test_expands_formula_herb_contextual_and_native_reference_evidence(self):
        result = search_classical_knowledge_paths(
            self.database, "恶寒", term_type="SYMPTOM", source_work="SHANG_HAN_LUN"
        )
        first = next(
            item for item in result["matches"]
            if item["source"]["passage_id"] == "p-sh-1"
        )
        self.assertEqual(len(first["formula_herb_candidates"]), 1)
        formula_herb = first["formula_herb_candidates"][0]
        self.assertEqual(formula_herb["predicate"], "FORMULA_CONTAINS_HERB")
        self.assertEqual(formula_herb["subject_text"], "桂枝汤")
        self.assertEqual(formula_herb["object_text"], "桂枝")
        self.assertEqual(formula_herb["relation_semantics"], "UNRESOLVED_SEMANTIC_CANDIDATE")
        self.assertEqual(len(first["contextual_relation_candidates"]), 1)
        self.assertEqual(
            first["contextual_relation_candidates"][0]["predicate"],
            "SYMPTOM_TO_SYNDROME",
        )
        self.assertEqual(len(first["document_references"]), 1)
        self.assertEqual(
            first["document_references"][0]["relation_semantics"],
            "NATIVE_SIYUAN_REFERENCE",
        )
        self.assertEqual(
            first["source"]["document_role"], "CLASSICAL_CHAPTER"
        )

    def test_returns_symptom_acupoint_and_technique_links_as_navigation_only(self):
        result = search_classical_knowledge_paths(
            self.database, "恶寒", source_work="ZHEN_JIU_DA_CHENG"
        )
        self.assertEqual(result["matched_occurrences"], 1)
        item = result["matches"][0]
        self.assertEqual(
            {link["pair_key"] for link in item["navigational_links"]},
            {"SYMPTOM|ACUPOINT", "SYMPTOM|ACUPUNCTURE_TECHNIQUE"},
        )
        self.assertTrue(all(
            link["relation_semantics"] == "NAVIGATION_ONLY"
            for link in item["navigational_links"]
        ))
        terms = {(term["term_type"], term["term_text"]) for term in item["passage_terms"]}
        self.assertIn(("ACUPOINT", "足三里"), terms)
        self.assertIn(("ACUPUNCTURE_TECHNIQUE", "针刺"), terms)

    def test_rejects_empty_query_and_nonpositive_limit(self):
        with self.assertRaisesRegex(ValueError, "query must not be empty"):
            search_classical_knowledge_paths(self.database, " ")
        with self.assertRaisesRegex(ValueError, "limit must be a positive integer"):
            search_classical_knowledge_paths(self.database, "恶寒", limit=0)

    def test_rejects_database_without_classical_source_tables(self):
        empty = Path(self.temp_dir.name) / "empty.sqlite3"
        sqlite3.connect(empty).close()
        with self.assertRaisesRegex(ValueError, "missing classical-source tables"):
            search_classical_knowledge_paths(empty, "恶寒")


if __name__ == "__main__":
    unittest.main()
