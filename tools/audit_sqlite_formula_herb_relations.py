#!/usr/bin/env python3
"""Exhaustively audit SQLite formula-herb relation identities and source provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

SENTENCE_END = re.compile(r"[^。！？；．\n]+[。！？；．]?|；+|\n+")


def sentence_ranges(text: str) -> set[tuple[int, int]]:
    return {(m.start(), m.end()) for m in SENTENCE_END.finditer(text) if m.group(0).strip()}


def expected_relation_id(row: sqlite3.Row) -> str:
    raw = "\0".join((
        row["subject_mention_id"], "FORMULA_CONTAINS_HERB",
        row["object_mention_id"], row["unit_id"],
        str(row["sentence_start"]), str(row["sentence_end"]),
        row["extraction_rule"],
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()



AUTHOR_ATTRIBUTION_BOUNDARY = re.compile(
    r"(?:[\\u3400-\\u9fff]{1,8}(?:曰|云)[：:∶]|《[^》\\n]{1,40}》(?:曰|云)[：:∶])"
)


def position_parts(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except (AttributeError, ValueError):
        return ()


def crosses_author_attribution_boundary(connection: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Independently reject formula/herb endpoints separated by an author/book attribution."""
    formula_text = row["subject_source_text"]
    herb_text = row["object_source_text"]
    formula_start, formula_end = row["subject_start"], row["subject_end"]
    herb_start, herb_end = row["object_start"], row["object_end"]
    formula_position = position_parts(row["subject_tree_position"])
    herb_position = position_parts(row["object_tree_position"])

    if row["subject_unit_id"] == row["object_unit_id"]:
        if formula_start < herb_end and herb_start < formula_end:
            return True
        left, right = (
            (formula_end, herb_start)
            if formula_end <= herb_start
            else (herb_end, formula_start)
        )
        return bool(AUTHOR_ATTRIBUTION_BOUNDARY.search(formula_text[left:right]))

    if (len(formula_position) < 2 or len(herb_position) < 2
        or formula_position[:-1] != herb_position[:-1]
        or formula_position == herb_position):
        return True

    siblings = connection.execute(
        """
        SELECT tree_position, content_text
        FROM content_blocks
        WHERE document=? AND source_sha256=?
        """,
        (row["document"], row["source_sha256"]),
    ).fetchall()
    lower, upper = sorted((formula_position[-1], herb_position[-1]))
    middle = []
    for sibling in siblings:
        position = position_parts(sibling["tree_position"])
        if (len(position) >= 2 and position[:-1] == formula_position[:-1]
            and lower < position[-1] < upper):
            middle.append((position[-1], sibling["content_text"]))
    middle.sort(key=lambda item: item[0])

    if formula_position[-1] < herb_position[-1]:
        segments = [formula_text[formula_end:]]
        segments.extend(content for _, content in middle)
        segments.append(herb_text[:herb_start])
    else:
        segments = [herb_text[herb_end:]]
        segments.extend(content for _, content in middle)
        segments.append(formula_text[:formula_start])
    return any(AUTHOR_ATTRIBUTION_BOUNDARY.search(segment) for segment in segments)


