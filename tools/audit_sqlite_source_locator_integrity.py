#!/usr/bin/env python3
"""Verify SQLite source-block locators are unique and source lengths are exact."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from audit_report import write_audit_report


def audit(database_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    connection = sqlite3.connect(database_path)
    try:
        total = connection.execute("SELECT COUNT(*) FROM content_blocks").fetchone()[0]
        malformed = connection.execute("""
            SELECT COUNT(*) FROM content_blocks
            WHERE document IS NULL OR document = ''
               OR source_sha256 IS NULL OR source_sha256 = ''
               OR tree_position IS NULL OR tree_position = ''
               OR characters != length(content_text)
        """).fetchone()[0]
        duplicate_rows = connection.execute("""
            SELECT COUNT(*) FROM (
                SELECT document, source_sha256, tree_position,
                       COALESCE(block_id, '') AS normalized_block_id
                FROM content_blocks
                GROUP BY document, source_sha256, tree_position,
                         COALESCE(block_id, '')
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        duplicate_excess = connection.execute("""
            SELECT COALESCE(SUM(row_count - 1), 0) FROM (
                SELECT COUNT(*) AS row_count
                FROM content_blocks
                GROUP BY document, source_sha256, tree_position,
                         COALESCE(block_id, '')
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        locator_count = connection.execute("""
            SELECT COUNT(*) FROM (
                SELECT document, source_sha256, tree_position,
                       COALESCE(block_id, '') AS normalized_block_id
                FROM content_blocks
                GROUP BY document, source_sha256, tree_position,
                         COALESCE(block_id, '')
            )
        """).fetchone()[0]
        result = {
            "content_block_rows": total,
            "unique_source_locators": locator_count,
            "duplicate_locator_groups": duplicate_rows,
            "duplicate_locator_excess_rows": duplicate_excess,
            "malformed_source_rows": malformed,
            "source_locator_validation": "PASS" if duplicate_rows == 0 else "FAIL",
            "source_length_validation": "PASS" if malformed == 0 else "FAIL",
        }
        if duplicate_rows or malformed:
            samples = connection.execute("""
                SELECT document, source_sha256, tree_position, block_id, COUNT(*) AS row_count
                FROM content_blocks
                GROUP BY document, source_sha256, tree_position, COALESCE(block_id, '')
                HAVING COUNT(*) > 1
                ORDER BY row_count DESC, document, tree_position
                LIMIT 10
            """).fetchall()
            raise ValueError(
                "SQLite source locator integrity failed: "
                + json.dumps({"result": result, "duplicate_samples": samples},
                             ensure_ascii=False, sort_keys=True)
            )
        return result
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3"))
    parser.add_argument("--output", type=Path, help="Optional JSON audit report path.")
    args = parser.parse_args()
    result = audit(args.db)
    if args.output:
        write_audit_report(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
