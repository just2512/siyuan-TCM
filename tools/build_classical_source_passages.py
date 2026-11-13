#!/usr/bin/env python3
"""Build source-work, passage, mention-occurrence and native-reference tables.

This layer is navigational only. A mention inside a passage is not interpreted
as a treatment, efficacy, diagnosis, or theory relation. All spans stay tied to
the exact exported source document, SHA-256, tree position and block locator.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from build_contextual_relation_candidates import sentence_ranges

WORK_ROOTS = {
    ("倪海厦", "伤寒论"): ("SHANG_HAN_LUN", "伤寒论"),
    ("倪海厦", "金匮要略"): ("JIN_GUI_YAO_LUE", "金匮要略"),
    ("倪海厦", "黄帝内经"): ("HUANG_DI_NEI_JING", "黄帝内经"),
    ("书籍", "《黄帝内经》"): ("HUANG_DI_NEI_JING", "黄帝内经"),
    ("倪海厦", "针灸大成"): ("ZHEN_JIU_DA_CHENG", "针灸大成"),
}
AUXILIARY_TITLES = {"素材", "素材&笔记", "素材&amp;笔记", "方便法门", "笔记", "视频同步文字"}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    return digest("\0".join((prefix, *(str(part) for part in parts))))


def read_hierarchy(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "document", "parent_document", "notebook", "title",
            "document_depth", "child_document_count", "structure_role",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("document hierarchy missing fields: " + ", ".join(sorted(missing)))
        rows = list(reader)
    by_document: dict[str, dict[str, str]] = {}
    for line, row in enumerate(rows, 2):
        document = row["document"].strip()
        if not document:
            raise ValueError(f"document hierarchy row {line}: empty document path")
        if document in by_document:
            raise ValueError(f"document hierarchy row {line}: duplicate document path {document}")
        by_document[document] = row
    for row in rows:
        parent = row["parent_document"].strip()
        if parent and parent not in by_document:
            raise ValueError(f"document hierarchy has missing parent: {row['document']} -> {parent}")
    return rows


def source_document_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_document = {row["document"]: row for row in rows}
    roots: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        work = WORK_ROOTS.get((row["notebook"], row["title"]))
        if work:
            if row["parent_document"]:
                raise ValueError(f"classical source root unexpectedly has a parent: {row['document']}")
            roots[row["document"]] = (work[0], work[1], row["notebook"])

    if not roots:
        raise ValueError("no supported classical source roots found in document_hierarchy.csv")

    resolved: list[dict[str, Any]] = []
    for row in rows:
        chain: list[dict[str, str]] = []
        path = row["document"]
        seen: set[str] = set()
        while path:
            if path in seen:
                raise ValueError(f"document hierarchy cycle at {path}")
            seen.add(path)
            current = by_document[path]
            chain.append(current)
            path = current["parent_document"]
        chain.reverse()
        root = chain[0]
        if root["document"] not in roots:
            continue

        source_work, work_label, notebook = roots[root["document"]]
        relative = chain[1:]
        relative_titles = [item["title"] for item in relative]
        current_title = row["title"]
        in_formula_collection = "方剂" in relative_titles
        if row["document"] == root["document"]:
            role = "WORK_ROOT"
        elif in_formula_collection and current_title != "方剂":
            role = "FORMULA_REFERENCE"
        elif current_title in AUXILIARY_TITLES:
            role = "AUXILIARY_NOTE"
        elif any(title.startswith("注解") for title in relative_titles):
            role = "COMMENTARY"
        elif current_title == "方剂":
            role = "FORMULA_COLLECTION"
        elif int(row["child_document_count"] or 0) > 0:
            role = "SECTION_CONTAINER"
        elif re.match(r"^第[一二三四五六七八九十百零〇两0-9]+[篇章节]", current_title):
            role = "CLASSICAL_CHAPTER"
        else:
            role = "SOURCE_NOTE"

        chapter_path = [root["title"], *relative_titles]
        resolved.append({
            "source_document_id": stable_id("CLASSICAL_SOURCE_DOCUMENT", row["document"]),
            "document": row["document"],
            "source_work": source_work,
            "source_work_label": work_label,
            "root_document": root["document"],
            "parent_document": row["parent_document"],
            "notebook": notebook,
            "title": current_title,
            "document_depth": int(row["document_depth"] or 0),
            "document_role": role,
            "chapter_path_json": json.dumps(chapter_path, ensure_ascii=False, separators=(",", ":")),
        })
    return resolved


def create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        DROP TABLE IF EXISTS classical_source_document_references;
        DROP TABLE IF EXISTS classical_source_passage_mentions;
        DROP TABLE IF EXISTS classical_source_passages;
        DROP TABLE IF EXISTS classical_source_documents;

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

        CREATE INDEX idx_classical_source_work
            ON classical_source_documents(source_work, document_role);
        CREATE INDEX idx_classical_passage_document
            ON classical_source_passages(document, tree_position, character_start);
        CREATE INDEX idx_classical_passage_mentions_type
            ON classical_source_passage_mentions(term_type, term_text);
        CREATE INDEX idx_classical_passage_mentions_passage
            ON classical_source_passage_mentions(passage_id, character_start);
        CREATE INDEX idx_classical_document_refs_source
            ON classical_source_document_references(source_document_id);
        CREATE INDEX idx_classical_document_refs_target
            ON classical_source_document_references(target_document_id);
    """)


