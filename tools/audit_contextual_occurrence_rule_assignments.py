#!/usr/bin/env python3
"""Audit contextual candidate rule assignments without collapsing source occurrences."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED = {
    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
    "source_sha256", "tree_position", "block_id", "unit_id",
    "character_start", "character_end", "evidence_start", "evidence_text",
    "classification_status",
}
SOURCE_FIELDS = (
    "evidence_document", "source_sha256", "tree_position", "block_id", "unit_id",
    "character_start", "character_end", "evidence_start", "evidence_text",
)


def audit(path: Path, example_limit: int = 100) -> dict:
    groups: dict[tuple, dict] = {}
    raw_rows = 0
    duplicate_rule_rows = 0
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError("input missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            raw_rows += 1
            if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                raise ValueError(f"row {line}: unsafe classification status")
            start, end = int(row["character_start"]), int(row["character_end"])
            evidence_start = int(row["evidence_start"])
            if start < 0 or end <= start or evidence_start < 0:
                raise ValueError(f"row {line}: invalid occurrence/evidence offsets")
            evidence_end = evidence_start + len(row["evidence_text"])
            if (not row["evidence_text"] or not (evidence_start <= start < end <= evidence_end)
                or row["evidence_text"][start-evidence_start:end-evidence_start] != row["term"]):
                raise ValueError(f"row {line}: term does not match its exact evidence slice")
            key = (row["unit_id"], row["candidate_type"], row["candidate_id"], start, end)
            identity = {field: row[field] for field in SOURCE_FIELDS}
            item = groups.get(key)
            if item is None:
                groups[key] = {
                    "unit_id": row["unit_id"], "candidate_id": row["candidate_id"],
                    "term": row["term"], "candidate_type": row["candidate_type"],
                    "start": start, "end": end, "source": identity,
                    "rule_ids": {row["rule_id"]},
                }
                continue
            if item["term"] != row["term"] or item["source"] != identity:
                raise ValueError(f"row {line}: same occurrence identity has conflicting text/provenance")
            if row["rule_id"] in item["rule_ids"]:
                duplicate_rule_rows += 1
            else:
                item["rule_ids"].add(row["rule_id"])
    if duplicate_rule_rows:
        raise ValueError(f"duplicate occurrence/rule rows: {duplicate_rule_rows}")

    by_type = Counter()
    multi_by_type = Counter()
    rule_combinations = Counter()
    examples = []
    for item in groups.values():
        by_type[item["candidate_type"]] += 1
        rules = sorted(item["rule_ids"])
        if len(rules) > 1:
            multi_by_type[item["candidate_type"]] += 1
            rule_combinations[(item["candidate_type"], "|".join(rules))] += 1
            if len(examples) < example_limit:
                examples.append({
                    "candidate_id": item["candidate_id"], "term": item["term"],
                    "candidate_type": item["candidate_type"], "rule_ids": rules,
                    "unit_id": item["unit_id"], "document": item["source"]["evidence_document"],
                    "source_sha256": item["source"]["source_sha256"],
                    "tree_position": item["source"]["tree_position"],
                    "block_id": item["source"]["block_id"],
                    "character_start": item["start"], "character_end": item["end"],
                    "evidence_start": item["source"]["evidence_start"],
                    "evidence_text": item["source"]["evidence_text"],
                })
    extra_assignments = raw_rows - len(groups)
    return {
        "schema_version": 1,
        "candidate_rows": raw_rows,
        "distinct_occurrences": len(groups),
        "multi_rule_occurrence_groups": sum(multi_by_type.values()),
        "extra_rule_assignments": extra_assignments,
        "occurrence_counts_by_type": dict(sorted(by_type.items())),
        "multi_rule_occurrence_groups_by_type": dict(sorted(multi_by_type.items())),
        "rule_combinations_by_type": {
            f"{kind}:{rules}": count
            for (kind, rules), count in sorted(rule_combinations.items())
        },
        "multi_rule_examples": examples,
        "policy": {
            "occurrence_identity": "unit_id + candidate_type + candidate_id + source offsets",
            "rule_assignments": "multiple matching rules are reported, not treated as multiple source occurrences",
            "candidate_mutation": "none",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
        default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--output", type=Path,
        default=Path("catalog/generated/contextual_occurrence_rule_assignment_audit.json"))
    args = parser.parse_args()
    result = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k != "multi_rule_examples"},
        ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
