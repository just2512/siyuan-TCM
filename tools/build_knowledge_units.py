#!/usr/bin/env python3
"""Convert the loss-aware SiYuan content-block index into stable machine-readable knowledge units.

This stage normalizes structure and provenance only. It does not infer medical facts,
diagnoses, efficacy, or source validity from note text.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
REQUIRED_FIELDS = {
    "document", "source_sha256", "tree_position", "block_id",
    "parent_block_id", "parent_node_type", "content_type",
    "heading_level", "section_path", "section_heading_block_ids",
    "characters", "content_text",
}
ROLE_BY_TYPE = {
    "HEADING": "SECTION_HEADING",
    "PARAGRAPH": "SOURCE_PARAGRAPH",
    "TABLE_CELL": "SOURCE_TABLE_CELL",
    "LIST_ITEM": "SOURCE_LIST_ITEM",
    "HTML_BLOCK": "SOURCE_HTML_TEXT",
}


def stable_unit_id(row: dict[str, str]) -> str:
    identity = "\0".join((
        row["document"], row["source_sha256"], row["tree_position"],
        row.get("block_id", ""),
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def make_unit(row: dict[str, str]) -> dict[str, Any]:
    content_type = row["content_type"]
    if content_type not in ROLE_BY_TYPE:
        raise ValueError(f"unsupported content_type: {content_type}")
    source_hash = row["source_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise ValueError(f"invalid source SHA-256 for {row['document']}")
    document = row["document"].replace("\\", "/")
    if document.startswith("/") or re.match(r"^[A-Za-z]:", document) or ".." in Path(document).parts:
        raise ValueError(f"unsafe source path: {row['document']}")
    source_text = row["content_text"]
    if not source_text.strip():
        raise ValueError("empty content blocks must not become knowledge units")
    try:
        characters = int(row["characters"])
    except (TypeError, ValueError):
        characters = len(source_text)
    return {
        "schema_version": SCHEMA_VERSION,
        "unit_id": stable_unit_id(row),
        "unit_type": ROLE_BY_TYPE[content_type],
        "semantic_status": "UNCLASSIFIED",
        "assertion_status": "NOT_INTERPRETED",
        "source": {
            "document": document,
            "sha256": source_hash,
            "block_id": row.get("block_id", ""),
            "tree_position": row["tree_position"],
            "parent_block_id": row.get("parent_block_id", ""),
            "parent_node_type": row.get("parent_node_type", ""),
        },
        "context": {
            "section_path": row.get("section_path", ""),
            "section_heading_block_ids": [
                value for value in row.get("section_heading_block_ids", "").split(";") if value
            ],
            "heading_level": row.get("heading_level", ""),
        },
        "content": {
            "source_text": source_text,
            "normalized_text": normalize_text(source_text),
            "characters": characters,
        },
    }


def build(content_index: Path, output: Path) -> dict[str, int]:
    if not content_index.is_file():
        raise FileNotFoundError(content_index)
    output.mkdir(parents=True, exist_ok=True)
    target = output / "knowledge_units.jsonl.gz"
    seen: set[str] = set()
    counts: dict[str, int] = {}
    total = 0
    with gzip.open(content_index, "rt", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("content index missing fields: " + ", ".join(sorted(missing)))
        with target.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                import io
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                    for row in reader:
                        unit = make_unit(row)
                        if unit["unit_id"] in seen:
                            raise ValueError(f"duplicate unit_id: {unit['unit_id']}")
                        seen.add(unit["unit_id"])
                        counts[unit["unit_type"]] = counts.get(unit["unit_type"], 0) + 1
                        stream.write(json.dumps(unit, ensure_ascii=False, sort_keys=True) + "\n")
                        total += 1
    report = [
        "# Machine-readable knowledge units",
        "",
        f"- Schema version: {SCHEMA_VERSION}",
        f"- Units: {total}",
        f"- Unique unit IDs: {len(seen)}",
        "",
        "## Unit types",
        "",
        *[f"- {name}: {count}" for name, count in sorted(counts.items())],
        "",
        "## Contract",
        "",
        "- Each unit preserves the exact source text and a separate whitespace-normalized search form.",
        "- Every unit carries the source document, SHA-256, block ID, tree position and heading context.",
        "- IDs are deterministic for the same source revision and block location.",
        "- semantic_status remains UNCLASSIFIED and assertion_status remains NOT_INTERPRETED; this stage does not infer medical meaning.",
        "- Original .sy files are read-only; this output is a derived interchange format.",
        "",
        "## Output",
        "",
        "- knowledge_units.jsonl.gz: UTF-8 JSON Lines compressed with deterministic gzip metadata.",
    ]
    (output / "knowledge_units.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"units": total, "unique_unit_ids": len(seen), **{f"type_{k.lower()}": v for k, v in sorted(counts.items())}}


def validate(path: Path) -> int:
    seen: set[str] = set()
    count = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, 1):
            unit = json.loads(line)
            if unit.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(f"line {line_number}: unsupported schema version")
            if unit.get("semantic_status") != "UNCLASSIFIED" or unit.get("assertion_status") != "NOT_INTERPRETED":
                raise ValueError(f"line {line_number}: interpretation status must remain conservative")
            if not unit.get("content", {}).get("source_text", "").strip():
                raise ValueError(f"line {line_number}: empty source_text")
            if unit.get("unit_id") in seen:
                raise ValueError(f"line {line_number}: duplicate unit_id")
            seen.add(unit["unit_id"])
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-index", type=Path, default=Path("catalog/generated/content_block_index.csv.gz"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated"))
    parser.add_argument("--validate", action="store_true", help="validate an existing knowledge_units.jsonl.gz")
    args = parser.parse_args()
    if args.validate:
        count = validate(args.output / "knowledge_units.jsonl.gz")
        print(json.dumps({"validated_units": count}, ensure_ascii=False))
    else:
        result = build(args.content_index, args.output)
        validate(args.output / "knowledge_units.jsonl.gz")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
