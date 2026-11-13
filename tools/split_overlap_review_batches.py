#!/usr/bin/env python3
"""Split a full overlap-review CSV into deterministic, balanced human-review batches.

This utility only partitions review rows. It never assigns semantic decisions or
modifies source candidates. Pair IDs and every original column are preserved.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path


def split_review_batches(input_path: Path, output_dir: Path, batch_size: int) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    with input_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        if not fields:
            raise ValueError("review queue has no CSV header")
        pair_id_field = "pair_id"
        if pair_id_field not in fields:
            raise ValueError("review queue is missing pair_id")
        stratum_fields = [
            field for field in ("candidate_type_pair", "entity_type_pair", "overlap_kind")
            if field in fields
        ]
        if not stratum_fields:
            raise ValueError("review queue has no supported semantic review strata")
        rows = list(reader)

    seen: set[str] = set()
    for line, row in enumerate(rows, 2):
        pair_id = (row.get(pair_id_field) or "").strip()
        if not pair_id:
            raise ValueError(f"row {line}: pair_id is empty")
        if pair_id in seen:
            raise ValueError(f"row {line}: duplicate pair_id {pair_id}")
        seen.add(pair_id)
        if row.get("review_status") not in (None, "", "UNREVIEWED"):
            raise ValueError(f"row {line}: refusing to repartition an already reviewed row")

    strata: dict[tuple[str, ...], list[dict]] = {}
    for row in rows:
        key = tuple(row.get(field, "") for field in stratum_fields)
        strata.setdefault(key, []).append(row)
    for members in strata.values():
        members.sort(key=lambda row: row["pair_id"])

    ordered: list[dict] = []
    # Interleave strata so a small first batch is not dominated by one overlap type.
    max_depth = max((len(members) for members in strata.values()), default=0)
    for depth in range(max_depth):
        for key in sorted(strata):
            members = strata[key]
            if depth < len(members):
                ordered.append(members[depth])

    batch_count = max(1, (len(ordered) + batch_size - 1) // batch_size)
    batches: list[list[dict]] = [[] for _ in range(batch_count)]
    for index, row in enumerate(ordered):
        batches[index % batch_count].append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_batches = []
    for index, batch in enumerate(batches, 1):
        batch.sort(key=lambda row: (tuple(row.get(field, "") for field in stratum_fields), row["pair_id"]))
        filename = f"overlap-review-batch-{index:03d}.csv"
        target = output_dir / filename
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(batch)
        counts = Counter(" | ".join(row.get(field, "") for field in stratum_fields) for row in batch)
        manifest_batches.append({
            "file": filename,
            "rows": len(batch),
            "strata": dict(sorted(counts.items())),
            "pair_ids_sha256": hashlib.sha256(
                "\n".join(row["pair_id"] for row in batch).encode("utf-8")
            ).hexdigest(),
        })

    manifest = {
        "schema_version": 1,
        "input_file": input_path.name,
        "input_sha256": digest,
        "input_rows": len(rows),
        "batch_size_limit": batch_size,
        "batch_count": len(batches),
        "stratum_fields": stratum_fields,
        "review_decisions_assigned": 0,
        "candidate_mutations": 0,
        "batches": manifest_batches,
    }
    (output_dir / "overlap-review-batches.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(
        split_review_batches(args.input, args.output_dir, args.batch_size),
        ensure_ascii=False, sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
