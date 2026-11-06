import csv
import gzip
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

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
            self.assertEqual(found[0]["subject_tree_position"], "0.2")
            self.assertEqual(found[0]["object_tree_position"], "0.0")
            self.assertEqual(found[0]["evidence_tree_position"], "0.0")

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
            with self.assertRaises(ValueError):
                search_db.build_database(content, None, root / "bad.sqlite3", entities,
                                          None, root / "missing-registry.csv")

    def test_rejects_empty_query(self):
        with self.assertRaises(ValueError):
            search_db.search_database(Path("unused.db"), "  ")


if __name__ == "__main__":
    unittest.main()
