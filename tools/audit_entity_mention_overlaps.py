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


def audit(path: Path, output: Path, max_examples: int = 50,
          relations_path: Path | None = None,
          content_index_path: Path | None = None) -> dict[str, Any]:
    by_unit: dict[str, list[dict[str, str]]] = defaultdict(list)
    mention_ids: set[str] = set()
    mentions_by_id: dict[str, dict[str, str]] = {}
    relation_pairs: set[tuple[str, str]] = set()
    relation_rows: list[dict[str, str]] = []
    relation_fields: set[str] = set()
    relation_count = 0
    if relations_path is not None:
        with relations_path.open("r", encoding="utf-8", newline="") as relation_stream:
            reader = csv.DictReader(relation_stream)
            relation_fields = set(reader.fieldnames or [])
            required_relations = {"subject_mention_id", "object_mention_id", "relation_id"}
            missing_relations = required_relations - set(reader.fieldnames or [])
            if missing_relations:
                raise ValueError("relation input missing fields: " + ", ".join(sorted(missing_relations)))
            seen_relation_ids: set[str] = set()
            for row in reader:
                if not row["relation_id"] or row["relation_id"] in seen_relation_ids:
                    raise ValueError("relation input has a missing or duplicate relation_id")
                seen_relation_ids.add(row["relation_id"])
                if not row["subject_mention_id"] or not row["object_mention_id"]:
                    raise ValueError("relation input has a missing endpoint mention_id")
                pair = (row["subject_mention_id"], row["object_mention_id"])
                if pair in relation_pairs:
                    raise ValueError("relation input has a duplicate endpoint pair")
                relation_pairs.add(pair)
                relation_rows.append(row)
                relation_count += 1

    source_blocks: dict[tuple[str, str, str, str], str] = {}
    source_span_checked = 0
    if content_index_path is not None:
        with gzip.open(content_index_path, "rt", encoding="utf-8-sig", newline="") as content_stream:
            content_reader = csv.DictReader(content_stream)
            required_content = {"document", "source_sha256", "tree_position", "block_id", "content_text"}
            missing_content = required_content - set(content_reader.fieldnames or [])
            if missing_content:
                raise ValueError("content index missing fields: " + ", ".join(sorted(missing_content)))
            for content_row in content_reader:
                locator = (content_row["document"], content_row["source_sha256"],
                           content_row["tree_position"], content_row["block_id"])
                if locator in source_blocks:
                    raise ValueError("content index has a duplicate source locator: " + repr(locator))
                source_blocks[locator] = content_row["content_text"]

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
            if not row["mention_id"] or row["mention_id"] in mention_ids:
                raise ValueError("mention input has a missing or duplicate mention_id")
            mention_ids.add(row["mention_id"])
            mentions_by_id[row["mention_id"]] = row
            start, end = int(row["character_start"]), int(row["character_end"])
            if start < 0 or end <= start or end - start != len(row["matched_text"]):
                raise ValueError(f"invalid mention span: {row['mention_id']}")
            if content_index_path is not None:
                locator = (row["document"], row["source_sha256"], row["tree_position"], row["block_id"])
                source_text = source_blocks.get(locator)
                if source_text is None:
                    raise ValueError(f"mention source locator cannot be resolved: {row['mention_id']}")
                if end > len(source_text) or source_text[start:end] != row["matched_text"]:
                    raise ValueError(f"mention source span does not match source text: {row['mention_id']}")
                source_span_checked += 1
            by_unit[row["unit_id"]].append(row)

    endpoint_reference_counts: Counter[str] = Counter()
    endpoint_reference_examples: list[dict[str, Any]] = []
    for relation in relation_rows:
        subject = mentions_by_id.get(relation["subject_mention_id"])
        obj = mentions_by_id.get(relation["object_mention_id"])
        if subject is None or obj is None:
            missing = [
                mention_id for mention_id, record in (
                    (relation["subject_mention_id"], subject),
                    (relation["object_mention_id"], obj),
                ) if record is None
            ]
            raise ValueError(
                "relation endpoint mention_id not found in input mentions: "
                + ", ".join(missing)
            )
        endpoint_reference_counts["resolved_endpoint_references"] += 2
        expected = (
            (subject, "FORMULA", relation.get("subject_text", "")),
            (obj, "HERB", relation.get("object_text", "")),
        )
        for mention, expected_type, expected_text in expected:
            if mention["entity_type"] != expected_type:
                raise ValueError(
                    f"relation endpoint {mention['mention_id']} has type "
                    f"{mention['entity_type']}, expected {expected_type}"
                )
            if expected_text and mention["matched_text"] != expected_text:
                raise ValueError(
                    f"relation endpoint {mention['mention_id']} text does not "
                    "match the input mention candidate"
                )
            endpoint_reference_counts["type_text_matched_endpoint_references"] += 1

        if {"document", "source_sha256", "tree_position", "block_id", "unit_id"}.issubset(relation_fields):
            if (subject["document"] != relation["document"]
                or subject["source_sha256"] != relation["source_sha256"]):
                raise ValueError(
                    f"relation {relation['relation_id']} subject source document mismatch"
                )
            if (obj["document"] != relation["document"]
                or obj["source_sha256"] != relation["source_sha256"]
                or obj["tree_position"] != relation["tree_position"]
                or obj["block_id"] != relation["block_id"]
                or obj["unit_id"] != relation["unit_id"]):
                raise ValueError(
                    f"relation {relation['relation_id']} object source locator mismatch"
                )
            endpoint_reference_counts["source_locator_matched_relations"] += 1

        if len(endpoint_reference_examples) < max_examples:
            endpoint_reference_examples.append({
                "relation_id": relation["relation_id"],
                "subject_mention_id": subject["mention_id"],
                "subject_text": subject["matched_text"],
                "subject_unit_id": subject["unit_id"],
                "subject_document": subject["document"],
                "subject_tree_position": subject["tree_position"],
                "subject_block_id": subject["block_id"],
                "subject_source_sha256": subject["source_sha256"],
                "subject_character_start": int(subject["character_start"]),
                "subject_character_end": int(subject["character_end"]),
                "object_mention_id": obj["mention_id"],
                "object_text": obj["matched_text"],
                "object_unit_id": obj["unit_id"],
                "object_document": obj["document"],
                "object_tree_position": obj["tree_position"],
                "object_block_id": obj["block_id"],
                "object_source_sha256": obj["source_sha256"],
                "object_character_start": int(obj["character_start"]),
                "object_character_end": int(obj["character_end"]),
                "evidence_unit_id": relation.get("unit_id", ""),
                "evidence_document": relation.get("document", ""),
                "evidence_block_id": relation.get("block_id", ""),
                "evidence_sentence_start": relation.get("sentence_start", ""),
                "evidence_sentence_end": relation.get("sentence_end", ""),
                "evidence_text": relation.get("evidence_text", ""),
                "extraction_rule": relation.get("extraction_rule", ""),
                "resolution_status": relation.get("resolution_status", ""),
            })

    pair_counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    relation_link_counts: Counter[str] = Counter()
    relation_link_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
                if kind == "nested_formula_herb_entity" and relations_path is not None:
                    formula = prior if prior["entity_type"] == "FORMULA" else current
                    herb = prior if prior["entity_type"] == "HERB" else current
                    link_kind = ("relation_candidate_linked"
                                 if (formula["mention_id"], herb["mention_id"]) in relation_pairs
                                 else "no_relation_candidate_link")
                    relation_link_counts[link_kind] += 1
                    if len(relation_link_examples[link_kind]) < max_examples:
                        relation_link_examples[link_kind].append({
                            "unit_id": unit_id,
                            "document": current["document"],
                            "tree_position": current["tree_position"],
                            "formula_mention_id": formula["mention_id"],
                            "formula_text": formula["matched_text"],
                            "formula_start": int(formula["character_start"]),
                            "formula_end": int(formula["character_end"]),
                            "herb_mention_id": herb["mention_id"],
                            "herb_text": herb["matched_text"],
                            "herb_start": int(herb["character_start"]),
                            "herb_end": int(herb["character_end"]),
                        })
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
        "source_span_validation": ({
            "source_blocks": len(source_blocks),
            "checked_mentions": source_span_checked,
            "status": "PASS",
        } if content_index_path is not None else {"status": "NOT_RUN"}),
        "overlap_pair_counts": {
            key: pair_counts.get(key, 0) for key in (
                "same_type_exact_duplicate_window", "cross_type_exact_span",
                "nested_formula_herb_entity", "nested_named_formula",
                "nested_same_type_window", "nested_cross_type_entity", "partial_overlap",
            )
        },
        "relation_candidate_cross_reference": ({
            "relation_candidate_rows": relation_count,
            "endpoint_reference": {
                "endpoint_references": relation_count * 2,
                "resolved_endpoint_references": endpoint_reference_counts.get(
                    "resolved_endpoint_references", 0
                ),
                "source_locator_matched_relations": endpoint_reference_counts.get(
                    "source_locator_matched_relations", 0
                ),
                "type_text_matched_endpoint_references": endpoint_reference_counts.get(
                    "type_text_matched_endpoint_references", 0
                ),
                "examples": endpoint_reference_examples,
                "interpretation": (
                    "Each subject/object mention ID must resolve to exactly one input "
                    "candidate with the expected FORMULA/HERB type and matching text. "
                    "Endpoint source locators are shown separately from the evidence unit. The subject must belong to the same source document; the object must belong to the exact evidence unit/block."
                ),
            },
            "same_unit_nested_formula_herb_pairs": sum(relation_link_counts.values()),
            "linked_same_unit_nested_pairs": relation_link_counts.get("relation_candidate_linked", 0),
            "unlinked_same_unit_nested_pairs": relation_link_counts.get("no_relation_candidate_link", 0),
            "examples": dict(sorted(relation_link_examples.items())),
            "interpretation": "These linked/unlinked counts apply only to FORMULA/HERB mentions nested in the same source unit. Nearby-block relations intentionally reference a formula mention in a sibling unit, so they are audited separately by endpoint_reference and source-locator checks. An unlinked same-unit nested pair is not thereby proven false or semantically invalid.",
        } if relations_path is not None else None),
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
        "source_span_validation": ({
            "source_blocks": len(source_blocks),
            "checked_mentions": source_span_checked,
            "status": "PASS",
        } if content_index_path is not None else {"status": "NOT_RUN"}),
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
    parser.add_argument("--relations", type=Path,
                        help="optional formula-herb relation CSV for endpoint cross-reference")
    parser.add_argument("--content-index", type=Path,
                        help="optional exact source-block index for validating every mention offset")
    args = parser.parse_args()
    if args.max_examples < 1:
        parser.error("--max-examples must be >= 1")
    print(json.dumps(audit(args.mentions, args.output, args.max_examples, args.relations,
                            args.content_index), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
