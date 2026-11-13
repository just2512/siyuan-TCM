#!/usr/bin/env python3
"""Validate and merge human decisions from deterministic overlap-review batches.

The source queue is the immutable identity/provenance baseline. Only
review_status, review_decision and review_note may differ in returned batches.
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
REVIEW_STATUSES = {"UNREVIEWED", "REVIEWED"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        if not fields:
            raise ValueError(f"{path}: missing CSV header")
        return fields, list(reader)


def merge_review_batches(
    source_queue: Path,
    batch_dir: Path,
    output_path: Path,
    report_path: Path | None = None,
) -> dict:
    source_queue = Path(source_queue)
    batch_dir = Path(batch_dir)
    output_path = Path(output_path)
    if output_path.resolve() == source_queue.resolve():
        raise ValueError("output must not overwrite the source review queue")

    source_sha = sha256_file(source_queue)
    source_fields, source_rows = read_rows(source_queue)
    required = {"pair_id"} | REVIEW_FIELDS
    missing = required - set(source_fields)
    if missing:
        raise ValueError("source queue missing fields: " + ", ".join(sorted(missing)))

    source_by_id: dict[str, dict[str, str]] = {}
    for line, row in enumerate(source_rows, 2):
        pair_id = (row.get("pair_id") or "").strip()
        if not pair_id:
            raise ValueError(f"source row {line}: empty pair_id")
        if pair_id in source_by_id:
            raise ValueError(f"source row {line}: duplicate pair_id {pair_id}")
        source_by_id[pair_id] = row

    manifest_path = batch_dir / "overlap-review-batches.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported overlap batch manifest schema")
    if manifest.get("input_file") != source_queue.name:
        raise ValueError("batch manifest input filename does not match source queue")
    if manifest.get("input_sha256") != source_sha:
        raise ValueError("batch manifest source SHA-256 does not match source queue")
    if int(manifest.get("input_rows", -1)) != len(source_rows):
        raise ValueError("batch manifest source row count does not match source queue")

    batch_specs = manifest.get("batches")
    if not isinstance(batch_specs, list) or int(manifest.get("batch_count", -1)) != len(batch_specs):
        raise ValueError("batch manifest count does not match its batch entries")
    batch_size_limit = int(manifest.get("batch_size_limit", 0))
    if batch_size_limit < 1:
        raise ValueError("batch manifest has an invalid batch size limit")

    merged_by_id: dict[str, dict[str, str]] = {}
    for batch_index, spec in enumerate(batch_specs, 1):
        filename = spec.get("file", "")
        if not filename or Path(filename).name != filename:
            raise ValueError(f"manifest batch {batch_index}: unsafe batch filename")
        batch_path = batch_dir / filename
        if not batch_path.is_file():
            raise FileNotFoundError(batch_path)
        fields, rows = read_rows(batch_path)
        if fields != source_fields:
            raise ValueError(f"{filename}: columns differ from the source queue")
        if len(rows) != int(spec.get("rows", -1)):
            raise ValueError(f"{filename}: row count differs from manifest")
        if len(rows) > batch_size_limit:
            raise ValueError(f"{filename}: exceeds batch size limit")

        ordered_pair_ids: list[str] = []
        for line, row in enumerate(rows, 2):
            pair_id = (row.get("pair_id") or "").strip()
            if not pair_id:
                raise ValueError(f"{filename} row {line}: empty pair_id")
            if pair_id in merged_by_id:
                raise ValueError(f"{filename} row {line}: pair_id appears in more than one batch: {pair_id}")
            source = source_by_id.get(pair_id)
            if source is None:
                raise ValueError(f"{filename} row {line}: unknown pair_id {pair_id}")

            for field in source_fields:
                if field not in REVIEW_FIELDS and row.get(field, "") != source.get(field, ""):
                    raise ValueError(f"{filename} row {line}: immutable field changed: {field}")

            status = (row.get("review_status") or "").strip()
            decision = (row.get("review_decision") or "").strip()
            if status not in REVIEW_STATUSES:
                raise ValueError(f"{filename} row {line}: unsupported review_status {status!r}")
            if status == "REVIEWED" and not decision:
                raise ValueError(f"{filename} row {line}: reviewed row has no review_decision")
            if status == "UNREVIEWED" and decision:
                raise ValueError(f"{filename} row {line}: unreviewed row carries a review_decision")

            ordered_pair_ids.append(pair_id)
            merged_by_id[pair_id] = row

        observed_hash = hashlib.sha256("\n".join(ordered_pair_ids).encode("utf-8")).hexdigest()
        if observed_hash != spec.get("pair_ids_sha256"):
            raise ValueError(f"{filename}: pair-ID hash differs from manifest")

    missing_ids = set(source_by_id) - set(merged_by_id)
    extra_ids = set(merged_by_id) - set(source_by_id)
    if missing_ids or extra_ids:
        raise ValueError(
            f"batch coverage mismatch: missing={len(missing_ids)}, extra={len(extra_ids)}"
        )
    if sum(int(spec.get("rows", -1)) for spec in batch_specs) != len(source_rows):
        raise ValueError("manifest batch row totals do not match source queue")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=output_path.name + ".", suffix=".tmp",
                                           dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=source_fields)
            writer.writeheader()
            for source in source_rows:
                writer.writerow(merged_by_id[source["pair_id"]])
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    statuses = Counter(row["review_status"] for row in merged_by_id.values())
    decisions = Counter(
        row["review_decision"].strip()
        for row in merged_by_id.values()
        if row["review_status"] == "REVIEWED"
    )
    result = {
        "schema_version": 1,
        "source_queue": source_queue.name,
        "source_sha256": source_sha,
        "input_rows": len(source_rows),
        "batch_count": len(batch_specs),
        "review_status_counts": dict(sorted(statuses.items())),
        "review_decision_counts": dict(sorted(decisions.items())),
        "output_file": output_path.name,
        "review_decisions_assigned_by_tool": 0,
        "candidate_mutations": 0,
    }
    destination_report = report_path or output_path.with_name(output_path.name + ".report.json")
    destination_report.parent.mkdir(parents=True, exist_ok=True)
    destination_report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-queue", type=Path, required=True)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    merge_review_batches(args.source_queue, args.batch_dir, args.output, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
