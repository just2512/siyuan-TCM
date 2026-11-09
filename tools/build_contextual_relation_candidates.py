#!/usr/bin/env python3
"""Extract explicit symptom/syndrome/treatment/formula relations from source spans.

All edges remain unresolved candidates and retain source-unit evidence. The
extractor never infers a relation from co-occurrence alone: a supported
predicate must occur between the subject and object spans in one sentence.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

FIELDS = [
    "relation_id", "predicate", "subject_candidate_id", "subject_text",
    "subject_type", "subject_start", "subject_end", "object_candidate_id", "object_text",
    "object_type", "object_start", "object_end",
    "unit_id", "document", "source_sha256", "tree_position", "block_id",
    "sentence_start", "sentence_end", "evidence_text", "predicate_text",
    "extraction_rule", "resolution_status",
]
SENTENCE_END = re.compile(r"[^。！？；．\n]+[。！？；．]?|；+|\n+")
PREDICATES = {
    "SYMPTOM_TO_SYNDROME": re.compile(r"(?:辨证为|辨证属|证属|诊断为|辨为)"),
    "SYNDROME_TO_TREATMENT": re.compile(r"(?:治宜|治法为|治以|当以)"),
    "TREATMENT_TO_FORMULA": re.compile(r"(?:方用|选用|用方|主方为|方选|可用)"),
}
SUBJECT_TYPES = {
    "SYMPTOM": {"SYMPTOM"},
    "SYNDROME": {"SYNDROME"},
    "TREATMENT": {"TREATMENT"},
}
OBJECT_TYPES = {
    "SYMPTOM_TO_SYNDROME": {"SYNDROME"},
    "SYNDROME_TO_TREATMENT": {"TREATMENT"},
    "TREATMENT_TO_FORMULA": {"FORMULA"},
}
NEGATION_PREFIX = re.compile(r"(?:不宜|不应|不可|不能|勿|忌|禁用|禁|未|非)\s*$")

# A later quoted recommendation must not attach to syndrome candidates
# appearing before a source-attribution boundary in the same long sentence.
RELATION_SCOPE_BREAKS = {
    predicate: re.compile(r"(?:[\u3400-\u9fff]{1,8}曰[：:∶])")
    for predicate in PREDICATES
}


def load_context_candidates(path: Path) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "candidate_id", "term", "candidate_type", "evidence_document",
            "source_sha256", "tree_position", "block_id", "unit_id",
            "character_start", "character_end", "classification_status",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("context candidate input missing fields: " + ", ".join(sorted(missing)))
        for row in reader:
            if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                raise ValueError("context candidate input contains unsafe status")
            if row["candidate_type"] in {"SYMPTOM", "SYNDROME", "TREATMENT"}:
                grouped[row["unit_id"]].append({
                    "candidate_id": row["candidate_id"], "term": row["term"],
                    "candidate_type": row["candidate_type"],
                    "character_start": row["character_start"],
                    "character_end": row["character_end"],
                    "document": row["evidence_document"],
                    "source_sha256": row["source_sha256"],
                    "tree_position": row["tree_position"],
                    "block_id": row["block_id"],
                })
    return grouped


def load_formula_mentions(path: Path) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["entity_type"] == "FORMULA":
                grouped[row["unit_id"]].append({
                    "candidate_id": row["mention_id"], "term": row["matched_text"],
                    "candidate_type": "FORMULA",
                    "character_start": row["character_start"],
                    "character_end": row["character_end"],
                    "document": row["document"], "source_sha256": row["source_sha256"],
                    "tree_position": row["tree_position"], "block_id": row["block_id"],
                })
    return grouped


def sentence_ranges(text: str):
    for match in SENTENCE_END.finditer(text):
        if match.group(0).strip():
            yield match.start(), match.end()


def canonicalize_spans(
    spans: list[tuple[int, int, dict[str, str]]],
) -> list[tuple[int, int, dict[str, str]]]:
    """Collapse nested n-grams while preserving distinct partially-overlapping spans.

    A contained span is an alternate window for the enclosing lexical
    endpoint. Partial overlaps with neither span containing the other may
    represent adjacent real terms and are retained. Non-overlapping repeated
    occurrences always retain their own offsets.
    """
    grouped: dict[str, list[tuple[int, int, dict[str, str]]]] = defaultdict(list)
    for item in spans:
        grouped[item[2]["candidate_type"]].append(item)

    retained: list[tuple[int, int, dict[str, str]]] = []
    for candidate_type, items in grouped.items():
        # Formula lexicon entries can be independently named formulas even
        # when one exact name is contained in a modified formula name. Keep
        # both unresolved endpoints; only lexical n-gram duplicates for other
        # endpoint classes are collapsed here.
        if candidate_type == "FORMULA":
            retained.extend(items)
            continue
        parents = list(range(len(items)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        for left_index, (left_start, left_end, _) in enumerate(items):
            for right_index in range(left_index + 1, len(items)):
                right_start, right_end, _ = items[right_index]
                left_contains_right = left_start <= right_start and right_end <= left_end
                right_contains_left = right_start <= left_start and left_end <= right_end
                if left_contains_right or right_contains_left:
                    union(left_index, right_index)

        components: dict[int, list[tuple[int, int, dict[str, str]]]] = defaultdict(list)
        for index, item in enumerate(items):
            components[find(index)].append(item)

        for component in components.values():
            retained.append(min(
                component,
                key=lambda item: (-(item[1] - item[0]), item[0], item[2]["candidate_id"]),
            ))

    return sorted(retained, key=lambda item: (item[0], item[1], item[2]["candidate_type"],
                                               item[2]["candidate_id"]))


def relation_identity(predicate: str, subject: dict[str, str],
                      obj: dict[str, str], unit_id: str, start: int, end: int) -> str:
    raw = "\0".join((
        predicate, subject["candidate_id"], str(subject["character_start"]),
        str(subject["character_end"]), obj["candidate_id"],
        str(obj["character_start"]), str(obj["character_end"]),
        unit_id, str(start), str(end),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract(context_path: Path, mentions_path: Path, units_path: Path,
            output_path: Path) -> dict[str, int]:
    for path in (context_path, mentions_path, units_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    candidates = load_context_candidates(context_path)
    formulas = load_formula_mentions(mentions_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    distinct_predicates: set[str] = set()
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=FIELDS)
        writer.writeheader()
        with gzip.open(units_path, "rt", encoding="utf-8", newline="") as source:
            for raw in source:
                unit = json.loads(raw)
                unit_id = unit["unit_id"]
                text = unit["content"]["source_text"]
                src = unit["source"]
                unit_candidates = candidates.pop(unit_id, [])
                unit_formulas = formulas.get(unit_id, [])
                for candidate in unit_candidates + unit_formulas:
                    left = int(candidate["character_start"])
                    right = int(candidate["character_end"])
                    if (candidate["document"] != src["document"]
                        or candidate["source_sha256"] != src["sha256"]
                        or candidate["tree_position"] != src["tree_position"]
                        or candidate["block_id"] != src.get("block_id", "")):
                        raise ValueError(f"candidate source provenance mismatch: {unit_id}")
                    if left < 0 or right <= left or right > len(text) or text[left:right] != candidate["term"]:
                        raise ValueError(f"candidate span mismatch: {unit_id}:{left}-{right}")
                if not unit_candidates and not unit_formulas:
                    continue
                for start, end in sentence_ranges(text):
                    sentence = text[start:end]
                    spans = []
                    for row in unit_candidates + unit_formulas:
                        left = int(row["character_start"])
                        right = int(row["character_end"])
                        if left < start or right > end or right <= left:
                            continue
                        if text[left:right] != row["term"]:
                            raise ValueError(f"candidate span mismatch: {unit_id}:{left}-{right}")
                        spans.append((left, right, row))
                    spans.sort(key=lambda item: (item[0], item[1], item[2]["candidate_id"]))
                    spans = canonicalize_spans(spans)
                    for predicate, marker in PREDICATES.items():
                        subject_types = SUBJECT_TYPES[predicate.split("_TO_")[0]]
                        object_types = OBJECT_TYPES[predicate]
                        for subject_start, subject_end, subject in spans:
                            if subject["candidate_type"] not in subject_types:
                                continue
                            for object_start, object_end, obj in spans:
                                if obj["candidate_type"] not in object_types or object_start < subject_end:
                                    continue
                                between = text[subject_end:object_start]
                                match = marker.search(between)
                                if match is None:
                                    continue
                                if NEGATION_PREFIX.search(between[:match.start()]):
                                    continue
                                scope_break = RELATION_SCOPE_BREAKS.get(predicate)
                                if scope_break and scope_break.search(between):
                                    continue
                                relation_id = relation_identity(predicate, subject, obj, unit_id, start, end)
                                writer.writerow({
                                    "relation_id": relation_id,
                                    "predicate": predicate,
                                    "subject_candidate_id": subject["candidate_id"],
                                    "subject_text": subject["term"],
                                    "subject_type": subject["candidate_type"],
                                    "subject_start": subject_start,
                                    "subject_end": subject_end,
                                    "object_candidate_id": obj["candidate_id"],
                                    "object_text": obj["term"],
                                    "object_type": obj["candidate_type"],
                                    "object_start": object_start,
                                    "object_end": object_end,
                                    "unit_id": unit_id,
                                    "document": src["document"],
                                    "source_sha256": src["sha256"],
                                    "tree_position": src["tree_position"],
                                    "block_id": src.get("block_id", ""),
                                    "sentence_start": start,
                                    "sentence_end": end,
                                    "evidence_text": sentence,
                                    "predicate_text": match.group(0),
                                    "extraction_rule": predicate + "_EXPLICIT_V1",
                                    "resolution_status": "UNRESOLVED_CANDIDATE",
                                })
                                count += 1
                                distinct_predicates.add(predicate)
    return {"contextual_relation_candidates": count,
            "predicate_types": len(distinct_predicates)}


def validate(
    path: Path,
    units_path: Path,
    context_candidates_path: Path | None = None,
    mentions_path: Path | None = None,
) -> int:
    units: dict[str, dict[str, Any]] = {}
    with gzip.open(units_path, "rt", encoding="utf-8", newline="") as stream:
        for raw in stream:
            unit = json.loads(raw)
            units[unit["unit_id"]] = unit

    candidate_index: set[tuple[str, str, str, str, int, int, str, str, str, str]] | None = None
    if (context_candidates_path is None) != (mentions_path is None):
        raise ValueError("both context candidates and formula mentions are required for endpoint validation")
    if context_candidates_path is not None and mentions_path is not None:
        # Context candidate IDs identify vocabulary terms, not individual
        # occurrences. Repeated occurrences in one unit may share an ID.
        # Validate the complete endpoint identity instead of requiring ID
        # uniqueness: ID, type, text, exact span, and source provenance.
        candidate_index = set()
        for grouped in (
            load_context_candidates(context_candidates_path),
            load_formula_mentions(mentions_path),
        ):
            for source_unit_id, rows in grouped.items():
                for candidate in rows:
                    candidate_index.add((
                        source_unit_id, candidate["candidate_id"],
                        candidate["candidate_type"], candidate["term"],
                        int(candidate["character_start"]), int(candidate["character_end"]),
                        candidate["document"], candidate["source_sha256"],
                        candidate["tree_position"], candidate["block_id"],
                    ))

    count = 0
    seen = set()
    sentence_boundaries: dict[str, set[tuple[int, int]]] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("relation output missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                raise ValueError(f"row {line}: unsafe relation status")
            predicate = row["predicate"]
            if predicate not in PREDICATES or row["extraction_rule"] != predicate + "_EXPLICIT_V1":
                raise ValueError(f"row {line}: unsupported relation predicate/rule")
            if row["subject_type"] not in SUBJECT_TYPES[predicate.split("_TO_")[0]]:
                raise ValueError(f"row {line}: invalid subject type")
            if row["object_type"] not in OBJECT_TYPES[predicate]:
                raise ValueError(f"row {line}: invalid object type")
            unit = units.get(row["unit_id"])
            if unit is None:
                raise ValueError(f"row {line}: source unit not found")
            src = unit["source"]
            if (src["document"] != row["document"] or src["sha256"] != row["source_sha256"]
                or src["tree_position"] != row["tree_position"]
                or src.get("block_id", "") != row["block_id"]):
                raise ValueError(f"row {line}: source provenance mismatch")
            text = unit["content"]["source_text"]
            start, end = int(row["sentence_start"]), int(row["sentence_end"])
            if start < 0 or end <= start or text[start:end] != row["evidence_text"]:
                raise ValueError(f"row {line}: evidence span mismatch")
            if row["unit_id"] not in sentence_boundaries:
                sentence_boundaries[row["unit_id"]] = set(sentence_ranges(text))
            if (start, end) not in sentence_boundaries[row["unit_id"]]:
                raise ValueError(f"row {line}: evidence span crosses a source sentence boundary")
            subject_start, subject_end = int(row["subject_start"]), int(row["subject_end"])
            object_start, object_end = int(row["object_start"]), int(row["object_end"])
            if not (start <= subject_start < subject_end <= object_start < object_end <= end):
                raise ValueError(f"row {line}: endpoint spans are outside sentence or overlap")
            if text[subject_start:subject_end] != row["subject_text"]:
                raise ValueError(f"row {line}: subject span does not match source")
            if text[object_start:object_end] != row["object_text"]:
                raise ValueError(f"row {line}: object span does not match source")
            between = text[subject_end:object_start]
            predicate_match = PREDICATES[predicate].search(between)
            if (predicate_match is None or predicate_match.group(0) != row["predicate_text"]
                or NEGATION_PREFIX.search(between[:predicate_match.start()])):
                raise ValueError(f"row {line}: predicate evidence missing, negated, or outside relation scope")
            scope_break = RELATION_SCOPE_BREAKS.get(predicate)
            if scope_break and scope_break.search(between):
                raise ValueError(f"row {line}: relation crosses a source-attribution boundary")
            if candidate_index is not None:
                for role, candidate_id, candidate_type, term, span_start, span_end in (
                    ("subject", row["subject_candidate_id"], row["subject_type"],
                     row["subject_text"], subject_start, subject_end),
                    ("object", row["object_candidate_id"], row["object_type"],
                     row["object_text"], object_start, object_end),
                ):
                    identity = (
                        row["unit_id"], candidate_id, candidate_type, term,
                        span_start, span_end, row["document"], row["source_sha256"],
                        row["tree_position"], row["block_id"],
                    )
                    if identity not in candidate_index:
                        raise ValueError(
                            f"row {line}: {role} candidate ID/span/type is absent from source candidate inputs"
                        )

            expected_relation_id = relation_identity(
                predicate,
                {"candidate_id": row["subject_candidate_id"],
                 "character_start": str(subject_start), "character_end": str(subject_end)},
                {"candidate_id": row["object_candidate_id"],
                 "character_start": str(object_start), "character_end": str(object_end)},
                row["unit_id"], start, end,
            )
            if row["relation_id"] != expected_relation_id:
                raise ValueError(f"row {line}: relation identity does not match endpoint spans")
            identity = (row["relation_id"], row["unit_id"])
            if identity in seen:
                raise ValueError(f"row {line}: duplicate relation")
            seen.add(identity)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-candidates", type=Path,
                        default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--mentions", type=Path,
                        default=Path("catalog/generated/entity_mention_candidates.csv.gz"))
    parser.add_argument("--units", type=Path,
                        default=Path("catalog/generated/knowledge_units.jsonl.gz"))
    parser.add_argument("--output", type=Path,
                        default=Path("catalog/generated/contextual_relation_candidates.csv"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        count = validate(args.output, args.units, args.context_candidates, args.mentions)
        result = {"validated_contextual_relations": count}
    else:
        result = extract(args.context_candidates, args.mentions, args.units, args.output)
        result["validated_contextual_relations"] = validate(
            args.output, args.units, args.context_candidates, args.mentions
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
