#!/usr/bin/env python3
"""Build a source-grounded manual review queue for cross-type contextual overlaps.

This tool never changes candidate records or decides whether either span is
semantically valid. It only makes every cross-type overlap inspectable with
stable candidate identities, source offsets, provenance, and exact evidence.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED = {
    "candidate_id", "term", "candidate_type", "rule_id", "evidence_document",
    "source_sha256", "tree_position", "block_id", "unit_id", "character_start",
    "character_end", "evidence_start", "evidence_text", "classification_status",
}
SOURCE_FIELDS = (
    "evidence_document", "source_sha256", "tree_position", "block_id", "unit_id",
)


def load_occurrences(path: Path) -> dict[tuple, dict]:
    occurrences: dict[tuple, dict] = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError("input missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                raise ValueError(f"row {line}: unsafe classification status")
            if not all(row.get(field) for field in (
                "candidate_id", "term", "candidate_type", "rule_id",
                "evidence_document", "source_sha256", "tree_position", "unit_id",
                "evidence_text",
            )):
                raise ValueError(f"row {line}: missing identity or provenance")
            start, end = int(row["character_start"]), int(row["character_end"])
            evidence_start = int(row["evidence_start"])
            evidence_text = row["evidence_text"]
            evidence_end = evidence_start + len(evidence_text)
            if (start < 0 or end <= start or evidence_start < 0
                or not (evidence_start <= start < end <= evidence_end)
                or evidence_text[start-evidence_start:end-evidence_start] != row["term"]):
                raise ValueError(f"row {line}: candidate span/evidence text mismatch")
            key = (row["unit_id"], row["candidate_type"], row["candidate_id"], start, end)
            item = {
                "unit_id": row["unit_id"], "candidate_id": row["candidate_id"],
                "term": row["term"], "candidate_type": row["candidate_type"],
                "start": start, "end": end,
                "evidence_start": evidence_start, "evidence_text": evidence_text,
                "source": {field: row[field] for field in SOURCE_FIELDS},
                "rules": {row["rule_id"]},
            }
            prior = occurrences.get(key)
            if prior is None:
                occurrences[key] = item
            else:
                comparable = ("term", "evidence_start", "evidence_text", "source")
                if any(prior[field] != item[field] for field in comparable):
                    raise ValueError(f"row {line}: duplicate occurrence has conflicting provenance")
                if row["rule_id"] in prior["rules"]:
                    raise ValueError(f"row {line}: duplicate occurrence/rule row")
                prior["rules"].add(row["rule_id"])
    return occurrences


def overlap_kind(left: dict, right: dict) -> str:
    if left["start"] == right["start"] and left["end"] == right["end"]:
        return "exact_span"
    if left["start"] <= right["start"] and right["end"] <= left["end"]:
        return "prior_nested"
    if right["start"] <= left["start"] and left["end"] <= right["end"]:
        return "current_nested"
    return "partial_overlap"


def build_review_queue(input_path: Path, output_path: Path, report_path: Path, overlap_audit_path: Path | None = None) -> dict:
    occurrences = load_occurrences(input_path)
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for item in occurrences.values():
        by_unit[item["unit_id"]].append(item)

    rows: list[dict] = []
    by_pair_type: Counter[str] = Counter()
    by_overlap_kind: Counter[str] = Counter()
    same_type_pairs = 0
    for unit_id, items in by_unit.items():
        items.sort(key=lambda x: (x["start"], x["end"], x["candidate_type"], x["candidate_id"]))
        active: list[dict] = []
        for current in items:
            active = [item for item in active if item["end"] > current["start"]]
            for prior in active:
                if prior["candidate_type"] == current["candidate_type"]:
                    same_type_pairs += 1
                    continue
                if prior["source"] != current["source"]:
                    raise ValueError(f"unit {unit_id}: overlapping candidates have different source locators")
                left, right = prior, current
                left_start, right_end = min(left["start"], right["start"]), max(left["end"], right["end"])
                evidence_options = [item for item in (left, right)
                    if item["evidence_start"] <= left_start
                    and right_end <= item["evidence_start"] + len(item["evidence_text"])]
                if not evidence_options:
                    raise ValueError(f"unit {unit_id}: no exact evidence window covers overlapping spans")
                evidence = min(evidence_options, key=lambda x: len(x["evidence_text"]))
                evidence_end = evidence["evidence_start"] + len(evidence["evidence_text"])
                pair_type = "|".join(sorted((left["candidate_type"], right["candidate_type"])))
                kind = overlap_kind(left, right)
                identity = "\0".join((unit_id, left["candidate_id"], str(left["start"]),
                    str(left["end"]), right["candidate_id"], str(right["start"]), str(right["end"])))
                pair_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                rows.append({
                    "pair_id": pair_id,
                    "unit_id": unit_id,
                    "document": left["source"]["evidence_document"],
                    "source_sha256": left["source"]["source_sha256"],
                    "tree_position": left["source"]["tree_position"],
                    "block_id": left["source"]["block_id"],
                    "overlap_kind": kind,
                    "candidate_type_pair": pair_type,
                    "left_candidate_id": left["candidate_id"],
                    "left_type": left["candidate_type"],
                    "left_term": left["term"],
                    "left_start": left["start"],
                    "left_end": left["end"],
                    "left_rule_ids": ";".join(sorted(left["rules"])),
                    "right_candidate_id": right["candidate_id"],
                    "right_type": right["candidate_type"],
                    "right_term": right["term"],
                    "right_start": right["start"],
                    "right_end": right["end"],
                    "right_rule_ids": ";".join(sorted(right["rules"])),
                    "evidence_start": evidence["evidence_start"],
                    "evidence_end": evidence_end,
                    "evidence_text": evidence["evidence_text"],
                    "review_status": "UNREVIEWED",
                    "review_decision": "",
                    "review_note": "",
                })
                by_pair_type[pair_type] += 1
                by_overlap_kind[kind] += 1
            active.append(current)

    reconciliation = {"status": "NOT_RUN"}
    if overlap_audit_path is not None:
        overlap_audit = json.loads(overlap_audit_path.read_text(encoding="utf-8"))
        expected_by_pair = {}
        for pair, count in overlap_audit.get("overlap_pair_candidate_type_counts", {}).items():
            entity_types = pair.split("|")
            if len(entity_types) == 2 and entity_types[0] != entity_types[1] and int(count):
                expected_by_pair[pair] = int(count)
        actual_by_pair = dict(sorted(by_pair_type.items()))
        if expected_by_pair != actual_by_pair:
            raise ValueError(
                "cross-type contextual review queue does not reconcile with overlap audit: "
                f"expected={expected_by_pair}, actual={actual_by_pair}"
            )
        reported_cross_type = int(
            overlap_audit.get("overlap_pair_type_relation_counts", {}).get("cross_type", -1)
        )
        if reported_cross_type != len(rows):
            raise ValueError(
                "cross-type contextual review queue total does not reconcile with overlap audit: "
                f"expected={reported_cross_type}, actual={len(rows)}"
            )
        reconciliation = {
            "status": "PASS",
            "expected_cross_type_overlap_pairs": reported_cross_type,
            "queued_cross_type_overlap_pairs": len(rows),
            "pairs_by_type_match": True,
        }

    rows.sort(key=lambda row: (row["document"], row["tree_position"], row["block_id"],
        row["left_start"], row["right_start"], row["pair_id"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else [
        "pair_id", "unit_id", "document", "source_sha256", "tree_position", "block_id",
        "overlap_kind", "candidate_type_pair", "left_candidate_id", "left_type",
        "left_term", "left_start", "left_end", "left_rule_ids", "right_candidate_id",
        "right_type", "right_term", "right_start", "right_end", "right_rule_ids",
        "evidence_start", "evidence_end", "evidence_text", "review_status",
        "review_decision", "review_note",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    result = {
        "schema_version": 1,
        "distinct_occurrences": len(occurrences),
        "cross_type_overlap_pairs": len(rows),
        "reconciliation": reconciliation,
        "same_type_overlap_pairs_not_queued": same_type_pairs,
        "cross_type_pairs_by_type": dict(sorted(by_pair_type.items())),
        "cross_type_pairs_by_overlap_kind": dict(sorted(by_overlap_kind.items())),
        "review_status": "UNREVIEWED",
        "policy": {
            "candidate_mutation": "none",
            "semantic_decisions": "manual review required; geometric overlap is not a semantic verdict",
            "evidence": "each row includes an exact source excerpt and source locator",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
        default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--output", type=Path,
        default=Path("catalog/generated/contextual_term_cross_type_overlap_review.csv"))
    parser.add_argument("--report", type=Path,
        default=Path("catalog/generated/contextual_term_cross_type_overlap_review.json"))
    parser.add_argument("--overlap-audit", type=Path,
        default=Path("catalog/generated/contextual_term_overlap_audit.json"))
    args = parser.parse_args()
    build_review_queue(args.input, args.output, args.report, args.overlap_audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
