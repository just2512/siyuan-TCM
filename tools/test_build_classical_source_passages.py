import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_classical_source_passages import build


def hierarchy_rows():
    shanghan = "shanghan.sy"
    shanghan_chapter = "shanghan/太阳.sy"
    formula_index = "shanghan/方剂.sy"
    formula_note = "shanghan/方剂/【桂枝汤】.sy"
    neijing = "neijing.sy"
    neijing_chapter = "neijing/阴阳应象大论.sy"
    return [
        {
            "document": shanghan, "parent_document": "", "notebook": "倪海厦",
            "title": "伤寒论", "document_depth": "0", "child_document_count": "2",
            "structure_role": "CONTAINER",
        },
        {
            "document": shanghan_chapter, "parent_document": shanghan, "notebook": "倪海厦",
            "title": "太阳篇", "document_depth": "1", "child_document_count": "0",
            "structure_role": "LEAF",
        },
        {
            "document": formula_index, "parent_document": shanghan, "notebook": "倪海厦",
            "title": "方剂", "document_depth": "1", "child_document_count": "1",
            "structure_role": "CONTAINER",
        },
        {
            "document": formula_note, "parent_document": formula_index, "notebook": "倪海厦",
            "title": "【桂枝汤】", "document_depth": "2", "child_document_count": "0",
            "structure_role": "LEAF",
        },
        {
            "document": neijing, "parent_document": "", "notebook": "书籍",
            "title": "《黄帝内经》", "document_depth": "0", "child_document_count": "1",
            "structure_role": "CONTAINER",
        },
        {
            "document": neijing_chapter, "parent_document": neijing, "notebook": "书籍",
            "title": "第五篇 阴阳应象大论", "document_depth": "1", "child_document_count": "0",
            "structure_role": "LEAF",
        },
    ]


