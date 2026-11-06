#!/usr/bin/env python3
"""Extract explicit formula-herb composition relation candidates with source evidence.

Only narrowly matched textual constructions are emitted. This is not a
confirmed pharmacological or medical relation; every row retains its sentence
and source span and remains UNRESOLVED_CANDIDATE.
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
    "relation_id", "unit_id", "subject_mention_id", "subject_text", "predicate",
    "object_mention_id", "object_text", "document", "source_sha256",
    "tree_position", "block_id", "sentence_start", "sentence_end",
    "evidence_text", "extraction_rule", "resolution_status",
]
SENTENCE_END = re.compile(r"[^。！？\n]+[。！？]?|\n+")


def read_mentions(path: Path) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            grouped[row["unit_id"]].append(row)
    return grouped


def sentence_ranges(text: str):
    for match in SENTENCE_END.finditer(text):
        if match.group(0).strip():
            yield match.start(), match.end()


def explicit_composition(formula: dict[str, str], herbs: list[dict[str, str]],
                         sentence: str, sentence_start: int) -> list[dict[str, str]]:
    """Return only herbs inside a tightly bounded, explicit ingredient phrase."""
    fs = int(formula["character_start"]) - sentence_start
    fe = int(formula["character_end"]) - sentence_start
    if fs < 0 or fe > len(sentence):
        return []

    ingredient_start = ingredient_end = None
    tail = sentence[fe:]
    forward = re.match(
        r"^\s*(?:中|的)?由(?P<ingredients>[^。！？；\n]{1,80}?)(?:组成|构成)",
        tail,
    )
    if forward is None:
        forward = re.match(
            r"^\s*(?:中|的)?(?:含有|包含|含)(?P<ingredients>[^。！？；\n]{1,80})",
            tail,
        )
    if forward is not None:
        ingredient_start = fe + forward.start("ingredients")
        ingredient_end = fe + forward.end("ingredients")
    else:
        reverse = re.search(
            r"(?P<ingredients>[^。！？；\n]{1,80}?)(?:组成|构成)(?:了)?\s*$",
            sentence[:fs],
        )
        if reverse is None:
            return []
        ingredient_start = reverse.start("ingredients")
        ingredient_end = reverse.end("ingredients")

    selected = []
    residual = sentence[ingredient_start:ingredient_end]
    replacements = []
    for herb in herbs:
        hs = int(herb["character_start"]) - sentence_start
        he = int(herb["character_end"]) - sentence_start
        if ingredient_start <= hs and he <= ingredient_end:
            selected.append(herb)
            replacements.append((hs - ingredient_start, he - ingredient_start))
    if not selected:
        return []
    for left, right in sorted(replacements, reverse=True):
        residual = residual[:left] + residual[right:]
    residual = re.sub(r"[\s、，,及和与并等]+", "", residual)
    return selected if not residual else []


def extract(mentions_path: Path, units_path: Path, output_path: Path) -> dict[str, int]:
    if not mentions_path.is_file() or not units_path.is_file():
        raise FileNotFoundError("entity mentions and knowledge units are both required")
    mentions = read_mentions(mentions_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    seen: set[str] = set()
    with gzip.open(units_path, "rt", encoding="utf-8", newline="") as source, output_path.open(
        "w", encoding="utf-8", newline=""
    ) as destination:
        writer = csv.DictWriter(destination, fieldnames=FIELDS)
        writer.writeheader()
        for raw in source:
            unit = json.loads(raw)
            unit_id = unit["unit_id"]
            text = unit["content"]["source_text"]
            source_info = unit["source"]
            unit_mentions = mentions.get(unit_id, [])
            formulas = [m for m in unit_mentions if m["entity_type"] == "FORMULA"]
            herbs = [m for m in unit_mentions if m["entity_type"] == "HERB"]
            for start, end in sentence_ranges(text):
                sentence = text[start:end]
                sentence_formulas = [m for m in formulas
                    if start <= int(m["character_start"]) and int(m["character_end"]) <= end]
                sentence_herbs = [m for m in herbs
                    if start <= int(m["character_start"]) and int(m["character_end"]) <= end]
                for formula in sentence_formulas:
                    for herb in explicit_composition(formula, sentence_herbs, sentence, start):
                        identity = "\0".join((
                            formula["mention_id"], "FORMULA_CONTAINS_HERB",
                            herb["mention_id"], str(start), str(end),
                        ))
                        relation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                        if relation_id in seen:
                            continue
                        seen.add(relation_id)
                        writer.writerow({
                            "relation_id": relation_id,
                            "unit_id": unit_id,
                            "subject_mention_id": formula["mention_id"],
                            "subject_text": formula["matched_text"],
                            "predicate": "FORMULA_CONTAINS_HERB",
                            "object_mention_id": herb["mention_id"],
                            "object_text": herb["matched_text"],
                            "document": source_info["document"],
                            "source_sha256": source_info["sha256"],
                            "tree_position": source_info["tree_position"],
                            "block_id": source_info.get("block_id", ""),
                            "sentence_start": start,
                            "sentence_end": end,
                            "evidence_text": sentence,
                            "extraction_rule": "FORMULA_COMPOSITION_EXPLICIT_V1",
                            "resolution_status": "UNRESOLVED_CANDIDATE",
                        })
                        count += 1
    return {"relation_candidates": count, "unique_relation_ids": len(seen)}


def validate(path: Path, units_path: Path, mentions_path: Path | None = None) -> int:
    units = {}
    mentions = {}
    if mentions_path is not None:
        with gzip.open(mentions_path, "rt", encoding="utf-8", newline="") as mention_stream:
            mentions = {row["mention_id"]: row for row in csv.DictReader(mention_stream)}
    with gzip.open(units_path, "rt", encoding="utf-8", newline="") as stream:
        for raw in stream:
            unit = json.loads(raw)
            units[unit["unit_id"]] = unit
    count = 0
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                raise ValueError(f"row {line}: invalid resolution status")
            if row["predicate"] != "FORMULA_CONTAINS_HERB":
                raise ValueError(f"row {line}: unsupported predicate")
            unit = units.get(row["unit_id"])
            if unit is None:
                raise ValueError(f"row {line}: source unit not found")
            source_info = unit["source"]
            if (source_info["document"] != row["document"]
                or source_info["sha256"] != row["source_sha256"]
                or source_info["tree_position"] != row["tree_position"]
                or source_info.get("block_id", "") != row["block_id"]):
                raise ValueError(f"row {line}: source provenance mismatch")
            if mentions_path is not None:
                subject = mentions.get(row["subject_mention_id"])
                obj = mentions.get(row["object_mention_id"])
                if subject is None or obj is None:
                    raise ValueError(f"row {line}: relation mention reference not found")
                if (subject["unit_id"] != row["unit_id"] or obj["unit_id"] != row["unit_id"]
                    or subject["entity_type"] != "FORMULA" or obj["entity_type"] != "HERB"
                    or subject["matched_text"] != row["subject_text"]
                    or obj["matched_text"] != row["object_text"]):
                    raise ValueError(f"row {line}: relation endpoints do not match entity mentions")
            text = unit["content"]["source_text"]
            start, end = int(row["sentence_start"]), int(row["sentence_end"])
            if start < 0 or end <= start or text[start:end] != row["evidence_text"]:
                raise ValueError(f"row {line}: evidence span mismatch")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mentions", type=Path,
                        default=Path("catalog/generated/entity_mention_candidates.csv.gz"))
    parser.add_argument("--units", type=Path,
                        default=Path("catalog/generated/knowledge_units.jsonl.gz"))
    parser.add_argument("--output", type=Path,
                        default=Path("catalog/generated/formula_herb_relation_candidates.csv"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        count = validate(args.output, args.units, args.mentions)
        print(json.dumps({"validated_relation_candidates": count}, ensure_ascii=False))
    else:
        result = extract(args.mentions, args.units, args.output)
        validate(args.output, args.units, args.mentions)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
