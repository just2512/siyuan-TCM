#!/usr/bin/env python3
"""Audit overlapping and repeated dictionary-backed entity mention windows.

The audit is observational: it never removes or rewrites candidate mentions.
It distinguishes same-type nested lexical windows from cross-type nested
entities (notably FORMULA/HERB) and preserves every original character span.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def classify_pair(left: dict[str, str], right: dict[str, str]) -> str | None:
    ls, le = int(left["character_start"]), int(left["character_end"])
    rs, re_ = int(right["character_start"]), int(right["character_end"])
    if le <= rs or re_ <= ls:
        return None
    same_type = left["entity_type"] == right["entity_type"]
    if ls == rs and le == re_:
        if same_type:
            return "same_type_exact_duplicate_window"
        return "cross_type_exact_span"
    left_contains = ls <= rs and re_ <= le
    right_contains = rs <= ls and le <= re_
    if left_contains or right_contains:
        if {left["entity_type"], right["entity_type"]} == {"FORMULA", "HERB"}:
            return "nested_formula_herb_entity"
        if same_type and left["entity_type"] == "FORMULA":
            return "nested_named_formula"
        if same_type:
            return "nested_same_type_window"
        return "nested_cross_type_entity"
    return "partial_overlap"


def audit(path: Path, output: Path, max_examples: int = 50) -> dict[str, Any]:
    by_unit: dict[str, list[dict[str, str]]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "mention_id", "unit_id", "entity_type", "matched_text",
            "character_start", "character_end", "document", "source_sha256",
            "tree_position", "block_id",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("mention input missing fields: " + ", ".join(sorted(missing)))
        for row in reader:
            start, end = int(row["character_start"]), int(row["character_end"])
            if start < 0 or end <= start or end - start != len(row["matched_text"]):
                raise ValueError(f"invalid mention span: {row['mention_id']}")
            by_unit[row["unit_id"]].append(row)

    pair_counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    repeated_groups = 0
    repeated_occurrences = 0
    repeated_examples = []
    total_mentions = 0

    for unit_id, rows in by_unit.items():
        total_mentions += len(rows)
        rows.sort(key=lambda row: (int(row["character_start"]),
                                   int(row["character_end"]), row["mention_id"]))
        active: list[dict[str, str]] = []
        for current in rows:
            start = int(current["character_start"])
            active = [prior for prior in active
                      if int(prior["character_end"]) > start]
            for prior in active:
                kind = classify_pair(prior, current)
                if kind is None:
                    continue
                pair_counts[kind] += 1
                if len(examples[kind]) < max_examples:
                    examples[kind].append({
                        "unit_id": unit_id,
                        "document": current["document"],
                        "tree_position": current["tree_position"],
                        "block_id": current["block_id"],
                        "left": {
                            "mention_id": prior["mention_id"],
                            "entity_type": prior["entity_type"],
                            "text": prior["matched_text"],
                            "start": int(prior["character_start"]),
                            "end": int(prior["character_end"]),
                        },
                        "right": {
                            "mention_id": current["mention_id"],
                            "entity_type": current["entity_type"],
                            "text": current["matched_text"],
                            "start": start,
                            "end": int(current["character_end"]),
                        },
                    })
            active.append(current)

        occurrences: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            occurrences[(row["entity_type"], row["matched_text"])].append(row)
        for (entity_type, term), hits in occurrences.items():
            if len(hits) < 2:
                continue
            repeated_groups += 1
            repeated_occurrences += len(hits)
            if len(repeated_examples) < max_examples:
                repeated_examples.append({
                    "unit_id": unit_id,
                    "document": hits[0]["document"],
                    "tree_position": hits[0]["tree_position"],
                    "block_id": hits[0]["block_id"],
                    "entity_type": entity_type,
                    "term": term,
                    "occurrences": [
                        {"mention_id": hit["mention_id"],
                         "start": int(hit["character_start"]),
                         "end": int(hit["character_end"])}
                        for hit in hits[:max_examples]
                    ],
                })

    report = {
        "schema_version": 1,
        "source_mentions": str(path),
        "source_units": len(by_unit),
        "total_mentions": total_mentions,
        "overlap_pair_counts": dict(sorted(pair_counts.items())),
        "repeated_term_groups": repeated_groups,
        "repeated_term_occurrences_in_groups": repeated_occurrences,
        "examples_limit_per_category": max_examples,
        "overlap_examples": dict(sorted(examples.items())),
        "repeated_occurrence_examples": repeated_examples,
        "interpretation": {
            "same_type_exact_duplicate_window": "same entity type and exact same character window; inspect as duplicate lexical window",
            "nested_formula_herb_entity": "different semantic types nested in source text; retain both unresolved candidates",
            "nested_named_formula": "nested formula names; retain both unresolved candidates for later resolution",
            "repeated_term_groups": "same term/type appearing multiple times in one source unit; offsets remain distinct",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return {
        "source_units": len(by_unit),
        "total_mentions": total_mentions,
        "overlap_pair_counts": dict(sorted(pair_counts.items())),
        "repeated_term_groups": repeated_groups,
        "repeated_term_occurrences_in_groups": repeated_occurrences,
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mentions", type=Path,
                        default=Path("catalog/generated/entity_mention_candidates.csv.gz"))
    parser.add_argument("--output", type=Path,
                        default=Path("catalog/generated/entity_mention_overlap_audit.json"))
    parser.add_argument("--max-examples", type=int, default=50)
    args = parser.parse_args()
    if args.max_examples < 1:
        parser.error("--max-examples must be >= 1")
    print(json.dumps(audit(args.mentions, args.output, args.max_examples),
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
