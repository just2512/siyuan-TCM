import csv
import gzip
import importlib.util
import json
import tempfile
import unittest
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
            self.assertEqual(result, {"entity_nodes": 2, "relation_edges": 1})
            self.assertEqual(module.validate(database, output), {
                "validated_entity_nodes": 2, "validated_relation_edges": 1
            })
            with gzip.open(output, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            edge = next(row for row in rows if row["record_type"] == "RELATION_CANDIDATE")
            self.assertEqual(edge["subject_entity_id"], "ef")
            self.assertEqual(edge["object_entity_id"], "eh")
            self.assertEqual(edge["evidence"]["text"], "桂枝汤由桂枝组成。")


    def test_exports_contextual_terms_and_explicit_relation_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content.csv.gz"
            contextual_terms = root / "contextual-terms.csv.gz"
            contextual_relations = root / "contextual-relations.csv"
            database = root / "search.sqlite3"
            output = root / "graph.jsonl.gz"
            source_text = "症见头痛，辨证为太阳中风。"
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
            ])
            relation_fields = ["relation_id", "predicate", "subject_candidate_id", "subject_text",
                "subject_type", "subject_start", "subject_end", "object_candidate_id", "object_text",
                "object_type", "object_start", "object_end", "unit_id", "document", "source_sha256",
                "tree_position", "block_id", "sentence_start", "sentence_end", "evidence_text",
                "predicate_text", "extraction_rule", "resolution_status"]
            with contextual_relations.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=relation_fields)
                writer.writeheader()
                writer.writerow({"relation_id": "ctx-r1", "predicate": "SYMPTOM_TO_SYNDROME",
                    "subject_candidate_id": "sym-1", "subject_text": "头痛", "subject_type": "SYMPTOM",
                    "subject_start": 2, "subject_end": 4, "object_candidate_id": "syn-1",
                    "object_text": "太阳中风", "object_type": "SYNDROME", "object_start": 8,
                    "object_end": 12, "unit_id": "u1", "document": "a.sy", "source_sha256": "hash",
                    "tree_position": "0.0", "block_id": "b1", "sentence_start": 0,
                    "sentence_end": len(source_text), "evidence_text": source_text,
                    "predicate_text": "辨证为", "extraction_rule": "SYMPTOM_TO_SYNDROME_EXPLICIT_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE"})
            db.build_database(content, None, database, None, None, None, None, contextual_terms, contextual_relations)
            counts = module.export(database, output)
            self.assertEqual(counts["contextual_term_candidates"], 2)
            self.assertEqual(counts["contextual_relation_edges"], 1)
            validated = module.validate(database, output)
            self.assertEqual(validated["validated_contextual_term_candidates"], 2)
            self.assertEqual(validated["validated_contextual_relation_edges"], 1)
            with gzip.open(output, "rt", encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
            edge = next(row for row in rows if row["record_type"] == "CONTEXTUAL_RELATION_CANDIDATE")
            self.assertEqual(edge["subject_text"], "头痛")
            self.assertEqual(edge["object_text"], "太阳中风")
            self.assertEqual(edge["evidence"]["text"], source_text)
if __name__ == "__main__":
    unittest.main()
