#!/usr/bin/env python3
"""Audit explicit contextual-relation predicate coverage without weakening extraction."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

from build_contextual_relation_candidates import (
    NEGATION_PREFIX,
    OBJECT_TYPES,
    PREDICATES,
    SUBJECT_TYPES,
    load_context_candidates,
    load_formula_mentions,
    sentence_ranges,
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
            "eligible_pairs": 0,
            "marker_sentences_without_typed_pair": 0,
            "typed_pair_sentences_without_marker": 0,
            "units_with_marker": 0,
            "units_with_eligible_pair": 0,
            "extracted_rows": 0,
        }
        for predicate in PREDICATES
    }
    marker_units = {key: set() for key in PREDICATES}
    eligible_units = {key: set() for key in PREDICATES}

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
                for predicate, marker in PREDICATES.items():
                    marker_matches = list(marker.finditer(sentence))
                    if marker_matches:
                        counts[predicate]["marker_occurrences"] += len(marker_matches)
                        counts[predicate]["sentences_with_marker"] += 1
                        marker_units[predicate].add(unit_id)

                    subject_types = SUBJECT_TYPES[predicate.split("_TO_")[0]]
                    object_types = OBJECT_TYPES[predicate]
                    pairs = []
                    for subject_start, subject_end, subject in spans:
                        if subject["candidate_type"] not in subject_types:
                            continue
                        for object_start, object_end, obj in spans:
                            if obj["candidate_type"] not in object_types or object_start < subject_end:
                                continue
                            pairs.append((subject_end, object_start))
                    counts[predicate]["ordered_typed_pairs"] += len(pairs)
                    if marker_matches and not pairs:
                        counts[predicate]["marker_sentences_without_typed_pair"] += 1
                    if pairs and not marker_matches:
                        counts[predicate]["typed_pair_sentences_without_marker"] += 1

                    for subject_end, object_start in pairs:
                        between = sentence[subject_end - sentence_start:object_start - sentence_start]
                        match = marker.search(between)
                        if match is None:
                            continue
                        counts[predicate]["pairs_with_predicate_between"] += 1
                        if NEGATION_PREFIX.search(between[:match.start()]):
                            counts[predicate]["negated_pairs"] += 1
                            continue
                        counts[predicate]["eligible_pairs"] += 1
                        eligible_units[predicate].add(unit_id)

    with relations_path.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            predicate = row["predicate"]
            if predicate not in counts:
                raise ValueError(f"unsupported extracted predicate: {predicate}")
            counts[predicate]["extracted_rows"] += 1

    for predicate in PREDICATES:
        counts[predicate]["units_with_marker"] = len(marker_units[predicate])
        counts[predicate]["units_with_eligible_pair"] = len(eligible_units[predicate])
        if counts[predicate]["eligible_pairs"] != counts[predicate]["extracted_rows"]:
            raise ValueError(
                f"{predicate}: eligible pair count does not match extracted rows "
                f"({counts[predicate]['eligible_pairs']} != {counts[predicate]['extracted_rows']})"
            )

    report = {
        "schema_version": 1,
        "source_units_scanned": sum(
            1 for _ in gzip.open(units_path, "rt", encoding="utf-8", newline="")
        ),
        "predicates": counts,
        "interpretation": {
            "marker_occurrences": "supported lexical predicate occurrences in source sentences",
            "eligible_pairs": "ordered typed candidate pairs with a non-negated predicate between endpoints",
            "extracted_rows": "rows emitted by the production extractor; must equal eligible_pairs",
            "coverage_limit": "This audit measures only the current predicate lexicon and typed candidates; it does not estimate semantic relations expressed with unsupported wording.",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_units_scanned": report["source_units_scanned"],
        "predicates": {
            key: {
                "marker_occurrences": value["marker_occurrences"],
                "ordered_typed_pairs": value["ordered_typed_pairs"],
                "eligible_pairs": value["eligible_pairs"],
                "extracted_rows": value["extracted_rows"],
            }
            for key, value in counts.items()
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
