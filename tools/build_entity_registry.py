#!/usr/bin/env python3
"""Build stable lexical entity identifiers without unsafe synonym merging."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

FIELDS = [
    "entity_id", "entity_type", "preferred_label", "lexical_form",
    "lexicon_version", "identity_status",
]


def stable_entity_id(entity_type: str, lexical_form: str) -> str:
    identity = "\0".join((entity_type, lexical_form))
    return "lex_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def build(lexicon_path: Path, output_path: Path) -> dict[str, int]:
    if not lexicon_path.is_file():
        raise FileNotFoundError(lexicon_path)
    entries = {}
    with lexicon_path.open("r", encoding="utf-8-sig", newline="") as source:
        for line, row in enumerate(csv.DictReader(source), 2):
            entity_type = row["entity_type"].strip()
            term = row["term"].strip()
            version = row["lexicon_version"].strip()
            if not entity_type or not term or not version:
                raise ValueError(f"lexicon row {line}: required field is empty")
            key = (entity_type, term)
            if key in entries:
                raise ValueError(f"lexicon row {line}: duplicate lexical entity {key}")
            entries[key] = {
                "entity_id": stable_entity_id(entity_type, term),
                "entity_type": entity_type,
                "preferred_label": term,
                "lexical_form": term,
                "lexicon_version": version,
                "identity_status": "LEXICAL_ID_ONLY",
            }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(entries[key] for key in sorted(entries))
    return {
        "lexical_entities": len(entries),
        "unique_entity_ids": len({row["entity_id"] for row in entries.values()}),
    }


def validate(registry_path: Path, lexicon_path: Path) -> int:
    expected = {}
    with lexicon_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            key = (row["entity_type"].strip(), row["term"].strip())
            expected[key] = row["lexicon_version"].strip()
    seen = set()
    ids = set()
    with registry_path.open("r", encoding="utf-8-sig", newline="") as source:
        for line, row in enumerate(csv.DictReader(source), 2):
            key = (row["entity_type"], row["lexical_form"])
            if key not in expected:
                raise ValueError(f"registry row {line}: unknown lexical entity {key}")
            if key in seen:
                raise ValueError(f"registry row {line}: duplicate lexical entity {key}")
            seen.add(key)
            if row["entity_id"] != stable_entity_id(*key):
                raise ValueError(f"registry row {line}: unstable entity_id")
            if row["preferred_label"] != row["lexical_form"]:
                raise ValueError(f"registry row {line}: label differs from lexical form")
            if row["lexicon_version"] != expected[key]:
                raise ValueError(f"registry row {line}: lexicon version mismatch")
            if row["identity_status"] != "LEXICAL_ID_ONLY":
                raise ValueError(f"registry row {line}: unsafe identity status")
            ids.add(row["entity_id"])
    if seen != set(expected):
        raise ValueError(f"registry coverage mismatch: missing={len(set(expected)-seen)}")
    if len(ids) != len(seen):
        raise ValueError("entity_id collision")
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon", type=Path, default=Path("catalog/entity-lexicon.csv"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/entity_registry.csv"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        count = validate(args.output, args.lexicon)
        print(json.dumps({"validated_lexical_entities": count}, ensure_ascii=False))
    else:
        result = build(args.lexicon, args.output)
        validate(args.output, args.lexicon)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