def write_hierarchy(path: Path):
    import csv
    rows = hierarchy_rows()
    fields = [
        "document", "parent_document", "notebook", "title", "document_depth",
        "child_document_count", "structure_role",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def create_fixture_database(path: Path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE content_blocks (
            id INTEGER PRIMARY KEY, document TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            tree_position TEXT NOT NULL, block_id TEXT, parent_block_id TEXT,
            parent_node_type TEXT, content_type TEXT NOT NULL, heading_level TEXT,
            section_path TEXT, section_heading_block_ids TEXT, characters INTEGER NOT NULL,
            content_text TEXT NOT NULL
        );
        CREATE TABLE entity_mentions (
            mention_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, entity_type TEXT NOT NULL,
            matched_text TEXT NOT NULL, character_start INTEGER NOT NULL,
            character_end INTEGER NOT NULL, document TEXT NOT NULL,
            source_sha256 TEXT NOT NULL, tree_position TEXT NOT NULL,
            block_id TEXT, resolution_status TEXT
        );
        CREATE TABLE contextual_term_type_candidates (
            candidate_id TEXT NOT NULL, term TEXT NOT NULL, candidate_type TEXT NOT NULL,
            rule_id TEXT NOT NULL, evidence_document TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            tree_position TEXT NOT NULL, block_id TEXT, unit_id TEXT,
            character_start INTEGER NOT NULL, character_end INTEGER NOT NULL
        );
        CREATE TABLE node_relationships (
            id INTEGER PRIMARY KEY, source_document TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            source_tree_position TEXT NOT NULL, source_block_id TEXT, source_node_type TEXT,
            relation_type TEXT NOT NULL, target TEXT NOT NULL, target_subtype TEXT,
            target_document TEXT, resolution TEXT NOT NULL
        );
    """)
    sources = {
        "shanghan/太阳.sy": (
            "太阳病，头项强痛而恶寒，桂枝汤主之。太阳病复见发热。",
            "sha-sh", "0.1", "b-sh",
        ),
        "shanghan/方剂/【桂枝汤】.sy": (
            "桂枝汤：桂枝、芍药、桂枝再加。",
            "sha-formula", "0.1", "b-formula",
        ),
        "neijing/阴阳应象大论.sy": (
            "阴阳应象大论曰：阴阳者，天地之道也。",
            "sha-nei", "0.1", "b-nei",
        ),
    }
    for document, (text, sha, tree, block) in sources.items():
        connection.execute("""
            INSERT INTO content_blocks (
                document, source_sha256, tree_position, block_id, parent_block_id,
                parent_node_type, content_type, heading_level, section_path,
                section_heading_block_ids, characters, content_text
            ) VALUES (?, ?, ?, ?, '', '', 'PARAGRAPH', '', '', '', ?, ?)
        """, (document, sha, tree, block, len(text), text))

    def add_entity(mention_id, entity_id, entity_type, term, document):
        text, sha, tree, block = sources[document]
        if mention_id in {"herb-1", "herb-2"}:
            first_ingredient = text.index("：") + 1
            start = text.index(term, first_ingredient)
            if mention_id == "herb-2":
                start = text.index(term, start + len(term))
        else:
            start = text.index(term)
        connection.execute("""
            INSERT INTO entity_mentions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mention_id, entity_id, entity_type, term, start, start + len(term),
            document, sha, tree, block, "UNRESOLVED_CANDIDATE",
        ))

    add_entity("formula-mention", "formula-gui-zhi", "FORMULA", "桂枝汤", "shanghan/方剂/【桂枝汤】.sy")
    add_entity("herb-1", "herb-gui-zhi", "HERB", "桂枝", "shanghan/方剂/【桂枝汤】.sy")
    add_entity("herb-2", "herb-gui-zhi", "HERB", "桂枝", "shanghan/方剂/【桂枝汤】.sy")
    add_entity("herb-shao-yao", "herb-shao-yao", "HERB", "芍药", "shanghan/方剂/【桂枝汤】.sy")

    text, sha, tree, block = sources["shanghan/太阳.sy"]
    for candidate_id, term, candidate_type, start in (
        ("symptom-cold", "恶寒", "SYMPTOM", text.index("恶寒")),
        ("formula-candidate", "桂枝汤", "FORMULA", text.index("桂枝汤")),
        # Deliberately spans two clauses: retain upstream, but do not make a
        # passage backlink that would cross an evidence boundary.
        ("cross-clause", "主之。太阳病", "SYMPTOM", text.index("主之")),
    ):
        connection.execute("""
            INSERT INTO contextual_term_type_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidate_id, term, candidate_type, candidate_type + "_RULE",
            "shanghan/太阳.sy", sha, tree, block, "unit-shanghan",
            start, start + len(term),
        ))

    connection.execute("""
        INSERT INTO node_relationships (
            source_document, source_sha256, source_tree_position, source_block_id,
            source_node_type, relation_type, target, target_subtype,
            target_document, resolution
        ) VALUES (?, ?, ?, ?, 'NodeTextMark', 'BLOCK_REFERENCE', ?, 'd', ?, 'RESOLVED_IN_CORPUS')
    """, (
        "shanghan/太阳.sy", sources["shanghan/太阳.sy"][1], "0.1", "b-sh",
        "b-nei", "neijing/阴阳应象大论.sy",
    ))
    connection.commit()
    connection.close()


class ClassicalSourcePassageBuilderTests(unittest.TestCase):
    def test_builds_work_chapter_passages_occurrences_and_native_references(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "search.sqlite3"
            hierarchy = root / "document_hierarchy.csv"
            report = root / "classical_source_passage_audit.json"
            create_fixture_database(database)
            write_hierarchy(hierarchy)

            result = build(database, hierarchy, report)

            self.assertEqual(result["source_documents"], 6)
            self.assertEqual(result["source_documents_by_work"], {
                "HUANG_DI_NEI_JING": 2,
                "SHANG_HAN_LUN": 4,
            })
            self.assertEqual(result["native_classical_document_references"], 1)
            self.assertEqual(result["entity_mention_occurrences"], 4)
            self.assertEqual(result["contextual_term_occurrences"], 2)
            self.assertEqual(result["unassigned_contextual_terms_outside_single_passage"], 1)
            self.assertEqual(
                result["source_passages_by_role_and_work"]["SHANG_HAN_LUN"]["CLASSICAL_CHAPTER"],
                2,
            )
            self.assertEqual(
                result["source_passages_by_role_and_work"]["SHANG_HAN_LUN"]["FORMULA_REFERENCE"],
                2,
            )
            self.assertEqual(
                result["same_passage_cooccurrences_by_work"]["SHANG_HAN_LUN"]["SYMPTOM|FORMULA"],
                1,
            )
            self.assertEqual(
                result["same_passage_cooccurrences_by_work"]["SHANG_HAN_LUN"]["FORMULA|HERB"],
                1,
            )
            shanghan_example = result["same_passage_cooccurrence_examples_by_work"][
                "SHANG_HAN_LUN"
            ]["SYMPTOM|FORMULA"][0]
            self.assertEqual(
                shanghan_example["passage_text"],
                "太阳病，头项强痛而恶寒，桂枝汤主之。",
            )
            self.assertEqual(
                result["passages_with_term_type_by_work"]["SHANG_HAN_LUN"]["SYMPTOM"],
                1,
            )
            self.assertEqual(
                result["same_passage_occurrence_links_by_role_and_work"]
                ["SHANG_HAN_LUN"]["CLASSICAL_CHAPTER"]["SYMPTOM|FORMULA"],
                1,
            )
            self.assertEqual(
                result["same_passage_occurrence_links_by_role_and_work"]
                ["SHANG_HAN_LUN"]["FORMULA_REFERENCE"]["FORMULA|HERB"],
                3,
            )


            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            docs = {
                row["document"]: row
                for row in connection.execute("SELECT * FROM classical_source_documents")
            }
            formula_doc = docs["shanghan/方剂/【桂枝汤】.sy"]
            self.assertEqual(formula_doc["source_work"], "SHANG_HAN_LUN")
            self.assertEqual(formula_doc["document_role"], "FORMULA_REFERENCE")
            self.assertEqual(json.loads(formula_doc["chapter_path_json"]), [
                "伤寒论", "方剂", "【桂枝汤】",
            ])

            repeated = connection.execute("""
                SELECT character_start, character_end, term_text
                FROM classical_source_passage_mentions
                WHERE reference_kind='ENTITY_MENTION' AND reference_id IN ('herb-1', 'herb-2')
                ORDER BY character_start
            """).fetchall()
            self.assertEqual(len(repeated), 2)
            self.assertNotEqual(repeated[0]["character_start"], repeated[1]["character_start"])
            self.assertEqual([row["term_text"] for row in repeated], ["桂枝", "桂枝"])

            links = connection.execute("""
                SELECT l.*, s.term_type AS subject_type, s.term_text AS subject_text,
                       s.character_start AS subject_start, s.character_end AS subject_end,
                       o.term_type AS object_type, o.term_text AS object_text,
                       o.character_start AS object_start, o.character_end AS object_end,
                       p.document, p.source_sha256, p.tree_position, p.block_id,
                       p.character_start AS passage_start, p.character_end AS passage_end,
                       p.passage_text, d.document_role
                FROM classical_source_passage_term_links l
                JOIN classical_source_passage_mentions s ON s.occurrence_id=l.subject_occurrence_id
                JOIN classical_source_passage_mentions o ON o.occurrence_id=l.object_occurrence_id
                JOIN classical_source_passages p ON p.passage_id=l.passage_id
                JOIN classical_source_documents d ON d.source_document_id=p.source_document_id
                ORDER BY l.pair_key, s.character_start, o.character_start
            """).fetchall()
            self.assertEqual(len(links), 4)
            self.assertTrue(all(row["relation_type"] == "SAME_PASSAGE_CO_OCCURRENCE" for row in links))
            self.assertTrue(any(
                row["subject_type"] == "SYMPTOM" and row["subject_text"] == "恶寒"
                and row["object_type"] == "FORMULA" and row["object_text"] == "桂枝汤"
                and row["document_role"] == "CLASSICAL_CHAPTER"
                for row in links
            ))
            formula_herb_links = [row for row in links if row["pair_key"] == "FORMULA|HERB"]
            self.assertEqual(len(formula_herb_links), 3)
            self.assertEqual(
                [row["object_text"] for row in formula_herb_links],
                ["桂枝", "芍药", "桂枝"],
            )
            self.assertNotEqual(
                formula_herb_links[0]["object_start"], formula_herb_links[2]["object_start"]
            )
            for row in links:
                source = connection.execute("""
                    SELECT content_text FROM content_blocks
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=?
                """, (row["document"], row["source_sha256"], row["tree_position"], row["block_id"])).fetchone()
                self.assertIsNotNone(source)
                self.assertEqual(
                    source["content_text"][row["passage_start"]:row["passage_end"]],
                    row["passage_text"],
                )
                self.assertEqual(
                    source["content_text"][row["subject_start"]:row["subject_end"]],
                    row["subject_text"],
                )
                self.assertEqual(
                    source["content_text"][row["object_start"]:row["object_end"]],
                    row["object_text"],
                )

            ref = connection.execute("""
                SELECT source_document, target_document, target_block_id, relation_type, resolution
                FROM classical_source_document_references
            """).fetchone()
            self.assertEqual(ref["source_document"], "shanghan/太阳.sy")
            self.assertEqual(ref["target_document"], "neijing/阴阳应象大论.sy")
            self.assertEqual(ref["target_block_id"], "b-nei")
            self.assertEqual(ref["relation_type"], "BLOCK_REFERENCE")
            self.assertEqual(ref["resolution"], "RESOLVED_IN_CORPUS")

            # Every generated passage is the exact source slice at its locator.
            for row in connection.execute("SELECT * FROM classical_source_passages"):
                source = connection.execute("""
                    SELECT content_text FROM content_blocks
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=?
                """, (row["document"], row["source_sha256"], row["tree_position"], row["block_id"])).fetchone()
                self.assertIsNotNone(source)
                self.assertEqual(
                    source["content_text"][row["character_start"]:row["character_end"]],
                    row["passage_text"],
                )
            connection.close()

            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), result)

    def test_rejects_source_occurrence_with_wrong_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "search.sqlite3"
            hierarchy = root / "document_hierarchy.csv"
            report = root / "report.json"
            create_fixture_database(database)
            write_hierarchy(hierarchy)
            connection = sqlite3.connect(database)
            connection.execute("""
                UPDATE contextual_term_type_candidates SET term='错误词'
                WHERE candidate_id='symptom-cold'
            """)
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(ValueError, "contextual term source mismatch"):
                build(database, hierarchy, report)

    def test_rejects_hierarchy_parent_cycle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hierarchy = root / "document_hierarchy.csv"
            rows = hierarchy_rows()
            rows[1]["parent_document"] = rows[2]["document"]
            rows[2]["parent_document"] = rows[1]["document"]
            import csv
            with hierarchy.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            from build_classical_source_passages import read_hierarchy, source_document_rows
            with self.assertRaisesRegex(ValueError, "cycle"):
                source_document_rows(read_hierarchy(hierarchy))


if __name__ == "__main__":
    unittest.main()
