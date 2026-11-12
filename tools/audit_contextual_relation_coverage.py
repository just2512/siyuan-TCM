#!/usr/bin/env python3
"""Audit explicit contextual-relation predicate coverage without weakening extraction."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

MAX_EXAMPLES_PER_DIAGNOSIS = 5
MAX_CANDIDATE_SPANS_PER_EXAMPLE = 12

from build_contextual_relation_candidates import (
    NEGATION_PREFIX,
    OBJECT_TYPES,
    PREDICATES,
    SUBJECT_TYPES,
    RELATION_SCOPE_BREAKS,
    canonicalize_spans,
    load_context_candidates,
    load_formula_mentions,
    sentence_ranges,
    relation_identity,
)


def audit(context_path: Path, mentions_path: Path, units_path: Path,
          relations_path: Path, output_path: Path) -> dict:
    candidates = load_context_candidates(context_path)
    formulas = load_formula_mentions(mentions_path)
    counts = {
        predicate: {
            "marker_occurrences": 0,
            "sentences_with_marker": 0,
            "ordered_typed_pairs": 0,
            "pairs_with_predicate_between": 0,
            "negated_pairs": 0,
            "scope_break_pairs": 0,
            "eligible_pairs": 0,
            "marker_sentences_without_typed_pair": 0,
            "typed_pair_sentences_without_marker": 0,
            "marker_sentences_with_subject_type": 0,
            "marker_sentences_with_object_type": 0,
            "marker_sentences_with_both_endpoint_types": 0,
            "marker_sentences_with_both_types_but_no_ordered_pair": 0,
            "marker_sentences_with_ordered_pair_but_no_predicate_between": 0,
            "marker_sentences_without_subject_type": 0,
            "marker_sentences_without_object_type": 0,
            "units_with_marker": 0,
            "units_with_eligible_pair": 0,
            "extracted_rows": 0,
        }
        for predicate in PREDICATES
    }
    marker_units = {key: set() for key in PREDICATES}
    eligible_units = {key: set() for key in PREDICATES}
    examples = {key: defaultdict(list) for key in PREDICATES}
    expected_relation_ids: dict[str, str] = {}

    def add_example(predicate: str, diagnosis: str, unit: dict,
                    sentence_start: int, sentence_end: int, sentence: str,
                    spans: list[tuple[int, int, dict]],
                    marker_matches: list) -> None:
        bucket = examples[predicate][diagnosis]
        if len(bucket) >= MAX_EXAMPLES_PER_DIAGNOSIS:
            return
        source = unit["source"]
        candidate_spans = [
            {
                "candidate_id": row["candidate_id"],
                "term": row["term"],
                "candidate_type": row["candidate_type"],
                "start": start,
                "end": end,
            }
            for start, end, row in spans[:MAX_CANDIDATE_SPANS_PER_EXAMPLE]
        ]
        bucket.append({
            "unit_id": unit["unit_id"],
            "document": source["document"],
            "source_sha256": source["sha256"],
            "tree_position": source["tree_position"],
            "block_id": source.get("block_id", ""),
            "sentence_start": sentence_start,
            "sentence_end": sentence_end,
            "sentence_text": sentence[:600],
            "sentence_truncated": len(sentence) > 600,
            "typed_candidate_spans": candidate_spans,
            "candidate_spans_truncated": len(spans) > MAX_CANDIDATE_SPANS_PER_EXAMPLE,
            "predicate_marker_spans": [
                {
                    "text": match.group(0),
                    "start": sentence_start + match.start(),
                    "end": sentence_start + match.end(),
                }
                for match in marker_matches
            ],
        })

    with gzip.open(units_path, "rt", encoding="utf-8", newline="") as stream:
        for raw in stream:
            unit = json.loads(raw)
            unit_id = unit["unit_id"]
            source = unit["source"]
            text = unit["content"]["source_text"]
            unit_candidates = candidates.pop(unit_id, [])
            unit_formulas = formulas.get(unit_id, [])
            rows = unit_candidates + unit_formulas

            for row in rows:
                start, end = int(row["character_start"]), int(row["character_end"])
                if (row["document"] != source["document"]
                    or row["source_sha256"] != source["sha256"]
                    or row["tree_position"] != source["tree_position"]
                    or row["block_id"] != source.get("block_id", "")):
                    raise ValueError(f"candidate source provenance mismatch: {unit_id}")
                if start < 0 or end <= start or end > len(text) or text[start:end] != row["term"]:
                    raise ValueError(f"candidate span mismatch: {unit_id}:{start}-{end}")

            for sentence_start, sentence_end in sentence_ranges(text):
                sentence = text[sentence_start:sentence_end]
                spans = []
                for row in rows:
                    start, end = int(row["character_start"]), int(row["character_end"])
                    if sentence_start <= start and end <= sentence_end and end > start:
                        spans.append((start, end, row))
                spans = canonicalize_spans(spans)
                for predicate, marker in PREDICATES.items():
                    marker_matches = list(marker.finditer(sentence))
                    if marker_matches:
                        counts[predicate]["marker_occurrences"] += len(marker_matches)
                        counts[predicate]["sentences_with_marker"] += 1
                        marker_units[predicate].add(unit_id)

                    subject_types = SUBJECT_TYPES[predicate.split("_TO_")[0]]
                    object_types = OBJECT_TYPES[predicate]
                    subject_rows = [row for _, _, row in spans
                                    if row["candidate_type"] in subject_types]
                    object_rows = [row for _, _, row in spans
                                   if row["candidate_type"] in object_types]
                    if marker_matches:
                        stats = counts[predicate]
                        stats["marker_sentences_with_subject_type"] += bool(subject_rows)
                        stats["marker_sentences_with_object_type"] += bool(object_rows)
                        stats["marker_sentences_with_both_endpoint_types"] += bool(subject_rows and object_rows)
                        stats["marker_sentences_without_subject_type"] += not bool(subject_rows)
                        stats["marker_sentences_without_object_type"] += not bool(object_rows)
                        type_counts = stats.setdefault("typed_candidate_mentions_by_type_in_marker_sentences", {})
                        for _, _, row in spans:
                            candidate_type = row["candidate_type"]
                            type_counts[candidate_type] = type_counts.get(candidate_type, 0) + 1
                        if not subject_rows and not object_rows:
                            add_example(predicate, "missing_both_endpoint_types", unit,
                                        sentence_start, sentence_end, sentence, spans, marker_matches)
                        elif not subject_rows:
                            add_example(predicate, "missing_subject_type", unit,
                                        sentence_start, sentence_end, sentence, spans, marker_matches)
                        elif not object_rows:
                            add_example(predicate, "missing_object_type", unit,
                                        sentence_start, sentence_end, sentence, spans, marker_matches)

                    pairs = []
                    for subject_start, subject_end, subject in spans:
                        if subject["candidate_type"] not in subject_types:
                            continue
                        for object_start, object_end, obj in spans:
                            if obj["candidate_type"] not in object_types or object_start < subject_end:
                                continue
                            pairs.append((subject_end, object_start, subject, obj))
                    counts[predicate]["ordered_typed_pairs"] += len(pairs)
                    if marker_matches and not pairs:
                        counts[predicate]["marker_sentences_without_typed_pair"] += 1
                        if subject_rows and object_rows:
                            counts[predicate]["marker_sentences_with_both_types_but_no_ordered_pair"] += 1
                            add_example(predicate, "both_endpoint_types_but_no_ordered_pair",
                                        unit, sentence_start, sentence_end, sentence, spans, marker_matches)
                    if pairs and marker_matches:
                        between_any = any(
                            marker.search(sentence[subject_end - sentence_start:object_start - sentence_start])
                            for subject_end, object_start, _, _ in pairs
                        )
                        if not between_any:
                            counts[predicate]["marker_sentences_with_ordered_pair_but_no_predicate_between"] += 1
                            add_example(predicate, "ordered_pair_but_no_predicate_between",
                                        unit, sentence_start, sentence_end, sentence, spans, marker_matches)
                    if pairs and not marker_matches:
                        counts[predicate]["typed_pair_sentences_without_marker"] += 1

                    for subject_end, object_start, subject, obj in pairs:
                        between = sentence[subject_end - sentence_start:object_start - sentence_start]
                        match = marker.search(between)
                        if match is None:
                            continue
                        scope_break = RELATION_SCOPE_BREAKS.get(predicate)
                        if scope_break and scope_break.search(between):
                            counts[predicate]["scope_break_pairs"] += 1
                            continue
                        counts[predicate]["pairs_with_predicate_between"] += 1
                        if NEGATION_PREFIX.search(between[:match.start()]):
                            counts[predicate]["negated_pairs"] += 1
                            continue
                        counts[predicate]["eligible_pairs"] += 1
                        eligible_units[predicate].add(unit_id)
                        expected_id = relation_identity(
                            predicate, subject, obj, unit_id, sentence_start, sentence_end
                        )
                        if expected_id in expected_relation_ids:
                            raise ValueError(f"duplicate independently derived relation identity: {expected_id}")
                        expected_relation_ids[expected_id] = predicate

    observed_relation_ids: set[str] = set()
    with relations_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required_relation_fields = {"relation_id", "predicate"}
        missing_relation_fields = required_relation_fields - set(reader.fieldnames or [])
        if missing_relation_fields:
            raise ValueError("relation output missing fields: " + ", ".join(sorted(missing_relation_fields)))
        for row in reader:
            predicate = row["predicate"]
            relation_id = row["relation_id"]
            if predicate not in counts:
                raise ValueError(f"unsupported extracted predicate: {predicate}")
            if not relation_id or relation_id in observed_relation_ids:
                raise ValueError("relation output has a missing or duplicate relation_id")
            observed_relation_ids.add(relation_id)
            expected_predicate = expected_relation_ids.get(relation_id)
            if expected_predicate is None:
                raise ValueError(f"extracted relation is not an independently eligible pair: {relation_id}")
            if expected_predicate != predicate:
                raise ValueError(f"extracted relation predicate mismatch: {relation_id}")
            counts[predicate]["extracted_rows"] += 1

    missing_relation_ids = set(expected_relation_ids) - observed_relation_ids
    if missing_relation_ids:
        sample = sorted(missing_relation_ids)[:5]
        raise ValueError(
            "independently eligible relation identities missing from extractor output: "
            + ", ".join(sample)
        )

    for predicate in PREDICATES:
        counts[predicate]["units_with_marker"] = len(marker_units[predicate])
        counts[predicate]["units_with_eligible_pair"] = len(eligible_units[predicate])
        if counts[predicate]["eligible_pairs"] != counts[predicate]["extracted_rows"]:
            raise ValueError(
                f"{predicate}: eligible pair count does not match extracted rows "
                f"({counts[predicate]['eligible_pairs']} != {counts[predicate]['extracted_rows']})"
            )

    report = {
        "schema_version": 3,
        "source_units_scanned": sum(
            1 for _ in gzip.open(units_path, "rt", encoding="utf-8", newline="")
        ),
        "predicates": counts,
        "diagnostic_examples": {
            predicate: dict(by_diagnosis)
            for predicate, by_diagnosis in examples.items()
        },
        "interpretation": {
            "marker_occurrences": "supported lexical predicate occurrences in source sentences",
            "scope_break_pairs": "ordered typed pairs with a source-attribution boundary anywhere between endpoints and excluded from extraction",
            "eligible_pairs": "ordered typed candidate pairs with a non-negated predicate between endpoints and no source-attribution boundary",
            "extracted_rows": "rows emitted by the production extractor; must equal eligible_pairs",
            "endpoint_diagnostics": "For sentences containing a supported predicate marker, these counters show whether subject and object candidate types were present and ordered correctly; they do not relax extraction requirements.",
            "diagnostic_examples": "At most five source-grounded examples per diagnosis and predicate. Candidate spans are limited to twelve per example and sentence text to 600 characters; examples retain source identity and offsets.",
            "coverage_limit": "This audit measures only the current predicate lexicon and typed candidates; it does not estimate semantic relations expressed with unsupported wording.",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_units_scanned": report["source_units_scanned"],
        "predicates": {
            key: dict(value)
            for key, value in counts.items()
        },
        "diagnostic_example_counts": {
            predicate: {diagnosis: len(items) for diagnosis, items in groups.items()}
            for predicate, groups in examples.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-candidates", type=Path,
                        default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--mentions", type=Path,
                        default=Path("catalog/generated/entity_mention_candidates.csv.gz"))
    parser.add_argument("--units", type=Path,
                        default=Path("catalog/generated/knowledge_units.jsonl.gz"))
    parser.add_argument("--relations", type=Path,
                        default=Path("catalog/generated/contextual_relation_candidates.csv"))
    parser.add_argument("--output", type=Path,
                        default=Path("catalog/generated/contextual_relation_coverage.json"))
    args = parser.parse_args()
    print(json.dumps(audit(args.context_candidates, args.mentions, args.units,
                           args.relations, args.output), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
