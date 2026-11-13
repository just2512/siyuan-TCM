#!/usr/bin/env python3
"""Apply the narrow KEEP_BOTH rule to source-verified herb mentions nested in formula names.

This is a mention-level decision only. It never creates or infers a
FORMULA_CONTAINS_HERB relation from lexical containment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

REVIEW_FIELDS = {"review_status", "review_decision", "review_note"}
REQUIRED_FIELDS = {
    "pair_id", "unit_id", "document", "source_sha256", "tree_position", "block_id",
    "overlap_kind", "entity_type_pair", "left_type", "left_text", "left_start", "left_end",
    "right_type", "right_text", "right_start", "right_end", "context_start", "context_end",
    "context_text", "review_status", "review_decision", "review_note", "relation_id",
}
RULE_ID = "NESTED_FORMULA_HERB_NAME_KEEP_BOTH_V1"
DECISION = "KEEP_BOTH"
NOTE = (
    "Rule-based semantic review: preserve both typed entity mentions because the complete "
    "HERB span is strictly contained in the FORMULA name span. This name overlap alone "
    "does not create a FORMULA_CONTAINS_HERB relation."
)


def _atomic_write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def review_nested_formula_herb_overlaps(
    input_path: Path, output_path: Path, report_path: Path | None = None,
) -> dict:
    input_path, output_path = Path(input_path), Path(output_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("output must not overwrite the source review queue")
    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        missing = REQUIRED_FIELDS - set(fields)
        if missing:
            raise ValueError("review queue missing fields: " + ", ".join(sorted(missing)))
        rows = list(reader)

    reviewed = 0
    preserved_existing = 0
    for line, row in enumerate(rows, 2):
        status = (row.get("review_status") or "").strip()
        decision = (row.get("review_decision") or "").strip()
        if status == "REVIEWED":
            if not decision:
                raise ValueError(f"row {line}: reviewed row has no decision")
            preserved_existing += 1
            continue
        if status != "UNREVIEWED" or decision:
            raise ValueError(f"row {line}: invalid review status/decision combination")

        if row["entity_type_pair"] != "FORMULA|HERB" or row["overlap_kind"] != "nested_formula_herb_entity":
            continue

        if row["left_type"] == "FORMULA" and row["right_type"] == "HERB":
            formula_prefix, herb_prefix = "left", "right"
        elif row["left_type"] == "HERB" and row["right_type"] == "FORMULA":
            formula_prefix, herb_prefix = "right", "left"
        else:
            raise ValueError(f"row {line}: FORMULA|HERB pair has inconsistent endpoint types")

        # block_id is optional in the catalogue source model. It is still
        # part of the locator tuple (as an empty string when absent), and the
        # unit_id hash binds the complete tuple without requiring each
        # component to be non-empty.
        if not row["unit_id"].strip() or not row["document"].strip() or not row["source_sha256"].strip():
            raise ValueError(f"row {line}: missing source identity")
        locator = (
            row["document"], row["source_sha256"], row["tree_position"], row["block_id"]
        )
        expected_unit_id = hashlib.sha256("\0".join(locator).encode("utf-8")).hexdigest()
        if row["unit_id"] != expected_unit_id:
            raise ValueError(f"row {line}: unit_id/source locator mismatch")
        context_start, context_end = int(row["context_start"]), int(row["context_end"])
        formula_start = int(row[f"{formula_prefix}_start"])
        formula_end = int(row[f"{formula_prefix}_end"])
        herb_start = int(row[f"{herb_prefix}_start"])
        herb_end = int(row[f"{herb_prefix}_end"])
        if not (context_start <= formula_start < formula_end <= context_end):
            raise ValueError(f"row {line}: formula span is outside the evidence window")
        if not (context_start <= herb_start < herb_end <= context_end):
            raise ValueError(f"row {line}: herb span is outside the evidence window")
        if not (
            formula_start <= herb_start and herb_end <= formula_end
            and (formula_start < herb_start or herb_end < formula_end)
        ):
            raise ValueError(f"row {line}: herb is not strictly nested in the formula span")

        context = row["context_text"]
        formula_slice = context[formula_start - context_start:formula_end - context_start]
        herb_slice = context[herb_start - context_start:herb_end - context_start]
        if formula_slice != row[f"{formula_prefix}_text"]:
            raise ValueError(f"row {line}: formula text does not match source evidence offsets")
        if herb_slice != row[f"{herb_prefix}_text"]:
            raise ValueError(f"row {line}: herb text does not match source evidence offsets")

        row["review_status"] = "REVIEWED"
        row["review_decision"] = DECISION
        row["review_note"] = NOTE
        reviewed += 1

    _atomic_write_csv(output_path, fields, rows)
    statuses = Counter(row["review_status"] for row in rows)
    decisions = Counter(
        row["review_decision"] for row in rows if row["review_status"] == "REVIEWED"
    )
    result = {
        "schema_version": 1,
        "source_queue": input_path.name,
        "input_rows": len(rows),
        "reviewed_by_rule": reviewed,
        "preserved_existing_reviewed_rows": preserved_existing,
        "review_status_counts": dict(sorted(statuses.items())),
        "review_decision_counts": dict(sorted(decisions.items())),
        "remaining_unreviewed_rows": statuses.get("UNREVIEWED", 0),
        "rule_id": RULE_ID,
        "decision": DECISION,
        "candidate_mutations": 0,
        "relationship_inferences": 0,
        "output_file": output_path.name,
    }
    if report_path is not None:
        report_path = Path(report_path)
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        report["review_status"] = (
            "PARTIALLY_REVIEWED" if statuses.get("REVIEWED", 0) and statuses.get("UNREVIEWED", 0)
            else "REVIEWED" if statuses.get("REVIEWED", 0) else "UNREVIEWED"
        )
        report["review_status_counts"] = result["review_status_counts"]
        report["review_decision_counts"] = result["review_decision_counts"]
        report["automated_semantic_review"] = {
            "rule_id": RULE_ID,
            "decision": DECISION,
            "reviewed_rows": reviewed,
            "remaining_unreviewed_rows": result["remaining_unreviewed_rows"],
            "scope": "only nested FORMULA/HERB mention spans with exact evidence-window text parity",
            "non_inference": "does not create or infer a formula-herb relation",
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result




def review_nested_formula_herb_overlap_batches(
    batch_dir: Path, report_path: Path,
) -> dict:
    """Apply the narrow rule to deterministic batch rows without breaking the source manifest."""
    batch_dir, report_path = Path(batch_dir), Path(report_path)
    manifest_path = batch_dir / "overlap-review-batches.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    specs = manifest.get("batches")
    if manifest.get("schema_version") != 1 or not isinstance(specs, list):
        raise ValueError("unsupported or malformed overlap batch manifest")
    if int(manifest.get("batch_count", -1)) != len(specs):
        raise ValueError("batch manifest count does not match its batch entries")
    if int(manifest.get("batch_size_limit", 0)) < 1:
        raise ValueError("batch manifest has an invalid batch size limit")

    seen: set[str] = set()
    total_rows = 0
    total_reviewed = 0
    total_preserved_reviewed = 0
    status_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()

    for index, spec in enumerate(specs, 1):
        filename = spec.get("file", "")
        if not filename or Path(filename).name != filename:
            raise ValueError(f"manifest batch {index}: unsafe batch filename")
        path = batch_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)

        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        if len(rows) != int(spec.get("rows", -1)):
            raise ValueError(f"{filename}: row count differs from manifest")
        pair_ids = []
        for line, row in enumerate(rows, 2):
            pair_id = (row.get("pair_id") or "").strip()
            if not pair_id:
                raise ValueError(f"{filename} row {line}: empty pair_id")
            if pair_id in seen:
                raise ValueError(f"{filename} row {line}: duplicate pair_id across batches: {pair_id}")
            seen.add(pair_id)
            pair_ids.append(pair_id)
        observed_hash = hashlib.sha256("\n".join(pair_ids).encode("utf-8")).hexdigest()
        if observed_hash != spec.get("pair_ids_sha256"):
            raise ValueError(f"{filename}: pair-ID hash differs from manifest")

        temporary = path.with_name(path.name + ".reviewed.tmp")
        result = review_nested_formula_herb_overlaps(path, temporary, None)
        os.replace(temporary, path)
        total_rows += result["input_rows"]
        total_reviewed += result["reviewed_by_rule"]
        total_preserved_reviewed += result["preserved_existing_reviewed_rows"]
        status_counts.update(result["review_status_counts"])
        decision_counts.update(result["review_decision_counts"])

    if total_rows != int(manifest.get("input_rows", -1)):
        raise ValueError("manifest batch row totals do not match input_rows")

    result = {
        "schema_version": 1,
        "source_queue": manifest.get("input_file", ""),
        "source_sha256": manifest.get("input_sha256", ""),
        "input_rows": total_rows,
        "batch_count": len(specs),
        "reviewed_by_rule": total_reviewed,
        "preserved_existing_reviewed_rows": total_preserved_reviewed,
        "review_status_counts": dict(sorted(status_counts.items())),
        "review_decision_counts": dict(sorted(decision_counts.items())),
        "remaining_unreviewed_rows": status_counts.get("UNREVIEWED", 0),
        "rule_id": RULE_ID,
        "decision": DECISION,
        "candidate_mutations": 0,
        "relationship_inferences": 0,
        "batches_updated_in_place": True,
    }
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    report["review_status"] = (
        "PARTIALLY_REVIEWED" if status_counts.get("REVIEWED", 0) and status_counts.get("UNREVIEWED", 0)
        else "REVIEWED" if status_counts.get("REVIEWED", 0) else "UNREVIEWED"
    )
    report["review_status_counts"] = result["review_status_counts"]
    report["review_decision_counts"] = result["review_decision_counts"]
    report["automated_semantic_review"] = {
        "rule_id": RULE_ID,
        "decision": DECISION,
        "reviewed_rows": total_reviewed,
        "remaining_unreviewed_rows": result["remaining_unreviewed_rows"],
        "scope": "only nested FORMULA/HERB mention spans with exact evidence-window text parity",
        "non_inference": "does not create or infer a formula-herb relation",
        "source_manifest_preserved": True,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path,
        default=Path("catalog/generated/entity_mention_overlap_review_batches"))
    parser.add_argument("--report", type=Path,
        default=Path("catalog/generated/entity_mention_cross_type_overlap_review.json"))
    args = parser.parse_args()
    review_nested_formula_herb_overlap_batches(args.batch_dir, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
