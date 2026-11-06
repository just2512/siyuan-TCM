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


if __name__ == "__main__":
    unittest.main()
