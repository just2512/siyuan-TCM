#!/usr/bin/env python3
"""Export compact, immutable snapshots of unreviewed source-overlap decisions.

This utility never changes candidate rows or assigns semantic decisions. It
validates source-window offsets, then emits only review rows and grouped
signatures so a reviewer can adjudicate repeated patterns without downloading
the multi-gigabyte search-index artifact.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_queue(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        required = {
            "pair_id", "unit_id", "document", "source_sha256",
            "tree_position", "block_id", "overlap_kind",
            "review_status", "review_decision", "review_note",
        }
        missing = required - set(fields)
        if missing:
            raise ValueError(f"{path}: missing required fields: {sorted(missing)}")
        rows = list(reader)

    seen: set[str] = set()
    for line, row in enumerate(rows, 2):
        pair_id = row["pair_id"].strip()
        if not pair_id or pair_id in seen:
            raise ValueError(f"{path}: row {line}: missing or duplicate pair_id")
        seen.add(pair_id)
        status = row["review_status"].strip()
        decision = row["review_decision"].strip()
        if status not in {"UNREVIEWED", "REVIEWED"}:
            raise ValueError(f"{path}: row {line}: invalid review_status={status!r}")
        if status == "UNREVIEWED" and decision:
            raise ValueError(f"{path}: row {line}: unreviewed row has a decision")
        if status == "REVIEWED" and not decision:
            raise ValueError(f"{path}: row {line}: reviewed row has no decision")
        validate_evidence_window(path, line, row, fields)
    return fields, rows, digest


def validate_evidence_window(
    path: Path, line: int, row: dict[str, str], fields: list[str]
) -> None:
    if {"context_start", "context_end", "context_text"}.issubset(fields):
        base = int(row["context_start"])
        end = int(row["context_end"])
        text = row["context_text"]
    elif {"evidence_start", "evidence_end", "evidence_text"}.issubset(fields):
        base = int(row["evidence_start"])
        end = int(row["evidence_end"])
        text = row["evidence_text"]
    else:
        raise ValueError(f"{path}: missing evidence window fields")
    if end < base or end - base != len(text):
        raise ValueError(f"{path}: row {line}: evidence window length mismatch")
    for side in ("left", "right"):
        start_key = f"{side}_start"
        end_key = f"{side}_end"
        text_key = f"{side}_text" if f"{side}_text" in fields else f"{side}_term"
        if not {start_key, end_key, text_key}.issubset(fields):
            raise ValueError(f"{path}: missing {side} span fields")
        start, stop = int(row[start_key]), int(row[end_key])
        term = row[text_key]
        if start < base or stop > end or stop <= start:
            raise ValueError(f"{path}: row {line}: {side} span outside evidence window")
        if text[start - base:stop - base] != term:
            raise ValueError(
                f"{path}: row {line}: {side} text does not match source evidence offsets"
            )


def span_shape(row: dict[str, str]) -> str:
    ls, le = int(row["left_start"]), int(row["left_end"])
    rs, re_ = int(row["right_start"]), int(row["right_end"])
    if ls == rs and le == re_:
        return "EXACT_SAME_WINDOW"
    if ls <= rs and re_ <= le:
        return "LEFT_CONTAINS_RIGHT"
    if rs <= ls and le <= re_:
        return "RIGHT_CONTAINS_LEFT"
    return "PARTIAL_OVERLAP"


def signature(row: dict[str, str]) -> tuple[str, ...]:
    left_text = row.get("left_text", row.get("left_term", ""))
    right_text = row.get("right_text", row.get("right_term", ""))
    left_type = row.get("left_type", "")
    right_type = row.get("right_type", "")
    pair = row.get("entity_type_pair", row.get("candidate_type_pair", ""))
    # The signature groups recurring lexical patterns only. It never merges
    # the underlying occurrence IDs or source locations.
    return (
        pair,
        row["overlap_kind"],
        span_shape(row),
        left_type,
        left_text,
        right_type,
        right_text,
    )


def export_queue(
    source: Path, output: Path, summary: dict[str, Any]
) -> dict[str, Any]:
    fields, rows, source_digest = read_queue(source)
    pending = [row for row in rows if row["review_status"] == "UNREVIEWED"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(pending)

    by_type: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in pending:
        pair = row.get("entity_type_pair", row.get("candidate_type_pair", "UNKNOWN"))
        by_type[pair] += 1
        by_kind[row["overlap_kind"]] += 1
        grouped[signature(row)].append(row)

    patterns = []
    for sig, matches in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        examples = []
        for row in matches[:5]:
            examples.append({
                "pair_id": row["pair_id"],
                "document": row["document"],
                "source_sha256": row["source_sha256"],
                "tree_position": row["tree_position"],
                "block_id": row["block_id"],
                "unit_id": row["unit_id"],
                "left_id": row.get("left_mention_id", row.get("left_candidate_id", "")),
                "right_id": row.get("right_mention_id", row.get("right_candidate_id", "")),
                "evidence_text": row.get("context_text", row.get("evidence_text", "")),
            })
        patterns.append({
            "signature": list(sig),
            "occurrences": len(matches),
            "distinct_documents": len({row["document"] for row in matches}),
            "examples": examples,
        })

    return {
        "source_file": source.name,
        "source_sha256": source_digest,
        "source_rows": len(rows),
        "reviewed_rows": len(rows) - len(pending),
        "unreviewed_rows": len(pending),
        "unreviewed_by_type_pair": dict(sorted(by_type.items())),
        "unreviewed_by_overlap_kind": dict(sorted(by_kind.items())),
        "distinct_lexical_patterns": len(grouped),
        "snapshot_file": output.name,
        "candidate_mutations": 0,
        "semantic_decisions_assigned": 0,
        "patterns": patterns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity-queue", type=Path, required=True)
    parser.add_argument("--contextual-queue", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    entity_report = export_queue(
        args.entity_queue,
        args.output_dir / "entity_overlap_unreviewed.csv.gz",
        {},
    )
    contextual_report = export_queue(
        args.contextual_queue,
        args.output_dir / "contextual_overlap_unreviewed.csv.gz",
        {},
    )
    report = {
        "schema_version": 1,
        "policy": {
            "candidate_mutations": "none",
            "occurrence_identity": "all original IDs, source locators and offsets remain distinct",
            "grouping": "lexical signatures are for review batching only; never deduplicate source occurrences",
            "decision_assignment": "none; review decisions require explicit source-grounded adjudication",
            "evidence": "each left/right span is checked against the corresponding exact evidence-window offsets",
        },
        "entity_overlap": entity_report,
        "contextual_overlap": contextual_report,
    }
    (args.output_dir / "overlap_review_snapshot.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "entity_unreviewed": entity_report["unreviewed_rows"],
        "entity_patterns": entity_report["distinct_lexical_patterns"],
        "contextual_unreviewed": contextual_report["unreviewed_rows"],
        "contextual_patterns": contextual_report["distinct_lexical_patterns"],
        "candidate_mutations": 0,
        "semantic_decisions_assigned": 0,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
