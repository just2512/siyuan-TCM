import csv
import gzip
import importlib.util
import json
import sqlite3
import tempfile
import unittest

from build_contextual_relation_candidates import relation_identity
from build_classical_source_passages import create_tables as create_classical_source_tables
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("export_semantic_graph.py")
SPEC = importlib.util.spec_from_file_location("export_semantic_graph", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

DB_PATH = Path(__file__).with_name("build_siyuan_search_db.py")
DB_SPEC = importlib.util.spec_from_file_location("build_siyuan_search_db", DB_PATH)
db = importlib.util.module_from_spec(DB_SPEC)
DB_SPEC.loader.exec_module(db)


class SemanticGraphExportTests(unittest.TestCase):
    def test_exports_nodes_and_traceable_candidate_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            mentions = root / "mentions.csv.gz"
            registry = root / "registry.csv"
            relations = root / "relations.csv"
            database = root / "search.sqlite3"
            output = root / "graph.jsonl.gz"
            def write_gzip(path, fields, rows):
                with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
            write_gzip(content, db.CONTENT_FIELDS, [{
                "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                "block_id": "b1", "content_type": "PARAGRAPH", "characters": 9,
                "content_text": "桂枝汤由桂枝组成。",
            }])
            write_gzip(mentions, db.ENTITY_FIELDS, [
                {"mention_id": "f1", "unit_id": "u1", "entity_type": "FORMULA",
                 "matched_text": "桂枝汤", "character_start": 0, "character_end": 3,
                 "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                 "block_id": "b1", "content_type": "PARAGRAPH", "section_path": "",
                 "lexicon_version": "1.3.0", "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
                {"mention_id": "h1", "unit_id": "u1", "entity_type": "HERB",
                 "matched_text": "桂枝", "character_start": 4, "character_end": 6,
                 "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                 "block_id": "b1", "content_type": "PARAGRAPH", "section_path": "",
                 "lexicon_version": "1.3.0", "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
            ])
            with registry.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=db.ENTITY_REGISTRY_FIELDS)
                writer.writeheader()
                writer.writerows([
                    {"entity_id": "ef", "entity_type": "FORMULA", "preferred_label": "桂枝汤",
                     "lexical_form": "桂枝汤", "lexicon_version": "1.3.0",
                     "identity_status": "LEXICAL_ID_ONLY"},
                    {"entity_id": "eh", "entity_type": "HERB", "preferred_label": "桂枝",
                     "lexical_form": "桂枝", "lexicon_version": "1.3.0",
                     "identity_status": "LEXICAL_ID_ONLY"},
                ])
            with relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=db.RELATION_CANDIDATE_FIELDS)
                writer.writeheader()
                writer.writerow({
                    "relation_id": "r1", "unit_id": "u1", "subject_mention_id": "f1",
                    "subject_text": "桂枝汤", "predicate": "FORMULA_CONTAINS_HERB",
                    "object_mention_id": "h1", "object_text": "桂枝",
                    "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                    "block_id": "b1", "sentence_start": 0, "sentence_end": 9,
                    "evidence_text": "桂枝汤由桂枝组成。", "extraction_rule": "EXPLICIT_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })
            db.build_database(content, None, database, mentions, relations, registry)
            result = module.export(database, output)
            self.assertEqual(result, {
                "entity_nodes": 2, "relation_edges": 1,
                "contextual_term_candidates": 0, "contextual_relation_edges": 0,
                "classical_source_documents": 0, "classical_source_passages": 0,
                "classical_source_passage_mentions": 0,
                "classical_source_document_references": 0,
                "classical_source_passage_term_links": 0,
            })
            self.assertEqual(module.validate(database, output), {
                "validated_entity_nodes": 2, "validated_relation_edges": 1,
                "validated_contextual_term_candidates": 0,
                "validated_contextual_relation_edges": 0,
                "validated_classical_source_documents": 0,
                "validated_classical_source_passages": 0,
                "validated_classical_source_passage_mentions": 0,
                "validated_classical_source_document_references": 0,
                "validated_classical_source_passage_term_links": 0,
            })
            with gzip.open(output, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            edge = next(row for row in rows if row["record_type"] == "RELATION_CANDIDATE")
            self.assertEqual(edge["subject_entity_id"], "ef")
            self.assertEqual(edge["object_entity_id"], "eh")
            self.assertEqual(edge["subject_mention"], {
                "mention_id": "f1", "entity_id": "ef", "entity_type": "FORMULA",
                "matched_text": "桂枝汤", "unit_id": "u1", "character_start": 0,
                "character_end": 3, "document": "a.sy", "source_sha256": "hash",
                "tree_position": "0.0", "block_id": "b1",
            })
            self.assertEqual(edge["object_mention"], {
                "mention_id": "h1", "entity_id": "eh", "entity_type": "HERB",
                "matched_text": "桂枝", "unit_id": "u1", "character_start": 4,
                "character_end": 6, "document": "a.sy", "source_sha256": "hash",
                "tree_position": "0.0", "block_id": "b1",
            })
            self.assertEqual(edge["evidence"]["text"], "桂枝汤由桂枝组成。")
            # A graph edge must retain the exact mention identity, not only the
            # canonical lexical entity node. Its mention offsets must also resolve
            # to the source block independently of the relation evidence span.
            edge["subject_mention"]["mention_id"] = "missing-mention"
            with gzip.open(output, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "relation graph/SQLite mismatch"):
                module.validate(database, output)
            edge["subject_mention"]["mention_id"] = "f1"
            edge["object_mention"]["character_start"] = 3
            with gzip.open(output, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "relation graph/SQLite mismatch"):
                module.validate(database, output)
            edge["object_mention"]["character_start"] = 4
            # Destructive checks: every exported relation field and endpoint mapping
            # must remain identical to the SQLite source row.
            edge["predicate"] = "FORMULA_CONTAINS_FORMULA"
            with gzip.open(output, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "relation graph/SQLite mismatch"):
                module.validate(database, output)

            edge["predicate"] = "FORMULA_CONTAINS_HERB"
            entity = next(row for row in rows if row["record_type"] == "ENTITY")
            entity["preferred_label"] = "错误实体标签"
            with gzip.open(output, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "entity graph/SQLite mismatch"):
                module.validate(database, output)

            # A graph and SQLite row can agree byte-for-byte yet still encode
            # the wrong semantic direction. Corrupt the stored edge itself to
            # ensure graph validation enforces FORMULA -> HERB, not merely
            # membership in the allowed endpoint-type set.
            with sqlite3.connect(database) as connection:
                connection.execute("""
                    UPDATE semantic_relation_candidates
                    SET subject_mention_id='h1', subject_text='桂枝',
                        object_mention_id='f1', object_text='桂枝汤'
                    WHERE relation_id='r1'
                """)
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "invalid subject_mention relation endpoint direction/type"):
                module.validate(database, output)

            # Python accepts negative slice indexes. A negative source offset
            # can therefore resolve to the correct characters unless bounds
            # are checked explicitly.
            with sqlite3.connect(database) as connection:
                connection.execute("""
                    UPDATE semantic_relation_candidates
                    SET subject_mention_id='f1', subject_text='桂枝汤',
                        object_mention_id='h1', object_text='桂枝'
                    WHERE relation_id='r1'
                """)
                connection.execute("""
                    UPDATE entity_mentions SET character_start=-5, character_end=-3
                    WHERE mention_id='h1'
                """)
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "object_mention source span mismatch"):
                module.validate(database, output)

            # Evidence offsets need explicit bounds too: Python negative slices
            # and slices extending past EOF can still return matching text.
            with sqlite3.connect(database) as connection:
                connection.execute("""
                    UPDATE entity_mentions SET character_start=4, character_end=6
                    WHERE mention_id='h1'
                """)
                connection.execute("""
                    UPDATE semantic_relation_candidates
                    SET sentence_start=-6, sentence_end=-1, evidence_text='由桂枝组成'
                    WHERE relation_id='r1'
                """)
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "relation evidence mismatch"):
                module.validate(database, output)

            with sqlite3.connect(database) as connection:
                connection.execute("""
                    UPDATE semantic_relation_candidates
                    SET sentence_start=0, sentence_end=14, evidence_text='桂枝汤由桂枝组成。'
                    WHERE relation_id='r1'
                """)
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "relation evidence mismatch"):
                module.validate(database, output)


    def test_exports_validated_passage_term_links_and_rejects_invalid_endpoints(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            mentions = root / "mentions.csv.gz"
            registry = root / "registry.csv"
            database = root / "search.sqlite3"
            output = root / "graph.jsonl.gz"
            source_text = "桂枝汤由桂枝组成。"

            def write_gzip(path, fields, rows):
                with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)

            write_gzip(content, db.CONTENT_FIELDS, [{
                "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                "block_id": "b1", "content_type": "PARAGRAPH", "characters": len(source_text),
                "content_text": source_text,
            }])
            write_gzip(mentions, db.ENTITY_FIELDS, [
                {"mention_id": "f1", "unit_id": "u1", "entity_type": "FORMULA",
                 "matched_text": "桂枝汤", "character_start": 0, "character_end": 3,
                 "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                 "block_id": "b1", "content_type": "PARAGRAPH", "section_path": "",
                 "lexicon_version": "1.3.0", "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
                {"mention_id": "h1", "unit_id": "u1", "entity_type": "HERB",
                 "matched_text": "桂枝", "character_start": 4, "character_end": 6,
                 "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                 "block_id": "b1", "content_type": "PARAGRAPH", "section_path": "",
                 "lexicon_version": "1.3.0", "extraction_method": "EXACT_LEXICON_MATCH",
                 "resolution_status": "UNRESOLVED_CANDIDATE"},
            ])
            with registry.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=db.ENTITY_REGISTRY_FIELDS)
                writer.writeheader()
                writer.writerows([
                    {"entity_id": "ef", "entity_type": "FORMULA", "preferred_label": "桂枝汤",
                     "lexical_form": "桂枝汤", "lexicon_version": "1.3.0",
                     "identity_status": "LEXICAL_ID_ONLY"},
                    {"entity_id": "eh", "entity_type": "HERB", "preferred_label": "桂枝",
                     "lexical_form": "桂枝", "lexicon_version": "1.3.0",
                     "identity_status": "LEXICAL_ID_ONLY"},
                ])
            db.build_database(content, None, database, mentions, None, registry)
            with sqlite3.connect(database) as connection:
                create_classical_source_tables(connection)
                connection.execute("""
                    INSERT INTO classical_source_documents VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    "sd1", "a.sy", "SHANG_HAN_LUN", "伤寒论", "a.sy", "", "倪海厦",
                    "第一篇 太阳篇", 1, "CLASSICAL_CHAPTER", "[\"伤寒论\",\"第一篇 太阳篇\"]",
                ))
                connection.execute("""
                    INSERT INTO classical_source_passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    "p1", "sd1", "a.sy", "SHANG_HAN_LUN", "hash", "0.0", "b1", "",
                    "PARAGRAPH", "", 0, len(source_text), source_text, "SENTENCE_OR_CLAUSE",
                ))
                connection.executemany("""
                    INSERT INTO classical_source_passage_mentions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, [
                    ("occ-f", "p1", "sd1", "ENTITY_MENTION", "f1", "ef", "FORMULA",
                     "桂枝汤", 0, 3, "[]", "UNRESOLVED_CANDIDATE"),
                    ("occ-h", "p1", "sd1", "ENTITY_MENTION", "h1", "eh", "HERB",
                     "桂枝", 4, 6, "[]", "UNRESOLVED_CANDIDATE"),
                ])
                connection.execute("""
                    INSERT INTO classical_source_passage_term_links VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    "link1", "p1", "SHANG_HAN_LUN", "a.sy", "CLASSICAL_CHAPTER",
                    "FORMULA|HERB", "SAME_PASSAGE_CO_OCCURRENCE", "occ-f", "occ-h",
                ))

            counts = module.export(database, output)
            self.assertEqual(counts["classical_source_passage_term_links"], 1)
            validated = module.validate(database, output)
            self.assertEqual(validated["validated_classical_source_passage_term_links"], 1)
            with gzip.open(output, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            link = next(row for row in rows if row["record_type"] == "CLASSICAL_SOURCE_PASSAGE_TERM_LINK")
            self.assertEqual(link, {
                "record_type": "CLASSICAL_SOURCE_PASSAGE_TERM_LINK", "link_id": "link1",
                "passage_id": "p1", "source_work": "SHANG_HAN_LUN", "document": "a.sy",
                "document_role": "CLASSICAL_CHAPTER", "pair_key": "FORMULA|HERB",
                "relation_type": "SAME_PASSAGE_CO_OCCURRENCE",
                "subject_occurrence_id": "occ-f", "object_occurrence_id": "occ-h",
            })

            # A link cannot point to an occurrence from another passage or invent
            # a type pair, even when its serialized fields otherwise match SQLite.
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE classical_source_passage_term_links SET object_occurrence_id='missing' "
                    "WHERE link_id='link1'"
                )
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "classical passage term link endpoint mismatch"):
                module.validate(database, output)

    def test_exports_contextual_terms_and_explicit_relation_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            contextual_terms = root / "contextual-terms.csv.gz"
            contextual_relations = root / "contextual-relations.csv"
            mentions = root / "mentions.csv.gz"
            database = root / "search.sqlite3"
            output = root / "graph.jsonl.gz"
            source_text = "症见头痛，辨证为太阳中风，治宜解表，方用桂枝汤。"

            def write_gzip(path, fields, rows):
                with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)

            write_gzip(content, db.CONTENT_FIELDS, [{
                "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                "block_id": "b1", "content_type": "PARAGRAPH", "characters": len(source_text),
                "content_text": source_text,
            }])
            term_fields = ["candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                "character_end", "evidence_start", "evidence_text", "classification_status"]
            write_gzip(contextual_terms, term_fields, [
                {"candidate_id": "sym-1", "term": "头痛", "candidate_type": "SYMPTOM",
                 "rule_id": "SYMPTOM_RULE", "evidence_document": "a.sy", "source_sha256": "hash",
                 "tree_position": "0.0", "block_id": "b1", "unit_id": "u1",
                 "character_start": 2, "character_end": 4, "evidence_start": 0,
                 "evidence_text": source_text, "classification_status": "CONTEXT_RULE_CANDIDATE"},
                {"candidate_id": "syn-1", "term": "太阳中风", "candidate_type": "SYNDROME",
                 "rule_id": "SYNDROME_RULE", "evidence_document": "a.sy", "source_sha256": "hash",
                 "tree_position": "0.0", "block_id": "b1", "unit_id": "u1",
                 "character_start": 8, "character_end": 12, "evidence_start": 0,
                 "evidence_text": source_text, "classification_status": "CONTEXT_RULE_CANDIDATE"},
                {"candidate_id": "treat-1", "term": "解表", "candidate_type": "TREATMENT",
                 "rule_id": "TREATMENT_RULE", "evidence_document": "a.sy", "source_sha256": "hash",
                 "tree_position": "0.0", "block_id": "b1", "unit_id": "u1",
                 "character_start": 15, "character_end": 17, "evidence_start": 0,
                 "evidence_text": source_text, "classification_status": "CONTEXT_RULE_CANDIDATE"},
            ])
            write_gzip(mentions, db.ENTITY_FIELDS, [{
                "mention_id": "formula-1", "unit_id": "u1", "entity_type": "FORMULA",
                "matched_text": "桂枝汤", "character_start": 20, "character_end": 23,
                "document": "a.sy", "source_sha256": "hash", "tree_position": "0.0",
                "block_id": "b1", "content_type": "PARAGRAPH", "section_path": "",
                "lexicon_version": "1.3.0", "extraction_method": "EXACT_LEXICON_MATCH",
                "resolution_status": "UNRESOLVED_CANDIDATE",
            }])
            ctx_r1_id = relation_identity(
                "SYMPTOM_TO_SYNDROME",
                {"candidate_id": "sym-1", "character_start": "2", "character_end": "4"},
                {"candidate_id": "syn-1", "character_start": "8", "character_end": "12"},
                "u1", 0, len(source_text),
            )
            ctx_r2_id = relation_identity(
                "TREATMENT_TO_FORMULA",
                {"candidate_id": "treat-1", "character_start": "15", "character_end": "17"},
                {"candidate_id": "formula-1", "character_start": "20", "character_end": "23"},
                "u1", 0, len(source_text),
            )
            relation_fields = ["relation_id", "predicate", "subject_candidate_id", "subject_text",
                "subject_type", "subject_start", "subject_end", "object_candidate_id", "object_text",
                "object_type", "object_start", "object_end", "unit_id", "document", "source_sha256",
                "tree_position", "block_id", "sentence_start", "sentence_end", "evidence_text",
                "predicate_text", "extraction_rule", "resolution_status"]
            with contextual_relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=relation_fields)
                writer.writeheader()
                writer.writerows([
                    {"relation_id": ctx_r1_id, "predicate": "SYMPTOM_TO_SYNDROME",
                     "subject_candidate_id": "sym-1", "subject_text": "头痛", "subject_type": "SYMPTOM",
                     "subject_start": 2, "subject_end": 4, "object_candidate_id": "syn-1",
                     "object_text": "太阳中风", "object_type": "SYNDROME", "object_start": 8,
                     "object_end": 12, "unit_id": "u1", "document": "a.sy", "source_sha256": "hash",
                     "tree_position": "0.0", "block_id": "b1", "sentence_start": 0,
                     "sentence_end": len(source_text), "evidence_text": source_text,
                     "predicate_text": "辨证为", "extraction_rule": "SYMPTOM_TO_SYNDROME_EXPLICIT_V1",
                     "resolution_status": "UNRESOLVED_CANDIDATE"},
                    {"relation_id": ctx_r2_id, "predicate": "TREATMENT_TO_FORMULA",
                     "subject_candidate_id": "treat-1", "subject_text": "解表", "subject_type": "TREATMENT",
                     "subject_start": 15, "subject_end": 17, "object_candidate_id": "formula-1",
                     "object_text": "桂枝汤", "object_type": "FORMULA", "object_start": 20,
                     "object_end": 23, "unit_id": "u1", "document": "a.sy", "source_sha256": "hash",
                     "tree_position": "0.0", "block_id": "b1", "sentence_start": 0,
                     "sentence_end": len(source_text), "evidence_text": source_text,
                     "predicate_text": "方用", "extraction_rule": "TREATMENT_TO_FORMULA_EXPLICIT_V1",
                     "resolution_status": "UNRESOLVED_CANDIDATE"},
                ])
            db.build_database(content, None, database, mentions, None, None, None,
                              contextual_terms, contextual_relations)
            counts = module.export(database, output)
            self.assertEqual(counts["contextual_term_candidates"], 3)
            self.assertEqual(counts["contextual_relation_edges"], 2)
            validated = module.validate(database, output)
            self.assertEqual(validated["validated_contextual_term_candidates"], 3)
            self.assertEqual(validated["validated_contextual_relation_edges"], 2)
            with gzip.open(output, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            edge = next(row for row in rows if row["record_type"] == "CONTEXTUAL_RELATION_CANDIDATE"
                         and row["predicate"] == "SYMPTOM_TO_SYNDROME")
            formula_edge = next(row for row in rows if row["record_type"] == "CONTEXTUAL_RELATION_CANDIDATE"
                                and row["predicate"] == "TREATMENT_TO_FORMULA")
            self.assertEqual(edge["subject_text"], "头痛")
            self.assertEqual(edge["object_text"], "太阳中风")
            self.assertEqual(formula_edge["subject_text"], "解表")
            self.assertEqual(formula_edge["object_text"], "桂枝汤")
            self.assertEqual(formula_edge["object_candidate_id"], "formula-1")
            self.assertEqual(edge["evidence"]["text"], source_text)

            # Contextual term evidence offsets are absolute source positions and
            # must be bounded before source slicing.
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE contextual_term_type_candidates SET evidence_start=-1 WHERE candidate_id='sym-1'"
                )
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "contextual term evidence mismatch"):
                module.validate(database, output)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE contextual_term_type_candidates SET evidence_start=0 WHERE candidate_id='sym-1'"
                )
            module.export(database, output)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE contextual_term_type_candidates SET evidence_start=? WHERE candidate_id='sym-1'",
                    (len(source_text),),
                )
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "contextual term evidence mismatch"):
                module.validate(database, output)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE contextual_term_type_candidates SET evidence_start=0 WHERE candidate_id='sym-1'"
                )
            module.export(database, output)

            # Graph validation independently checks the explicit predicate against source text,
            # rather than relying only on graph/SQLite field equality.
            connection = __import__("sqlite3").connect(database)
            connection.execute(
                "UPDATE contextual_relation_candidates SET predicate_text=? WHERE relation_id=?",
                ("证属", ctx_r1_id),
            )
            connection.commit()
            connection.close()
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "contextual relation predicate evidence mismatch"):
                module.validate(database, output)

            connection = __import__("sqlite3").connect(database)
            connection.execute(
                "UPDATE contextual_relation_candidates SET predicate_text=? WHERE relation_id=?",
                ("辨证为", ctx_r1_id),
            )
            connection.commit()
            connection.close()
            module.export(database, output)

            # Contextual relation evidence must reject negative and out-of-range
            # offsets before Python's permissive slicing can accept them.
            connection = __import__("sqlite3").connect(database)
            connection.execute(
                "UPDATE contextual_relation_candidates SET sentence_start=-length(evidence_text), "
                "sentence_end=-1 WHERE relation_id=?",
                (ctx_r1_id,),
            )
            connection.commit()
            connection.close()
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "contextual relation evidence mismatch"):
                module.validate(database, output)

            connection = __import__("sqlite3").connect(database)
            connection.execute(
                "UPDATE contextual_relation_candidates SET sentence_start=0, "
                "sentence_end=? WHERE relation_id=?",
                (len(source_text) + 1, ctx_r1_id),
            )
            connection.commit()
            connection.close()
            module.export(database, output)
            with self.assertRaisesRegex(ValueError, "contextual relation evidence mismatch"):
                module.validate(database, output)

            connection = __import__("sqlite3").connect(database)
            connection.execute(
                "UPDATE contextual_relation_candidates SET sentence_start=0, "
                "sentence_end=?, evidence_text=? WHERE relation_id=?",
                (len(source_text), source_text, ctx_r1_id),
            )
            connection.commit()
            connection.close()
            module.export(database, output)

            # Tampering with contextual classification metadata must be rejected.
            term = next(row for row in rows if row["record_type"] == "CONTEXTUAL_TERM_CANDIDATE")
            term["rule_id"] = "TAMPERED_RULE"
            with gzip.open(output, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "contextual term graph/SQLite mismatch"):
                module.validate(database, output)

            term["rule_id"] = "SYMPTOM_RULE"
            with gzip.open(output, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            edge["subject_candidate_id"] = "missing-candidate"
            with gzip.open(output, "wt", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            with self.assertRaisesRegex(ValueError, "graph/SQLite mismatch"):
                module.validate(database, output)

    def test_writes_machine_readable_validation_report(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "semantic_graph_validation.json"
            module.write_validation_report(path, {
                "validated_entity_nodes": 12,
                "validated_relation_edges": 3,
                "validated_contextual_term_candidates": 4,
                "validated_contextual_relation_edges": 0,
            })
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["validated_entity_nodes"], 12)
            self.assertEqual(report["validated_relation_edges"], 3)
            self.assertEqual(report["validated_contextual_term_candidates"], 4)
            self.assertEqual(report["validated_contextual_relation_edges"], 0)

if __name__ == "__main__":
    unittest.main()
