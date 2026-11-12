#!/usr/bin/env python3
"""Report repeated contextual-term occurrences and semantic span overlaps without collapsing them."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED = {
    "candidate_id", "term", "candidate_type", "rule_id", "unit_id",
    "character_start", "character_end", "classification_status",
}


def audit(path: Path, example_limit: int = 50) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    occurrences: dict[tuple, dict] = {}
    duplicate_rows = 0
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError("contextual term input missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                raise ValueError(f"row {line}: unsafe classification status")
            start, end = int(row["character_start"]), int(row["character_end"])
            if start < 0 or end <= start:
                raise ValueError(f"row {line}: invalid occurrence offsets")
            key = (row["unit_id"], row["candidate_type"], row["candidate_id"], start, end)
            prior = occurrences.get(key)
            if prior is None:
                occurrences[key] = {
                    "unit_id": row["unit_id"], "candidate_id": row["candidate_id"],
                    "term": row["term"], "candidate_type": row["candidate_type"],
                    "start": start, "end": end, "rules": {row["rule_id"]},
                }
            else:
                if prior["term"] != row["term"]:
                    raise ValueError(f"row {line}: same occurrence identity maps to different text")
                if row["rule_id"] in prior["rules"]:
                    duplicate_rows += 1
                prior["rules"].add(row["rule_id"])

    if duplicate_rows:
        raise ValueError(f"duplicate contextual occurrence/rule rows: {duplicate_rows}")

    by_unit = defaultdict(list)
    by_lexical = defaultdict(set)
    for item in occurrences.values():
        by_unit[item["unit_id"]].append(item)
        by_lexical[(item["candidate_type"], item["term"])].add(
            (item["unit_id"], item["start"], item["end"])
        )

    overlap_counts = Counter()
    overlap_type_relation_counts = Counter()
    overlap_type_pair_counts = Counter()
    overlap_examples = []
    repeated = [
        {"candidate_type": kind, "term": term, "distinct_occurrences": len(spans)}
        for (kind, term), spans in by_lexical.items() if len(spans) > 1
    ]
    for unit_id, items in by_unit.items():
        items.sort(key=lambda x: (x["start"], x["end"], x["candidate_type"], x["candidate_id"]))
        active = []
        for current in items:
            active = [item for item in active if item["end"] > current["start"]]
            for prior in active:
                if prior["start"] == current["start"] and prior["end"] == current["end"]:
                    kind = "exact_span"
                elif prior["start"] <= current["start"] and current["end"] <= prior["end"]:
                    kind = "current_nested"
                elif current["start"] <= prior["start"] and prior["end"] <= current["end"]:
                    kind = "prior_nested"
                else:
                    kind = "partial_overlap"
                overlap_counts[kind] += 1
                type_relation = "same_type" if prior["candidate_type"] == current["candidate_type"] else "cross_type"
                type_pair = "|".join(sorted((prior["candidate_type"], current["candidate_type"])))
                overlap_type_relation_counts[type_relation] += 1
                overlap_type_pair_counts[type_pair] += 1
                if len(overlap_examples) < example_limit:
                    overlap_examples.append({
                        "unit_id": unit_id, "overlap_kind": kind,
                        "type_relation": type_relation, "candidate_type_pair": type_pair,
                        "left": {k: prior[k] for k in ("candidate_id","term","candidate_type","start","end")},
                        "right": {k: current[k] for k in ("candidate_id","term","candidate_type","start","end")},
                    })
            active.append(current)

    return {
        "schema_version": 2,
        "distinct_occurrence_rows": len(occurrences),
        "repeated_lexical_forms_with_multiple_occurrences": len(repeated),
        "repeated_occurrence_examples": sorted(
            repeated, key=lambda x: (-x["distinct_occurrences"], x["candidate_type"], x["term"])
        )[:example_limit],
        "overlap_pair_counts": dict(sorted(overlap_counts.items())),
        "overlap_pair_type_relation_counts": dict(sorted(overlap_type_relation_counts.items())),
        "overlap_pair_candidate_type_counts": dict(sorted(overlap_type_pair_counts.items())),
        "overlap_examples": overlap_examples,
        "policy": {
            "repeated_term": "same lexical form at different source offsets remains separate",
            "overlap": "reported for semantic review; this audit does not merge, delete, or reclassify candidates",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/contextual_term_overlap_audit.json"))
    args = parser.parse_args()
    result = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"repeated_occurrence_examples","overlap_examples"}}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