def audit(database_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        metadata = dict(connection.execute("SELECT key, value FROM index_metadata"))
        actual = connection.execute(
            "SELECT COUNT(*) FROM semantic_relation_candidates"
        ).fetchone()[0]
        if "relation_candidates" not in metadata or int(metadata["relation_candidates"]) != actual:
            raise ValueError(
                "semantic relation metadata count mismatch: "
                f"metadata={metadata.get('relation_candidates')!r}, actual={actual}"
            )
        query = """
            SELECT r.*, s.entity_type AS subject_type, s.matched_text AS subject_matched_text,
                   s.unit_id AS subject_unit_id, s.character_start AS subject_start,
                   s.character_end AS subject_end, s.document AS subject_document,
                   s.source_sha256 AS subject_sha256, s.tree_position AS subject_tree_position,
                   COALESCE(s.block_id, '') AS subject_block_id,
                   o.entity_type AS object_type, o.matched_text AS object_matched_text,
                   o.unit_id AS object_unit_id, o.character_start AS object_start,
                   o.character_end AS object_end, o.document AS object_document,
                   o.source_sha256 AS object_sha256, o.tree_position AS object_tree_position,
                   COALESCE(o.block_id, '') AS object_block_id,
                   sb.content_text AS subject_source_text, ob.content_text AS object_source_text,
                   eb.content_text AS evidence_source_text
            FROM semantic_relation_candidates r
            LEFT JOIN entity_mentions s ON s.mention_id = r.subject_mention_id
            LEFT JOIN entity_mentions o ON o.mention_id = r.object_mention_id
            LEFT JOIN content_blocks sb ON sb.document=s.document AND sb.source_sha256=s.source_sha256
              AND sb.tree_position=s.tree_position AND COALESCE(sb.block_id,'')=COALESCE(s.block_id,'')
            LEFT JOIN content_blocks ob ON ob.document=o.document AND ob.source_sha256=o.source_sha256
              AND ob.tree_position=o.tree_position AND COALESCE(ob.block_id,'')=COALESCE(o.block_id,'')
            LEFT JOIN content_blocks eb ON eb.document=r.document AND eb.source_sha256=r.source_sha256
              AND eb.tree_position=r.tree_position AND COALESCE(eb.block_id,'')=COALESCE(r.block_id,'')
            ORDER BY r.document, r.tree_position, r.sentence_start, r.relation_id
        """
        predicates: Counter[str] = Counter()
        seen: set[str] = set()
        checked = 0
        for row in connection.execute(query):
            rid = row["relation_id"]
            if not rid or rid in seen:
                raise ValueError(f"missing or duplicate SQLite relation_id: {rid!r}")
            seen.add(rid)
            if row["predicate"] != "FORMULA_CONTAINS_HERB":
                raise ValueError(f"unsupported formula-herb predicate: {rid}")
            if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                raise ValueError(f"unsafe formula-herb relation status: {rid}")
            if row["extraction_rule"] not in {
                "FORMULA_COMPOSITION_EXPLICIT_V1", "FORMULA_COMPOSITION_NEARBY_BLOCK_V1"
            }:
                raise ValueError(f"unsupported formula-herb extraction rule: {rid}")
            if rid != expected_relation_id(row):
                raise ValueError(f"formula-herb relation ID/endpoint identity mismatch: {rid}")
            if (row["subject_type"] != "FORMULA" or row["object_type"] != "HERB"
                or row["subject_matched_text"] != row["subject_text"]
                or row["object_matched_text"] != row["object_text"]):
                raise ValueError(f"formula-herb relation endpoint type/text mismatch: {rid}")
            for role in ("subject", "object"):
                start, end = row[f"{role}_start"], row[f"{role}_end"]
                source_text = row[f"{role}_source_text"]
                if (source_text is None or start < 0 or end <= start or end > len(source_text)
                    or source_text[start:end] != row[f"{role}_matched_text"]):
                    raise ValueError(f"formula-herb {role} mention source span mismatch: {rid}")
            if (row["subject_document"] != row["document"]
                or row["subject_sha256"] != row["source_sha256"]
                or row["object_document"] != row["document"]
                or row["object_sha256"] != row["source_sha256"]
                or row["object_unit_id"] != row["unit_id"]
                or row["object_tree_position"] != row["tree_position"]
                or row["object_block_id"] != row["block_id"]):
                raise ValueError(f"formula-herb relation endpoint source locator mismatch: {rid}")
            start, end = row["sentence_start"], row["sentence_end"]
            source_text = row["evidence_source_text"]
            if (source_text is None or start < 0 or end <= start or end > len(source_text)
                or source_text[start:end] != row["evidence_text"]):
                raise ValueError(f"formula-herb relation evidence offset mismatch: {rid}")
            if (start, end) not in sentence_ranges(source_text):
                raise ValueError(f"formula-herb relation evidence crosses sentence boundary: {rid}")
            if crosses_author_attribution_boundary(connection, row):
                raise ValueError(f"formula-herb relation crosses author attribution boundary: {rid}")
            predicates[row["predicate"]] += 1
            checked += 1
        if checked != actual:
            raise ValueError(f"semantic relation scan cardinality mismatch: {checked} != {actual}")
        return {
            "checked_relation_rows": checked,
            "relation_counts_by_predicate": dict(sorted(predicates.items())),
            "identity_validation": "PASS",
            "endpoint_source_validation": "PASS",
            "evidence_source_validation": "PASS",
        }
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
