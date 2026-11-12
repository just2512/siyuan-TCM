#!/usr/bin/env python3
"""Export every cross-type entity-mention overlap for source-grounded semantic review."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path

SENTENCE_BOUNDARIES = "。！？；\\n"
AUTHOR_ATTRIBUTION_BOUNDARY = re.compile(
    r"(?:[\\u3400-\\u9fff]{1,8}(?:曰|云)[：:∶]|《[^》\\n]{1,40}》(?:曰|云)[：:∶])"
)
MENTION_FIELDS = {
    "mention_id", "unit_id", "entity_type", "matched_text", "character_start",
    "character_end", "document", "source_sha256", "tree_position", "block_id",
}
CONTENT_FIELDS = {"document", "source_sha256", "tree_position", "block_id", "content_text"}


def classify_pair(left: dict, right: dict) -> str:
    ls, le = left["start"], left["end"]
    rs, re_ = right["start"], right["end"]
    if ls == rs and le == re_:
        return "cross_type_exact_span"
    if ls <= rs and re_ <= le or rs <= ls and le <= re_:
        if {left["entity_type"], right["entity_type"]} == {"FORMULA", "HERB"}:
            return "nested_formula_herb_entity"
        return "nested_cross_type_entity"
    return "partial_overlap"


def bounded_context(source: str, start: int, end: int, context: int = 24) -> tuple[int, int]:
    left = max(0, start - context)
    right = min(len(source), end + context)
    prior_sentence = max((source.rfind(mark, left, start) for mark in SENTENCE_BOUNDARIES), default=-1)
    left = max(left, prior_sentence + 1)
    next_sentences = [source.find(mark, end, right) for mark in SENTENCE_BOUNDARIES]
    next_sentences = [pos for pos in next_sentences if pos >= 0]
    if next_sentences:
        right = min(right, min(next_sentences))
    for match in AUTHOR_ATTRIBUTION_BOUNDARY.finditer(source, left, start):
        left = max(left, match.end())
    next_author = AUTHOR_ATTRIBUTION_BOUNDARY.search(source, end, right)
    if next_author:
        right = min(right, next_author.start())
    return left, right


def load_relations(path: Path | None) -> dict[tuple[str, str], str]:
    links: dict[tuple[str, str], str] = {}
    if path is None:
        return links
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"relation_id", "subject_mention_id", "object_mention_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("relation input missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            key = (row["subject_mention_id"], row["object_mention_id"])
            if not all(key) or not row["relation_id"] or key in links:
                raise ValueError(f"relation input has invalid or duplicate endpoint pair at row {line}")
            links[key] = row["relation_id"]
    return links


def build_review_queue(
    mentions_path: Path, content_index_path: Path, output_path: Path,
    report_path: Path, relations_path: Path | None = None,
) -> dict:
    source_blocks: dict[tuple[str, str, str, str], str] = {}
    with gzip.open(content_index_path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = CONTENT_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("content index missing fields: " + ", ".join(sorted(missing)))
        for row in reader:
            locator = (row["document"], row["source_sha256"], row["tree_position"], row["block_id"])
            if locator in source_blocks:
                raise ValueError(f"duplicate source locator: {locator}")
            source_blocks[locator] = row["content_text"]

    relation_links = load_relations(relations_path)
    mentions: dict[str, dict] = {}
    by_unit: dict[str, list[dict]] = defaultdict(list)
    type_counts: Counter[str] = Counter()
    with gzip.open(mentions_path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = MENTION_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("mention input missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            mention_id = row["mention_id"]
            if not mention_id or mention_id in mentions:
                raise ValueError(f"missing or duplicate mention_id at row {line}")
            start, end = int(row["character_start"]), int(row["character_end"])
            if start < 0 or end <= start or end - start != len(row["matched_text"]):
                raise ValueError(f"invalid mention span at row {line}")
            locator = (row["document"], row["source_sha256"], row["tree_position"], row["block_id"])
            expected_unit = hashlib.sha256(
                "\\0".join(locator).encode("utf-8")
            ).hexdigest()
            if row["unit_id"] != expected_unit:
                raise ValueError(f"mention unit_id/source locator mismatch: {mention_id}")
            source = source_blocks.get(locator)
            if source is None:
                raise ValueError(f"mention source locator cannot be resolved: {mention_id}")
            if end > len(source) or source[start:end] != row["matched_text"]:
                raise ValueError(f"mention source span mismatch: {mention_id}")
            item = {
                "mention_id": mention_id, "unit_id": row["unit_id"],
                "entity_type": row["entity_type"], "matched_text": row["matched_text"],
                "start": start, "end": end, "locator": locator, "source": source,
            }
            mentions[mention_id] = item
            by_unit[row["unit_id"]].append(item)
            type_counts[row["entity_type"]] += 1

    for (subject_id, object_id), relation_id in relation_links.items():
        if subject_id not in mentions or object_id not in mentions:
            raise ValueError(f"relation endpoint not found in mention input: {relation_id}")
        if mentions[subject_id]["entity_type"] != "FORMULA" or mentions[object_id]["entity_type"] != "HERB":
            raise ValueError(f"relation endpoint type mismatch: {relation_id}")

    rows: list[dict] = []
    by_pair_type: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    relation_linked = 0
    for unit_id, items in by_unit.items():
        items.sort(key=lambda item: (item["start"], item["end"], item["entity_type"], item["mention_id"]))
        active: list[dict] = []
        for current in items:
            active = [prior for prior in active if prior["end"] > current["start"]]
            for prior in active:
                if prior["entity_type"] == current["entity_type"]:
                    continue
                if prior["locator"] != current["locator"]:
                    raise ValueError(f"overlapping mentions have different source locators: {unit_id}")
                left, right = prior, current
                start, end = min(left["start"], right["start"]), max(left["end"], right["end"])
                source = left["source"]
                context_start, context_end = bounded_context(source, start, end)
                pair_type = "|".join(sorted((left["entity_type"], right["entity_type"])))
                kind = classify_pair(left, right)
                relation_id = ""
                if {left["entity_type"], right["entity_type"]} == {"FORMULA", "HERB"}:
                    formula = left if left["entity_type"] == "FORMULA" else right
                    herb = left if left["entity_type"] == "HERB" else right
                    relation_id = relation_links.get((formula["mention_id"], herb["mention_id"]), "")
                    if relation_id:
                        relation_linked += 1
                rows.append({
                    "pair_id": f"{unit_id}:{left['mention_id']}:{right['mention_id']}",
                    "unit_id": unit_id, "document": left["locator"][0],
                    "source_sha256": left["locator"][1], "tree_position": left["locator"][2],
                    "block_id": left["locator"][3], "overlap_kind": kind,
                    "entity_type_pair": pair_type,
                    "left_mention_id": left["mention_id"], "left_type": left["entity_type"],
                    "left_text": left["matched_text"], "left_start": left["start"], "left_end": left["end"],
                    "right_mention_id": right["mention_id"], "right_type": right["entity_type"],
                    "right_text": right["matched_text"], "right_start": right["start"], "right_end": right["end"],
                    "relation_id": relation_id,
                    "context_start": context_start, "context_end": context_end,
                    "context_text": source[context_start:context_end],
                    "review_status": "UNREVIEWED", "review_decision": "", "review_note": "",
                })
                by_pair_type[pair_type] += 1
                by_kind[kind] += 1
            active.append(current)

    rows.sort(key=lambda row: (row["document"], row["tree_position"], row["block_id"],
        row["left_start"], row["right_start"], row["pair_id"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else [
        "pair_id", "unit_id", "document", "source_sha256", "tree_position", "block_id",
        "overlap_kind", "entity_type_pair", "left_mention_id", "left_type", "left_text",
        "left_start", "left_end", "right_mention_id", "right_type", "right_text",
        "right_start", "right_end", "relation_id", "context_start", "context_end",
        "context_text", "review_status", "review_decision", "review_note",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "schema_version": 1,
        "source_mentions": len(mentions),
        "source_blocks": len(source_blocks),
        "cross_type_overlap_pairs": len(rows),
        "cross_type_pairs_by_type": dict(sorted(by_pair_type.items())),
        "cross_type_pairs_by_kind": dict(sorted(by_kind.items())),
        "formula_herb_pairs_linked_to_relation_candidates": relation_linked,
        "review_status": "UNREVIEWED",
        "policy": {
            "candidate_mutation": "none",
            "overlap": "every cross-type overlap is retained for semantic review; geometric containment is not a deletion rule",
            "formula_herb": "relation_id is populated only when this exact FORMULA/HERB mention pair is already linked by a relation candidate",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mentions", type=Path,
        default=Path("catalog/generated/entity_mention_candidates.csv.gz"))
    parser.add_argument("--content-index", type=Path,
        default=Path("catalog/generated/content_block_index.csv.gz"))
    parser.add_argument("--relations", type=Path,
        default=Path("catalog/generated/formula_herb_relation_candidates.csv"))
    parser.add_argument("--output", type=Path,
        default=Path("catalog/generated/entity_mention_cross_type_overlap_review.csv"))
    parser.add_argument("--report", type=Path,
        default=Path("catalog/generated/entity_mention_cross_type_overlap_review.json"))
    args = parser.parse_args()
    build_review_queue(args.mentions, args.content_index, args.output, args.report, args.relations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