def build(database_path: Path, hierarchy_path: Path, report_path: Path) -> dict[str, Any]:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    hierarchy = read_hierarchy(hierarchy_path)
    documents = source_document_rows(hierarchy)
    if not documents:
        raise ValueError("supported source roots have no descendant documents")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        required_tables = {"content_blocks", "entity_mentions", "contextual_term_type_candidates", "node_relationships"}
        existing_tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = required_tables - existing_tables
        if missing:
            raise ValueError("search database missing tables: " + ", ".join(sorted(missing)))
        create_tables(connection)
        connection.executemany("""
            INSERT INTO classical_source_documents (
                source_document_id, document, source_work, source_work_label,
                root_document, parent_document, notebook, title, document_depth,
                document_role, chapter_path_json
            ) VALUES (
                :source_document_id, :document, :source_work, :source_work_label,
                :root_document, :parent_document, :notebook, :title, :document_depth,
                :document_role, :chapter_path_json
            )
        """, documents)

        doc_index = {row["document"]: row for row in documents}
        passage_count = entity_occurrence_count = contextual_occurrence_count = 0
        unassigned_entity_mentions = unassigned_contextual_terms = 0
        passage_insert: list[tuple[Any, ...]] = []
        mention_insert: list[tuple[Any, ...]] = []
        for doc in documents:
            locator_rows = connection.execute("""
                SELECT document, source_sha256, tree_position, block_id,
                       parent_block_id, content_type, section_path, content_text
                FROM content_blocks
                WHERE document=?
                ORDER BY tree_position, block_id
            """, (doc["document"],)).fetchall()
            for block in locator_rows:
                text = block["content_text"] or ""
                if not text:
                    continue
                spans = list(sentence_ranges(text))
                if not spans:
                    continue
                entity_rows = connection.execute("""
                    SELECT mention_id, entity_id, entity_type, matched_text,
                           character_start, character_end, resolution_status
                    FROM entity_mentions
                    WHERE document=? AND source_sha256=? AND tree_position=? AND block_id=?
                    ORDER BY character_start, character_end, mention_id
                """, (block["document"], block["source_sha256"], block["tree_position"], block["block_id"])).fetchall()
                contextual_rows = connection.execute("""
                    SELECT candidate_id, term, candidate_type,
                           character_start, character_end,
                           GROUP_CONCAT(DISTINCT rule_id) AS rule_ids
                    FROM contextual_term_type_candidates
                    WHERE evidence_document=? AND source_sha256=? AND tree_position=? AND block_id=?
                    GROUP BY candidate_id, term, candidate_type, character_start, character_end
                    ORDER BY character_start, character_end, candidate_type, candidate_id
                """, (block["document"], block["source_sha256"], block["tree_position"], block["block_id"])).fetchall()

                for start, end in spans:
                    passage_text = text[start:end]
                    if not passage_text.strip():
                        continue
                    passage_id = stable_id(
                        "CLASSICAL_SOURCE_PASSAGE",
                        doc["source_document_id"], block["source_sha256"],
                        block["tree_position"], block["block_id"], start, end,
                    )
                    passage_insert.append((
                        passage_id, doc["source_document_id"], block["document"], doc["source_work"],
                        block["source_sha256"], block["tree_position"], block["block_id"],
                        block["parent_block_id"] or "", block["content_type"] or "",
                        block["section_path"] or "", start, end, passage_text, "SENTENCE_OR_CLAUSE",
                    ))
                    passage_count += 1

                    for mention in entity_rows:
                        left, right = int(mention["character_start"]), int(mention["character_end"])
                        if not (start <= left < right <= end):
                            continue
                        if text[left:right] != mention["matched_text"]:
                            raise ValueError(
                                f"entity mention source mismatch: {block['document']}:{left}-{right}"
                            )
                        occurrence_id = stable_id(
                            "CLASSICAL_SOURCE_PASSAGE_MENTION", passage_id, "ENTITY_MENTION",
                            mention["mention_id"], mention["entity_type"], left, right,
                        )
                        mention_insert.append((
                            occurrence_id, passage_id, doc["source_document_id"], "ENTITY_MENTION",
                            mention["mention_id"], mention["entity_id"], mention["entity_type"],
                            mention["matched_text"], left, right, "[]",
                            mention["resolution_status"] or "UNRESOLVED_CANDIDATE",
                        ))
                        entity_occurrence_count += 1

                    for candidate in contextual_rows:
                        left, right = int(candidate["character_start"]), int(candidate["character_end"])
                        if not (start <= left < right <= end):
                            continue
                        if text[left:right] != candidate["term"]:
                            raise ValueError(
                                f"contextual term source mismatch: {block['document']}:{left}-{right}"
                            )
                        rules = sorted(filter(None, (candidate["rule_ids"] or "").split(",")))
                        occurrence_id = stable_id(
                            "CLASSICAL_SOURCE_PASSAGE_MENTION", passage_id, "CONTEXTUAL_TERM_CANDIDATE",
                            candidate["candidate_id"], candidate["candidate_type"], left, right,
                        )
                        mention_insert.append((
                            occurrence_id, passage_id, doc["source_document_id"],
                            "CONTEXTUAL_TERM_CANDIDATE", candidate["candidate_id"], "",
                            candidate["candidate_type"], candidate["term"], left, right,
                            json.dumps(rules, ensure_ascii=False, separators=(",", ":")),
                            "CONTEXT_RULE_CANDIDATE",
                        ))
                        contextual_occurrence_count += 1

                # Count source spans that could not be placed wholly inside one
                # clause. They remain in their original mention tables; they are
                # deliberately not linked to a passage across a sentence boundary.
                for mention in entity_rows:
                    left, right = int(mention["character_start"]), int(mention["character_end"])
                    if not any(start <= left < right <= end for start, end in spans):
                        unassigned_entity_mentions += 1
                for candidate in contextual_rows:
                    left, right = int(candidate["character_start"]), int(candidate["character_end"])
                    if not any(start <= left < right <= end for start, end in spans):
                        unassigned_contextual_terms += 1

                if len(passage_insert) >= 5000:
                    connection.executemany("""
                        INSERT INTO classical_source_passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, passage_insert)
                    passage_insert.clear()
                if len(mention_insert) >= 5000:
                    connection.executemany("""
                        INSERT INTO classical_source_passage_mentions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, mention_insert)
                    mention_insert.clear()

        if passage_insert:
            connection.executemany("INSERT INTO classical_source_passages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", passage_insert)
        if mention_insert:
            connection.executemany("INSERT INTO classical_source_passage_mentions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", mention_insert)

        source_refs = connection.execute("""
            SELECT n.source_document, n.source_sha256, n.source_tree_position,
                   n.source_block_id, n.target AS target_block_id, n.target_subtype,
                   n.target_document, n.relation_type, n.resolution,
                   s.source_document_id AS source_document_id,
                   t.source_document_id AS target_document_id
            FROM node_relationships n
            JOIN classical_source_documents s ON s.document = n.source_document
            JOIN classical_source_documents t ON t.document = n.target_document
            WHERE n.relation_type='BLOCK_REFERENCE'
              AND n.resolution='RESOLVED_IN_CORPUS'
            ORDER BY n.source_document, n.source_block_id, n.target_document, n.target
        """).fetchall()
        reference_rows = []
        for ref in source_refs:
            reference_id = stable_id(
                "CLASSICAL_SOURCE_DOCUMENT_REFERENCE", ref["source_document_id"],
                ref["source_sha256"], ref["source_tree_position"], ref["source_block_id"],
                ref["target_document_id"], ref["target_block_id"], ref["target_subtype"],
            )
            reference_rows.append((
                reference_id, ref["source_document_id"], ref["target_document_id"],
                ref["source_document"], ref["target_document"], ref["source_sha256"],
                ref["source_tree_position"], ref["source_block_id"], ref["target_block_id"],
                ref["target_subtype"] or "", ref["relation_type"], ref["resolution"],
            ))
        if reference_rows:
            connection.executemany("""
                INSERT INTO classical_source_document_references VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, reference_rows)

        connection.commit()
        counts_by_work = {
            row["source_work"]: row["count"]
            for row in connection.execute("""
                SELECT source_work, COUNT(*) AS count
                FROM classical_source_documents GROUP BY source_work ORDER BY source_work
            """)
        }
        roles = {
            row["document_role"]: row["count"]
            for row in connection.execute("""
                SELECT document_role, COUNT(*) AS count
                FROM classical_source_documents GROUP BY document_role ORDER BY document_role
            """)
        }
        counts_by_term_type = {
            row["term_type"]: row["count"]
            for row in connection.execute("""
                SELECT term_type, COUNT(*) AS count
                FROM classical_source_passage_mentions
                GROUP BY term_type ORDER BY term_type
            """)
        }
        result = {
            "schema_version": 1,
            "source_documents": len(documents),
            "source_documents_by_work": counts_by_work,
            "source_documents_by_role": roles,
            "source_passages": passage_count,
            "passage_mentions": entity_occurrence_count + contextual_occurrence_count,
            "entity_mention_occurrences": entity_occurrence_count,
            "contextual_term_occurrences": contextual_occurrence_count,
            "passage_mentions_by_type": counts_by_term_type,
            "native_classical_document_references": len(reference_rows),
            "unassigned_entity_mentions_outside_single_passage": unassigned_entity_mentions,
            "unassigned_contextual_terms_outside_single_passage": unassigned_contextual_terms,
            "policy": {
                "passage_mentions": "source occurrence only; not a treatment, efficacy, diagnosis or theory assertion",
                "native_references": "only existing, resolved SiYuan BLOCK_REFERENCE edges whose two documents are in supported source works",
                "sentence_boundary": "an occurrence crossing passage boundaries is retained in its source table and is not linked to a passage",
            },
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    parser.add_argument("--document-hierarchy", type=Path, default=Path("catalog/generated/document_hierarchy.csv"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/classical_source_passage_audit.json"))
    args = parser.parse_args()
    result = build(args.db, args.document_hierarchy, args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
