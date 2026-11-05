#!/usr/bin/env python3
"""Build and query a local SQLite full-text index from generated SiYuan CSV.GZ indexes."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sqlite3
from pathlib import Path
from typing import Any


CONTENT_FIELDS = [
    "document", "source_sha256", "tree_position", "block_id",
    "parent_block_id", "parent_node_type", "content_type", "heading_level",
    "section_path", "section_heading_block_ids", "characters", "content_text",
]
RELATION_FIELDS = [
    "source_document", "source_sha256", "source_tree_position",
    "source_block_id", "source_node_type", "relation_type", "target",
    "target_subtype", "target_document", "resolution",
]


def read_gzip_csv(path: Path):
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream)


def build_database(content_index: Path, relationship_index: Path | None,
                   database_path: Path) -> dict[str, Any]:
    if not content_index.is_file():
        raise FileNotFoundError(content_index)
    if relationship_index is not None and not relationship_index.is_file():
        raise FileNotFoundError(relationship_index)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()

    connection = sqlite3.connect(database_path)
    connection.execute("""
        CREATE TABLE content_blocks (
            id INTEGER PRIMARY KEY,
            document TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            tree_position TEXT NOT NULL,
            block_id TEXT,
            parent_block_id TEXT,
            parent_node_type TEXT,
            content_type TEXT NOT NULL,
            heading_level TEXT,
            section_path TEXT,
            section_heading_block_ids TEXT,
            characters INTEGER NOT NULL,
            content_text TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE node_relationships (
            id INTEGER PRIMARY KEY,
            source_document TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_tree_position TEXT NOT NULL,
            source_block_id TEXT,
            source_node_type TEXT,
            relation_type TEXT NOT NULL,
            target TEXT NOT NULL,
            target_subtype TEXT,
            target_document TEXT,
            resolution TEXT NOT NULL
        )
    """)

    fts_enabled = True
    try:
        connection.execute("""
            CREATE VIRTUAL TABLE content_fts USING fts5(
                content_text,
                document UNINDEXED,
                block_id UNINDEXED,
                content_type UNINDEXED,
                section_path UNINDEXED,
                tokenize='trigram'
            )
        """)
    except sqlite3.OperationalError:
        fts_enabled = False

    content_count = 0
    content_batch = []
    fts_batch = []
    for row in read_gzip_csv(content_index):
        content_batch.append((
            row["document"], row["source_sha256"], row["tree_position"],
            row.get("block_id", ""), row.get("parent_block_id", ""),
            row.get("parent_node_type", ""), row["content_type"],
            row.get("heading_level", ""), row.get("section_path", ""),
            row.get("section_heading_block_ids", ""),
            int(row.get("characters") or len(row["content_text"])),
            row["content_text"],
        ))
        fts_batch.append((
            row["content_text"], row["document"], row.get("block_id", ""),
            row["content_type"], row.get("section_path", ""),
        ))
        if len(content_batch) >= 2000:
            connection.executemany("""
                INSERT INTO content_blocks (
                    document, source_sha256, tree_position, block_id,
                    parent_block_id, parent_node_type, content_type, heading_level,
                    section_path, section_heading_block_ids, characters, content_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, content_batch)
            if fts_enabled:
                connection.executemany("""
                    INSERT INTO content_fts
                    (content_text, document, block_id, content_type, section_path)
                    VALUES (?, ?, ?, ?, ?)
                """, fts_batch)
            content_count += len(content_batch)
            content_batch, fts_batch = [], []

    if content_batch:
        connection.executemany("""
            INSERT INTO content_blocks (
                document, source_sha256, tree_position, block_id,
                parent_block_id, parent_node_type, content_type, heading_level,
                section_path, section_heading_block_ids, characters, content_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, content_batch)
        if fts_enabled:
            connection.executemany("""
                INSERT INTO content_fts
                (content_text, document, block_id, content_type, section_path)
                VALUES (?, ?, ?, ?, ?)
            """, fts_batch)
        content_count += len(content_batch)

    relation_count = 0
    if relationship_index is not None:
        batch = []
        for row in read_gzip_csv(relationship_index):
            batch.append(tuple(row.get(field, "") for field in RELATION_FIELDS))
            if len(batch) >= 2000:
                connection.executemany("""
                    INSERT INTO node_relationships (
                        source_document, source_sha256, source_tree_position,
                        source_block_id, source_node_type, relation_type, target,
                        target_subtype, target_document, resolution
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                relation_count += len(batch)
                batch = []
        if batch:
            connection.executemany("""
                INSERT INTO node_relationships (
                    source_document, source_sha256, source_tree_position,
                    source_block_id, source_node_type, relation_type, target,
                    target_subtype, target_document, resolution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            relation_count += len(batch)

    connection.execute("CREATE INDEX idx_content_document ON content_blocks(document)")
    connection.execute("CREATE INDEX idx_content_block_id ON content_blocks(block_id)")
    connection.execute("CREATE INDEX idx_relation_source ON node_relationships(source_document, source_block_id)")
    connection.execute("CREATE INDEX idx_relation_target ON node_relationships(target)")
    connection.execute("CREATE TABLE index_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.executemany("INSERT INTO index_metadata(key, value) VALUES (?, ?)", [
        ("search_backend", "fts5-trigram" if fts_enabled else "sqlite-instr-fallback"),
        ("content_blocks", str(content_count)),
        ("relationships", str(relation_count)),
    ])
    connection.commit()
    connection.close()
    return {
        "database": str(database_path),
        "content_blocks": content_count,
        "relationships": relation_count,
        "search_backend": "fts5-trigram" if fts_enabled else "sqlite-instr-fallback",
        "database_bytes": database_path.stat().st_size,
    }


def search_database(database_path: Path, query: str, limit: int = 20) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query must not be empty")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    metadata = dict(connection.execute("SELECT key, value FROM index_metadata"))
    backend = metadata.get("search_backend", "")
    rows = []
    if backend == "fts5-trigram" and len(query) >= 3:
        expression = '"' + query.replace('"', '""') + '"'
        try:
            rows = connection.execute("""
                SELECT document, block_id, content_type, section_path,
                       tree_position, content_text
                FROM content_fts
                WHERE content_fts MATCH ?
                LIMIT ?
            """, (expression, limit)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    if not rows:
        rows = connection.execute("""
            SELECT document, block_id, content_type, section_path,
                   tree_position, content_text
            FROM content_blocks
            WHERE instr(content_text, ?) > 0
            LIMIT ?
        """, (query, limit)).fetchall()
    result = [dict(row) for row in rows]
    connection.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="build the local SQLite index")
    parser.add_argument("--content-index", type=Path,
                        default=Path("catalog/generated/content_block_index.csv.gz"))
    parser.add_argument("--relationship-index", type=Path,
                        default=Path("catalog/generated/node_relationship_index.csv.gz"))
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    parser.add_argument("--query", help="search a built database")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    if args.build:
        print(json.dumps(build_database(args.content_index, args.relationship_index, args.db),
                         ensure_ascii=False, sort_keys=True))
        return 0
    if args.query:
        results = search_database(args.db, args.query, args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    parser.error("choose --build or provide --query")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
