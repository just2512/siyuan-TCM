import csv
import gzip
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_classical_source_passages import create_tables as create_classical_source_tables

MODULE_PATH = Path(__file__).with_name("build_siyuan_search_db.py")
SPEC = importlib.util.spec_from_file_location("build_siyuan_search_db", MODULE_PATH)
search_db = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(search_db)


class SiYuanSearchDatabaseTests(unittest.TestCase):
    def _write_gzip_csv(self, path, fields, rows):
        with gzip.open(path, "wt", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_builds_searchable_sqlite_database_and_imports_relationships(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            relations = root / "relations.csv.gz"
            db = root / "search.sqlite3"
            entities = root / "entities.csv.gz"
            self._write_gzip_csv(entities, search_db.ENTITY_FIELDS, [
                {"mention_id": "m1", "unit_id": "u1", "entity_type": "FORMULA",
                 "matched_text": "桂枝汤", "character_start": 0, "character_end": 3,
                 "document": "book/a.sy", "source_sha256": "hash-a",
                 "tree_position": "0.0", "block_id": "p1", "content_type": "PARAGRAPH",
                 "section_path": "经方 / 桂枝汤", "lexicon_version": "1.0.0",
                 "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
            ])
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [
                {"document": "book/a.sy", "source_sha256": "hash-a",
                 "tree_position": "0.0", "block_id": "p1",
                 "parent_block_id": "doc", "parent_node_type": "NodeDocument",
                 "content_type": "PARAGRAPH", "heading_level": "",
                 "section_path": "经方 / 桂枝汤", "section_heading_block_ids": "h1;h2",
                 "characters": 10, "content_text": "桂枝汤治疗太阳中风"},
                {"document": "book/b.sy", "source_sha256": "hash-b",
                 "tree_position": "0.1", "block_id": "p2",
                 "parent_block_id": "doc2", "parent_node_type": "NodeDocument",
                 "content_type": "PARAGRAPH", "heading_level": "",
                 "section_path": "中药", "section_heading_block_ids": "h3",
                 "characters": 8, "content_text": "麻黄用于发汗"},
            ])
            self._write_gzip_csv(relations, search_db.RELATION_FIELDS, [
                {"source_document": "book/a.sy", "source_sha256": "hash-a",
                 "source_tree_position": "0.0", "source_block_id": "p1",
                 "source_node_type": "NodeTextMark", "relation_type": "BLOCK_REFERENCE",
                 "target": "target-id", "target_subtype": "d",
                 "target_document": "book/b.sy", "resolution": "RESOLVED_IN_CORPUS"}
            ])
            result = search_db.build_database(content, relations, db, entities)
            self.assertEqual(result["content_blocks"], 2)
            self.assertEqual(result["relationships"], 1)
            self.assertEqual(result["entity_mentions"], 1)
            self.assertTrue(db.is_file())
            # Three-character Chinese phrase uses trigram FTS when available.
            results = search_db.search_database(db, "桂枝汤")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["document"], "book/a.sy")
            self.assertEqual(results[0]["section_path"], "经方 / 桂枝汤")
            # Two-character Chinese term uses exact substring fallback.
            results = search_db.search_database(db, "麻黄")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["document"], "book/b.sy")
            with sqlite3.connect(db) as connection:
                count = connection.execute("SELECT COUNT(*) FROM node_relationships").fetchone()[0]
                entity = connection.execute(
                    "SELECT entity_type, matched_text, document, resolution_status FROM entity_mentions"
                ).fetchone()
            self.assertEqual(count, 1)
            self.assertEqual(entity, ("FORMULA", "桂枝汤", "book/a.sy", "UNRESOLVED_CANDIDATE"))
            entity_results = search_db.search_entity_mentions(db, "桂枝汤")
            self.assertEqual(len(entity_results), 1)
            self.assertEqual(entity_results[0]["character_start"], 0)
            self.assertEqual(entity_results[0]["character_end"], 3)
            self.assertEqual(entity_results[0]["content_text"], "桂枝汤治疗太阳中风")
            resolved = search_db.search_entity_by_id(db, entity_results[0]["entity_id"])
            self.assertEqual(len(resolved), 1)
            self.assertEqual(resolved[0]["matched_text"], "桂枝汤")

    def test_fts_search_returns_source_locator_without_content_blocks_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            db = root / "search.sqlite3"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [{
                "document": "book/a.sy", "source_sha256": "sha-a",
                "tree_position": "0.0", "block_id": "p1",
                "content_type": "PARAGRAPH", "section_path": "经方",
                "characters": 9, "content_text": "桂枝汤治疗太阳中风",
            }])
            result = search_db.build_database(content, None, db)
            if result["search_backend"] != "fts5-trigram":
                self.skipTest("SQLite build does not provide FTS5 trigram support")

            # Make the fallback source table deliberately unable to satisfy the
            # query. A successful result must therefore come from content_fts.
            with sqlite3.connect(db) as connection:
                connection.execute(
                    "UPDATE content_blocks SET content_text=? WHERE document=?",
                    ("回退表中已不存在目标词", "book/a.sy"),
                )
            rows = search_db.search_database(db, "桂枝汤")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["document"], "book/a.sy")
            self.assertEqual(rows[0]["source_sha256"], "sha-a")
            self.assertEqual(rows[0]["tree_position"], "0.0")
            self.assertEqual(rows[0]["content_text"], "桂枝汤治疗太阳中风")

    def test_indexes_and_queries_explicit_relation_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            relations = root / "relation_candidates.csv"
            entities = root / "entities.csv.gz"
            db = root / "search.sqlite3"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [{
                "document": "book/a.sy", "source_sha256": "hash-a",
                "tree_position": "0.0", "block_id": "p1",
                "content_type": "PARAGRAPH", "characters": 12,
                "content_text": "桂枝汤由桂枝组成。",
            }])
            self._write_gzip_csv(entities, search_db.ENTITY_FIELDS, [
                {"mention_id": "m1", "unit_id": "u2", "entity_type": "FORMULA",
                 "matched_text": "桂枝汤", "character_start": 0, "character_end": 3,
                 "document": "book/a.sy", "source_sha256": "hash-a",
                 "tree_position": "0.2", "block_id": "p2", "content_type": "PARAGRAPH",
                 "section_path": "", "lexicon_version": "1.1.0",
                 "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
                {"mention_id": "m2", "unit_id": "u1", "entity_type": "HERB",
                 "matched_text": "桂枝", "character_start": 3, "character_end": 5,
                 "document": "book/a.sy", "source_sha256": "hash-a",
                 "tree_position": "0.0", "block_id": "p1", "content_type": "PARAGRAPH",
                 "section_path": "", "lexicon_version": "1.1.0",
                 "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
            ])
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=search_db.RELATION_CANDIDATE_FIELDS)
                writer.writeheader()
                writer.writerow({
                    "relation_id": "r1", "unit_id": "u1", "subject_mention_id": "m1",
                    "subject_text": "桂枝汤", "predicate": "FORMULA_CONTAINS_HERB",
                    "object_mention_id": "m2", "object_text": "桂枝",
                    "document": "book/a.sy", "source_sha256": "hash-a",
                    "tree_position": "0.0", "block_id": "p1",
                    "sentence_start": 0, "sentence_end": 9,
                    "evidence_text": "桂枝汤由桂枝组成。",
                    "extraction_rule": "FORMULA_COMPOSITION_EXPLICIT_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })
            result = search_db.build_database(content, None, db, entities, relations)
            self.assertEqual(result["relation_candidates"], 1)
            found = search_db.search_relation_candidates(db, "桂枝汤")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["object_text"], "桂枝")
            self.assertEqual(found[0]["evidence_text"], "桂枝汤由桂枝组成。")
            self.assertEqual(found[0]["subject_mention_id"], "m1")
            self.assertEqual(found[0]["object_mention_id"], "m2")
            self.assertEqual(found[0]["subject_type"], "FORMULA")
            self.assertEqual(found[0]["object_type"], "HERB")
            self.assertEqual(found[0]["subject_matched_text"], "桂枝汤")
            self.assertEqual(found[0]["object_matched_text"], "桂枝")
            self.assertEqual((found[0]["subject_character_start"], found[0]["subject_character_end"]), (0, 3))
            self.assertEqual((found[0]["object_character_start"], found[0]["object_character_end"]), (3, 5))
            self.assertEqual(found[0]["subject_unit_id"], "u2")
            self.assertEqual(found[0]["object_unit_id"], "u1")
            self.assertEqual(found[0]["subject_source_sha256"], "hash-a")
            self.assertEqual(found[0]["object_source_sha256"], "hash-a")
            self.assertEqual(found[0]["subject_tree_position"], "0.2")
            self.assertEqual(found[0]["object_tree_position"], "0.0")
            self.assertEqual(found[0]["evidence_tree_position"], "0.0")
            self.assertEqual(found[0]["subject_entity_id"], search_db.search_entity_mentions(db, "桂枝汤")[0]["entity_id"])
            self.assertEqual(found[0]["object_entity_id"], search_db.search_entity_mentions(db, "桂枝")[0]["entity_id"])

    def test_registry_assigns_stable_entity_id_to_mentions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            entities = root / "entities.csv.gz"
            registry = root / "registry.csv"
            db = root / "search.sqlite3"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [{
                "document": "book/a.sy", "source_sha256": "hash-a",
                "tree_position": "0.0", "block_id": "p1",
                "content_type": "PARAGRAPH", "characters": 6,
                "content_text": "黄芪与黄耆",
            }])
            self._write_gzip_csv(entities, search_db.ENTITY_FIELDS, [
                {"mention_id": "m1", "unit_id": "u1", "entity_type": "HERB",
                 "matched_text": "黄芪", "character_start": 0, "character_end": 2,
                 "document": "book/a.sy", "source_sha256": "hash-a",
                 "tree_position": "0.0", "block_id": "p1", "content_type": "PARAGRAPH",
                 "section_path": "", "lexicon_version": "1.3.0",
                 "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
                {"mention_id": "m2", "unit_id": "u1", "entity_type": "HERB",
                 "matched_text": "黄耆", "character_start": 3, "character_end": 5,
                 "document": "book/a.sy", "source_sha256": "hash-a",
                 "tree_position": "0.0", "block_id": "p1", "content_type": "PARAGRAPH",
                 "section_path": "", "lexicon_version": "1.3.0",
                 "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
            ])
            with registry.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=search_db.ENTITY_REGISTRY_FIELDS)
                writer.writeheader()
                for term in ("黄芪", "黄耆"):
                    writer.writerow({
                        "entity_id": "id-" + term, "entity_type": "HERB",
                        "preferred_label": term, "lexical_form": term,
                        "lexicon_version": "1.3.0", "identity_status": "LEXICAL_ID_ONLY",
                    })
            result = search_db.build_database(content, None, db, entities, None, registry)
            self.assertEqual(result["lexical_entities"], 2)
            first = search_db.search_entity_mentions(db, "黄芪")
            second = search_db.search_entity_mentions(db, "黄耆")
            self.assertEqual(first[0]["entity_id"], "id-黄芪")
            self.assertEqual(second[0]["entity_id"], "id-黄耆")
            self.assertNotEqual(first[0]["entity_id"], second[0]["entity_id"])
            with self.assertRaises(FileNotFoundError):
                search_db.build_database(content, None, root / "bad.sqlite3", entities,
                                          None, root / "missing-registry.csv")


    def test_indexes_and_queries_corpus_mined_terms(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            terms = root / "terms.csv.gz"
            db = root / "search.sqlite3"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [{
                "document": "book/a.sy", "source_sha256": "hash-a",
                "tree_position": "0.0", "block_id": "p1",
                "content_type": "PARAGRAPH", "characters": 6,
                "content_text": "太阳中风，桂枝汤主之",
            }])
            self._write_gzip_csv(terms, [
                "candidate_id", "term", "ngram_length", "occurrence_count",
                "unit_count", "document_count", "sample_evidence", "candidate_status",
            ], [{
                "candidate_id": "term-sun-wind", "term": "太阳中风",
                "ngram_length": 4, "occurrence_count": 8, "unit_count": 5,
                "document_count": 3, "sample_evidence": "[]",
                "candidate_status": "UNCLASSIFIED_TERM_CANDIDATE",
            }])
            result = search_db.build_database(content, None, db, None, None, None, terms)
            self.assertEqual(result["unclassified_term_candidates"], 1)
            found = search_db.search_unclassified_terms(db, "太阳")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["term"], "太阳中风")
            self.assertEqual(found[0]["document_count"], 3)

    def test_indexes_and_queries_contextual_term_type_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            terms = root / "terms.csv.gz"
            contextual = root / "contextual.csv.gz"
            db = root / "search.sqlite3"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [{
                "document": "book/a.sy", "source_sha256": "hash-a",
                "tree_position": "0.0", "block_id": "p1",
                "content_type": "PARAGRAPH", "characters": 9,
                "content_text": "症见头痛，症见头痛",
            }])
            self._write_gzip_csv(terms, [
                "candidate_id", "term", "ngram_length", "occurrence_count",
                "unit_count", "document_count", "sample_evidence", "candidate_status",
            ], [{
                "candidate_id": "term-headache", "term": "头痛", "ngram_length": 2,
                "occurrence_count": 5, "unit_count": 3, "document_count": 2,
                "sample_evidence": "[]", "candidate_status": "UNCLASSIFIED_TERM_CANDIDATE",
            }])
            self._write_gzip_csv(contextual, [
                "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                "character_end", "evidence_start", "evidence_text", "classification_status",
            ], [
                {
                    "candidate_id": "term-headache", "term": "头痛", "candidate_type": "SYMPTOM",
                    "rule_id": "SYMPTOM_CONTEXT_01", "evidence_document": "book/a.sy",
                    "source_sha256": "hash-a", "tree_position": "0.0", "block_id": "p1",
                    "unit_id": "u1", "character_start": 2, "character_end": 4,
                    "evidence_start": 0, "evidence_text": "症见头痛，症见头痛",
                    "classification_status": "CONTEXT_RULE_CANDIDATE",
                },
                {
                    "candidate_id": "term-headache", "term": "头痛", "candidate_type": "SYMPTOM",
                    "rule_id": "SYMPTOM_CONTEXT_01", "evidence_document": "book/a.sy",
                    "source_sha256": "hash-a", "tree_position": "0.0", "block_id": "p1",
                    "unit_id": "u1", "character_start": 7, "character_end": 9,
                    "evidence_start": 0, "evidence_text": "症见头痛，症见头痛",
                    "classification_status": "CONTEXT_RULE_CANDIDATE",
                },
            ])
            result = search_db.build_database(
                content, None, db, term_candidates_path=terms,
                contextual_term_candidates_path=contextual,
            )
            self.assertEqual(result["contextual_term_type_candidates"], 2)
            found = search_db.search_contextual_term_candidates(db, "头痛")
            self.assertEqual(len(found), 2)
            self.assertEqual({row["candidate_type"] for row in found}, {"SYMPTOM"})
            self.assertEqual({row["character_start"] for row in found}, {2, 7})
            self.assertTrue(all(row["evidence_text"] == "症见头痛，症见头痛" for row in found))
            self.assertEqual(len(search_db.search_contextual_term_candidates(db, "SYMPTOM")), 2)

    def test_indexes_and_queries_contextual_relation_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            relations = root / "contextual-relations.csv"
            db = root / "search.sqlite3"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [{
                "document": "book/a.sy", "source_sha256": "hash-a",
                "tree_position": "0.0", "block_id": "p1",
                "content_type": "PARAGRAPH", "characters": 12,
                "content_text": "症见头痛，辨证为太阳中风",
            }])
            fields = [
                "relation_id", "predicate", "subject_candidate_id", "subject_text",
                "subject_type", "subject_start", "subject_end", "object_candidate_id",
                "object_text", "object_type", "object_start", "object_end", "unit_id",
                "document", "source_sha256", "tree_position", "block_id",
                "sentence_start", "sentence_end", "evidence_text", "predicate_text",
                "extraction_rule", "resolution_status",
            ]
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "relation_id": "ctx-r1", "predicate": "SYMPTOM_TO_SYNDROME",
                    "subject_candidate_id": "sym-1", "subject_text": "头痛",
                    "subject_type": "SYMPTOM", "subject_start": 2, "subject_end": 4,
                    "object_candidate_id": "syn-1", "object_text": "太阳中风",
                    "object_type": "SYNDROME", "object_start": 8, "object_end": 12,
                    "unit_id": "u1", "document": "book/a.sy", "source_sha256": "hash-a",
                    "tree_position": "0.0", "block_id": "p1", "sentence_start": 0,
                    "sentence_end": 12, "evidence_text": "症见头痛，辨证为太阳中风",
                    "predicate_text": "辨证为", "extraction_rule": "SYMPTOM_TO_SYNDROME_EXPLICIT_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })
            result = search_db.build_database(content, None, db, contextual_relations_path=relations)
            self.assertEqual(result["contextual_relation_candidates"], 1)
            found = search_db.search_contextual_relation_candidates(db, "头痛")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["object_text"], "太阳中风")
            self.assertEqual(found[0]["predicate_text"], "辨证为")
            self.assertEqual(len(search_db.search_contextual_relation_candidates(db, "SYMPTOM_TO_SYNDROME")), 1)

    def test_searches_role_scoped_classical_passage_links_with_occurrence_offsets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            db = root / "search.sqlite3"
            source_text = "发热复见发热，桂枝汤由桂枝组成。"
            self._write_gzip_csv(content, search_db.CONTENT_FIELDS, [{
                "document": "shanghan/太阳.sy", "source_sha256": "sha-classical",
                "tree_position": "0.1", "block_id": "b1",
                "content_type": "PARAGRAPH", "characters": len(source_text),
                "content_text": source_text,
            }])
            search_db.build_database(content, None, db)

            with sqlite3.connect(db) as connection:
                create_classical_source_tables(connection)
                connection.execute("""
                    INSERT INTO classical_source_documents VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    "sd1", "shanghan/太阳.sy", "SHANG_HAN_LUN", "伤寒论",
                    "shanghan.sy", "", "书籍", "第一篇 太阳篇", 1,
                    "CLASSICAL_CHAPTER", '[\"伤寒论\",\"第一篇 太阳篇\"]',
                ))
                connection.execute("""
                    INSERT INTO classical_source_passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    "passage-1", "sd1", "shanghan/太阳.sy", "SHANG_HAN_LUN",
                    "sha-classical", "0.1", "b1", "", "PARAGRAPH", "太阳",
                    0, len(source_text), source_text, "SENTENCE_OR_CLAUSE",
                ))
                formula_start = source_text.index("桂枝汤")
                herb_start = source_text.index("桂枝", formula_start + len("桂枝汤"))
                occurrences = [
                    ("symptom-1", "passage-1", "sd1", "CONTEXTUAL_TERM_CANDIDATE",
                     "ctx-symptom-1", "", "SYMPTOM", "发热", 0, 2, "[]", "CONTEXT_RULE_CANDIDATE"),
                    ("symptom-2", "passage-1", "sd1", "CONTEXTUAL_TERM_CANDIDATE",
                     "ctx-symptom-2", "", "SYMPTOM", "发热", 4, 6, "[]", "CONTEXT_RULE_CANDIDATE"),
                    ("formula-1", "passage-1", "sd1", "ENTITY_MENTION",
                     "mention-formula", "entity-formula", "FORMULA", "桂枝汤",
                     formula_start, formula_start + 3, "[]", "UNRESOLVED_CANDIDATE"),
                    ("herb-1", "passage-1", "sd1", "ENTITY_MENTION",
                     "mention-herb", "entity-herb", "HERB", "桂枝",
                     herb_start, herb_start + 2, "[]", "UNRESOLVED_CANDIDATE"),
                ]
                connection.executemany("""
                    INSERT INTO classical_source_passage_mentions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, occurrences)
                connection.executemany("""
                    INSERT INTO classical_source_passage_term_links VALUES (?,?,?,?,?,?,?,?,?)
                """, [
                    ("link-symptom-1", "passage-1", "SHANG_HAN_LUN",
                     "shanghan/太阳.sy", "CLASSICAL_CHAPTER", "SYMPTOM|FORMULA",
                     "SAME_PASSAGE_CO_OCCURRENCE", "symptom-1", "formula-1"),
                    ("link-symptom-2", "passage-1", "SHANG_HAN_LUN",
                     "shanghan/太阳.sy", "CLASSICAL_CHAPTER", "SYMPTOM|FORMULA",
                     "SAME_PASSAGE_CO_OCCURRENCE", "symptom-2", "formula-1"),
                    ("link-formula-herb", "passage-1", "SHANG_HAN_LUN",
                     "shanghan/太阳.sy", "CLASSICAL_CHAPTER", "FORMULA|HERB",
                     "SAME_PASSAGE_CO_OCCURRENCE", "formula-1", "herb-1"),
                ])

            symptom_links = search_db.search_classical_source_passage_links(db, "发热")
            self.assertEqual(len(symptom_links), 2)
            self.assertEqual(
                {row["subject_occurrence_id"] for row in symptom_links},
                {"symptom-1", "symptom-2"},
            )
            self.assertEqual({row["subject_start"] for row in symptom_links}, {0, 4})
            self.assertTrue(all(row["subject_type"] == "SYMPTOM" for row in symptom_links))
            self.assertTrue(all(row["object_type"] == "FORMULA" for row in symptom_links))
            self.assertTrue(all(row["source_work"] == "SHANG_HAN_LUN" for row in symptom_links))
            self.assertTrue(all(row["document_role"] == "CLASSICAL_CHAPTER" for row in symptom_links))
            for row in symptom_links:
                self.assertEqual(
                    row["source_text"][row["passage_start"]:row["passage_end"]],
                    row["passage_text"],
                )
                self.assertEqual(
                    row["source_text"][row["subject_start"]:row["subject_end"]],
                    row["subject_text"],
                )
                self.assertEqual(
                    row["source_text"][row["object_start"]:row["object_end"]],
                    row["object_text"],
                )

            formula_herb = search_db.search_classical_source_passage_links(
                db, "桂枝", source_work="SHANG_HAN_LUN",
                document_role="CLASSICAL_CHAPTER", pair_key="FORMULA|HERB",
            )
            self.assertEqual(len(formula_herb), 1)
            self.assertEqual(formula_herb[0]["subject_text"], "桂枝汤")
            self.assertEqual(formula_herb[0]["object_text"], "桂枝")
            self.assertEqual(formula_herb[0]["source_title"], "第一篇 太阳篇")
            self.assertEqual(
                search_db.search_classical_source_passage_links(
                    db, "桂枝", document_role="COMMENTARY",
                ),
                [],
            )
            self.assertEqual(
                search_db.search_classical_source_passage_links(
                    db, "桂枝", source_work="JIN_GUI_YAO_LUE",
                ),
                [],
            )

    def test_rejects_empty_query(self):
        with self.assertRaises(ValueError):
            search_db.search_database(Path("unused.db"), "  ")
        with self.assertRaises(ValueError):
            search_db.search_classical_source_passage_links(Path("unused.db"), "  ")


if __name__ == "__main__":
    unittest.main()
