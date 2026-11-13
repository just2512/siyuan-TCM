import csv
import gzip
import importlib.util
import tempfile
import unittest
from pathlib import Path

from build_contextual_relation_candidates import relation_identity
import build_siyuan_search_db as db

MODULE_PATH = Path(__file__).with_name("export_semantic_graph.py")
SPEC = importlib.util.spec_from_file_location("export_semantic_graph_source_note_test", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(module)


class SourceNoteSemanticGraphTests(unittest.TestCase):
    def test_exports_source_note_point_symptom_link_with_resolvable_endpoint_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content_path = root / "content.csv.gz"
            mentions_path = root / "mentions.csv.gz"
            terms_path = root / "terms.csv.gz"
            relations_path = root / "contextual-relations.csv"
            database = root / "search.sqlite3"
            graph = root / "graph.jsonl.gz"
            source = "中脘穴：胃痛。"
            document, sha, tree, block, unit = "note/a.sy", "sha-a", "0.1", "b1", "u1"

            with gzip.open(content_path, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=db.CONTENT_FIELDS)
                writer.writeheader()
                writer.writerow({
                    "document": document, "source_sha256": sha, "tree_position": tree,
                    "block_id": block, "parent_block_id": "", "parent_node_type": "",
                    "content_type": "PARAGRAPH", "heading_level": "", "section_path": "",
                    "section_heading_block_ids": "", "characters": len(source), "content_text": source,
                })

            with gzip.open(mentions_path, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=db.ENTITY_FIELDS)
                writer.writeheader()
                writer.writerow({
                    "mention_id": "point-mention-1", "unit_id": unit, "entity_type": "POINT",
                    "matched_text": "中脘穴", "character_start": 0, "character_end": 3,
                    "document": document, "source_sha256": sha, "tree_position": tree,
                    "block_id": block, "content_type": "PARAGRAPH", "section_path": "",
                    "lexicon_version": "1.3.0", "extraction_method": "EXACT_LEXICON_MATCH",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })

            term_fields = [
                "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
                "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
                "character_end", "evidence_start", "evidence_text", "classification_status",
            ]
            with gzip.open(terms_path, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=term_fields)
                writer.writeheader()
                writer.writerow({
                    "candidate_id": "symptom-candidate-1", "term": "胃痛",
                    "candidate_type": "SYMPTOM", "rule_id": "SYMPTOM_CONTEXT_02",
                    "evidence_document": document, "source_sha256": sha, "tree_position": tree,
                    "block_id": block, "unit_id": unit, "character_start": 4, "character_end": 6,
                    "evidence_start": 0, "evidence_text": source,
                    "classification_status": "CONTEXT_RULE_CANDIDATE",
                })

            relation_fields = [
                "relation_id", "predicate", "subject_candidate_id", "subject_text", "subject_type",
                "subject_start", "subject_end", "object_candidate_id", "object_text", "object_type",
                "object_start", "object_end", "unit_id", "document", "source_sha256", "tree_position",
                "block_id", "sentence_start", "sentence_end", "evidence_text", "predicate_text",
                "extraction_rule", "resolution_status",
            ]
            subject = {"candidate_id": "point-mention-1", "character_start": "0", "character_end": "3"}
            obj = {"candidate_id": "symptom-candidate-1", "character_start": "4", "character_end": "6"}
            relation_id = relation_identity("SOURCE_NOTE_ASSOCIATES", subject, obj, unit, 0, len(source))
            with relations_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=relation_fields)
                writer.writeheader()
                writer.writerow({
                    "relation_id": relation_id, "predicate": "SOURCE_NOTE_ASSOCIATES",
                    "subject_candidate_id": "point-mention-1", "subject_text": "中脘穴",
                    "subject_type": "POINT", "subject_start": 0, "subject_end": 3,
                    "object_candidate_id": "symptom-candidate-1", "object_text": "胃痛",
                    "object_type": "SYMPTOM", "object_start": 4, "object_end": 6,
                    "unit_id": unit, "document": document, "source_sha256": sha,
                    "tree_position": tree, "block_id": block, "sentence_start": 0,
                    "sentence_end": len(source), "evidence_text": source, "predicate_text": "：",
                    "extraction_rule": "SOURCE_NOTE_ASSOCIATES_LABEL_V1",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })

            db.build_database(
                content_path, None, database, mentions_path, None, None, None, terms_path, relations_path
            )
            counts = module.export(database, graph)
            self.assertEqual(counts["contextual_term_candidates"], 1)
            self.assertEqual(counts["contextual_relation_edges"], 1)
            self.assertEqual(counts["entity_nodes"], 1)
            validated = module.validate(database, graph)
            self.assertEqual(validated["validated_contextual_relation_edges"], 1)
            with gzip.open(graph, "rt", encoding="utf-8") as stream:
                rows = [__import__("json").loads(line) for line in stream]
            edge = next(row for row in rows if row["record_type"] == "CONTEXTUAL_RELATION_CANDIDATE")
            self.assertEqual(edge["subject_type"], "POINT")
            self.assertEqual(edge["object_type"], "SYMPTOM")
            self.assertEqual(edge["subject_candidate_id"], "point-mention-1")
            self.assertEqual(edge["evidence"]["text"], source)


if __name__ == "__main__":
    unittest.main()
