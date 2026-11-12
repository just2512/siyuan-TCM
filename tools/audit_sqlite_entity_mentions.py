#!/usr/bin/env python3
"""Exhaustively validate SQLite entity mentions against their source blocks."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path


def source_unit_id(document: str, source_sha256: str, tree_position: str, block_id: str) -> str:
    raw = "\0".join((document, source_sha256, tree_position, block_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audit(database_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        metadata = dict(connection.execute("SELECT key, value FROM index_metadata"))
        expected_count = connection.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0]
        if "entity_mentions" not in metadata or int(metadata["entity_mentions"]) != expected_count:
            raise ValueError(
                f"entity_mentions metadata count mismatch: metadata={metadata.get('entity_mentions')!r}, "
                f"actual={expected_count}"
            )
        query = """
            SELECT m.mention_id, m.entity_id, m.unit_id, m.entity_type, m.matched_text,
                   m.character_start, m.character_end, m.document, m.source_sha256,
                   m.tree_position, COALESCE(m.block_id, '') AS block_id,
                   m.content_type, COALESCE(m.section_path, '') AS section_path,
                   m.lexicon_version, m.extraction_method, m.resolution_status,
                   c.entity_type AS catalog_entity_type,
                   b.content_text, b.content_type AS source_content_type,
                   COALESCE(b.section_path, '') AS source_section_path
            FROM entity_mentions m
            LEFT JOIN entity_catalog c ON c.entity_id = m.entity_id
            LEFT JOIN content_blocks b
              ON b.document = m.document
             AND b.source_sha256 = m.source_sha256
             AND b.tree_position = m.tree_position
             AND COALESCE(b.block_id, '') = COALESCE(m.block_id, '')
            ORDER BY m.mention_id
        """
        counts: Counter[str] = Counter()
        checked = 0
        for row in connection.execute(query):
            mention_id = row["mention_id"]
            if not mention_id or not row["entity_id"] or row["catalog_entity_type"] is None:
                raise ValueError(f"entity mention has a missing/unresolvable entity identity: {mention_id!r}")
            if row["entity_type"] != row["catalog_entity_type"]:
                raise ValueError(f"entity mention/catalog type mismatch: {mention_id}")
            for field in ("unit_id", "matched_text", "document", "source_sha256",
                          "tree_position", "content_type", "lexicon_version",
                          "extraction_method", "resolution_status"):
                if not row[field]:
                    raise ValueError(f"entity mention has empty {field}: {mention_id}")
            expected_unit = source_unit_id(
                row["document"], row["source_sha256"], row["tree_position"], row["block_id"]
            )
            if row["unit_id"] != expected_unit:
                raise ValueError(f"entity mention unit_id/source locator mismatch: {mention_id}")
            start, end = row["character_start"], row["character_end"]
            mention_identity = "\0".join((
                row["unit_id"], row["entity_type"], str(start), str(end), row["matched_text"],
            ))
            expected_mention_id = hashlib.sha256(mention_identity.encode("utf-8")).hexdigest()
            if mention_id != expected_mention_id:
                raise ValueError(f"entity mention ID/occurrence identity mismatch: {mention_id}")
            if row["content_text"] is None:
                raise ValueError(f"entity mention source locator cannot be resolved: {mention_id}")
            if (row["content_type"] != row["source_content_type"]
                or row["section_path"] != row["source_section_path"]):
                raise ValueError(f"entity mention source metadata mismatch: {mention_id}")
            start, end = row["character_start"], row["character_end"]
            source_text = row["content_text"]
            if (start < 0 or end <= start or end > len(source_text)
                or source_text[start:end] != row["matched_text"]):
                raise ValueError(f"entity mention source span mismatch: {mention_id}")
            counts[row["entity_type"]] += 1
            checked += 1
        if checked != expected_count:
            raise ValueError(
                f"entity mention scan cardinality mismatch: expected={expected_count}, checked={checked}"
            )
        return {"checked_entity_mentions": checked, "mention_counts_by_entity_type": dict(sorted(counts.items()))}
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    args = parser.parse_args()
    print(json.dumps(audit(args.db), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
