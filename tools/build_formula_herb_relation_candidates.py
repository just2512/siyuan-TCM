#!/usr/bin/env python3
"""Extract explicit formula-herb relation candidates with source evidence.

Supports direct composition wording and a narrowly bounded nearby-block
composition-list pattern. All relations remain unresolved candidates.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
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
SENTENCE_END = re.compile(r"[^。！？；．\n]+[。！？；．]?|；+|\n+")


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
    """Return herbs inside a tightly bounded, explicit ingredient phrase."""
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


def position_parts(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


AUTHOR_ATTRIBUTION_BOUNDARY = re.compile(r"(?:[\u3400-\u9fff]{1,8}(?:曰|云)[：:∶]|《[^》\n]{1,40}》(?:曰|云)[：:∶])")


def build_sibling_unit_index(
    units_by_id: dict[str, dict[str, Any]],
) -> dict[tuple[str, str, tuple[int, ...]], tuple[tuple[int, ...], tuple[dict[str, Any], ...]]]:
    """Index source sibling units once by document, revision, and parent position."""
    grouped: dict[tuple[str, str, tuple[int, ...]], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for unit in units_by_id.values():
        source = unit["source"]
        position = position_parts(source.get("tree_position", ""))
        if len(position) < 2:
            continue
        key = (source.get("document", ""), source.get("sha256", ""), position[:-1])
        grouped[key].append((position[-1], unit))
    indexed = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda item: item[0])
        indexed[key] = (
            tuple(position for position, _ in rows),
            tuple(unit for _, unit in rows),
        )
    return indexed


def crosses_author_attribution_boundary(
    formula: dict[str, str],
    herb: dict[str, str],
    units_by_id: dict[str, dict[str, Any]],
    sibling_index: dict[
        tuple[str, str, tuple[int, ...]],
        tuple[tuple[int, ...], tuple[dict[str, Any], ...]],
    ] | None = None,
) -> bool:
    """Reject overlapping endpoints or endpoint pairs separated by an author boundary."""
    formula_unit = units_by_id.get(formula.get("unit_id", ""))
    herb_unit = units_by_id.get(herb.get("unit_id", ""))
    if formula_unit is None or herb_unit is None:
        return True

    formula_source = formula_unit["source"]
    herb_source = herb_unit["source"]
    if (formula_source["document"] != herb_source["document"]
        or formula_source["sha256"] != herb_source["sha256"]):
        return True

    formula_text = formula_unit["content"]["source_text"]
    herb_text = herb_unit["content"]["source_text"]
    formula_start = int(formula["character_start"])
    formula_end = int(formula["character_end"])
    herb_start = int(herb["character_start"])
    herb_end = int(herb["character_end"])

    if formula_unit["unit_id"] == herb_unit["unit_id"]:
        if formula_start < herb_end and herb_start < formula_end:
            return True
        left, right = (
            (formula_end, herb_start)
            if formula_end <= herb_start
            else (herb_end, formula_start)
        )
        return bool(AUTHOR_ATTRIBUTION_BOUNDARY.search(formula_text[left:right]))

    formula_pos = position_parts(formula_unit["source"]["tree_position"])
    herb_pos = position_parts(herb_unit["source"]["tree_position"])
    if (len(formula_pos) < 2 or len(herb_pos) < 2
        or formula_pos[:-1] != herb_pos[:-1]
        or formula_pos == herb_pos):
        return True

    if sibling_index is None:
        sibling_index = build_sibling_unit_index(units_by_id)
    source = formula_unit["source"]
    key = (source["document"], source["sha256"], formula_pos[:-1])
    positions, indexed_units = sibling_index.get(key, ((), ()))
    lower, upper = sorted((formula_pos[-1], herb_pos[-1]))
    first = bisect_right(positions, lower)
    last = bisect_left(positions, upper)
    sibling_units = indexed_units[first:last]

    if formula_pos[-1] < herb_pos[-1]:
        segments = [formula_text[formula_end:]]
        segments.extend(item["content"]["source_text"] for item in sibling_units)
        segments.append(herb_text[:herb_start])
    else:
        segments = [herb_text[herb_end:]]
        segments.extend(item["content"]["source_text"] for item in sibling_units)
        segments.append(formula_text[:formula_start])
    return any(AUTHOR_ATTRIBUTION_BOUNDARY.search(segment) for segment in segments)


def has_explicit_formula_context(mention: dict[str, str]) -> bool:
    source_text = mention.get("_source_text", "")
    start, end = int(mention["character_start"]), int(mention["character_end"])
    # A lexicon hit at the suffix of a longer formula name is not an
    # independent formula anchor (e.g. “桂枝汤” inside “乌头桂枝汤”).
    # Permit common grammatical introducers, but reject an unseparated
    # Chinese modifier immediately before the candidate span.
    if start > 0 and re.fullmatch(r"[\u3400-\u9fff]", source_text[start - 1]):
        prefix = source_text[max(0, start - 8):start]
        if not re.search(
            r"(?:使用|采用|选用|选择|推荐|给予|处以|改用|再用|可用|当用|"
            r"应服|再服|服|用|加|予|与|给|宜|投|以|如|若|治|为|是|方)$",
            prefix,
        ):
            return False
    after = source_text[end:end + 16]
    if re.match(
        r"^\s*(?:(?:亦|也|可|亦可)?主之|主治|组成|方名|方剂|[:：])",
        after,
    ):
        return True
    if mention.get("_unit_type") == "SECTION_HEADING" and start <= 12:
        return True
    if start <= 12 and re.match(
        r"^\s*" + re.escape(mention["matched_text"]) + r"\s*(?:【|〔|（|\(|[:：]|主|组成)",
        source_text,
    ):
        return True
    return False


def nearby_formula(formula_mentions: list[dict[str, str]],
                   evidence_unit: dict[str, Any]) -> dict[str, str] | None:
    """Choose a unique nearby formula only when its own block names it explicitly."""
    evidence_source = evidence_unit["source"]
    evidence_pos = position_parts(evidence_source["tree_position"])
    if len(evidence_pos) < 2:
        return None
    candidates = []
    for mention in formula_mentions:
        if (mention.get("document") and mention["document"] != evidence_source.get("document")):
            continue
        if (mention.get("source_sha256") and evidence_source.get("sha256")
            and mention["source_sha256"] != evidence_source["sha256"]):
            continue
        if not has_explicit_formula_context(mention):
            continue
        if mention["unit_id"] == evidence_unit["unit_id"]:
            candidates.append((0, mention))
            continue
        other_pos = position_parts(mention["tree_position"])
        if len(other_pos) < 2 or other_pos[:-1] != evidence_pos[:-1]:
            continue
        distance = abs(other_pos[-1] - evidence_pos[-1])
        if 1 <= distance <= 5:
            candidates.append((distance, mention))
    if not candidates:
        return None
    min_distance = min(distance for distance, _ in candidates)
    nearest = [mention for distance, mention in candidates if distance == min_distance]
    # Ingredient-name overlap with a formula title is not evidence that the
    # composition list belongs to that formula. If multiple distinct formula
    # anchors are equally near, preserve the ambiguity instead of choosing one.
    terms = {mention["matched_text"] for mention in nearest}
    if len(terms) != 1:
        return None
    return sorted(nearest, key=lambda item: item["mention_id"])[0]


def make_relation(writer, seen: set[str], formula: dict[str, str],
                  herb: dict[str, str], evidence_unit: dict[str, Any],
                  start: int, end: int, evidence_text: str,
                  rule: str) -> bool:
    source = evidence_unit["source"]
    identity = "\0".join((
        formula["mention_id"], "FORMULA_CONTAINS_HERB",
        herb["mention_id"], evidence_unit["unit_id"], str(start), str(end), rule,
    ))
    relation_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    if relation_id in seen:
        return False
    seen.add(relation_id)
    writer.writerow({
        "relation_id": relation_id,
        "unit_id": evidence_unit["unit_id"],
        "subject_mention_id": formula["mention_id"],
        "subject_text": formula["matched_text"],
        "predicate": "FORMULA_CONTAINS_HERB",
        "object_mention_id": herb["mention_id"],
        "object_text": herb["matched_text"],
        "document": source["document"],
        "source_sha256": source["sha256"],
        "tree_position": source["tree_position"],
        "block_id": source.get("block_id", ""),
        "sentence_start": start,
        "sentence_end": end,
        "evidence_text": evidence_text,
        "extraction_rule": rule,
        "resolution_status": "UNRESOLVED_CANDIDATE",
    })
    return True


def extract(mentions_path: Path, units_path: Path, output_path: Path) -> dict[str, int]:
    if not mentions_path.is_file() or not units_path.is_file():
        raise FileNotFoundError("entity mentions and knowledge units are both required")
    mentions = read_mentions(mentions_path)
    units = []
    formulas_by_document: dict[str, list[dict[str, str]]] = defaultdict(list)
    with gzip.open(units_path, "rt", encoding="utf-8", newline="") as source:
        for raw in source:
            unit = json.loads(raw)
            units.append(unit)
            for mention in mentions.get(unit["unit_id"], []):
                if mention["entity_type"] == "FORMULA":
                    formula_record = dict(mention)
                    formula_record["_source_text"] = unit["content"]["source_text"]
                    formula_record["_unit_type"] = unit["unit_type"]
                    formulas_by_document[mention["document"]].append(formula_record)

    units_by_id = {unit["unit_id"]: unit for unit in units}
    sibling_index = build_sibling_unit_index(units_by_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    seen: set[str] = set()
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=FIELDS)
        writer.writeheader()
        for unit in units:
            unit_id = unit["unit_id"]
            text = unit["content"]["source_text"]
            source = unit["source"]
            unit_mentions = mentions.get(unit_id, [])
            formulas = [m for m in unit_mentions if m["entity_type"] == "FORMULA"]
            herbs = [m for m in unit_mentions if m["entity_type"] == "HERB"]

            # Direct formula-to-ingredient constructions within one source block.
            for start, end in sentence_ranges(text):
                sentence = text[start:end]
                sentence_formulas = [m for m in formulas
                    if start <= int(m["character_start"]) and int(m["character_end"]) <= end]
                sentence_herbs = [m for m in herbs
                    if start <= int(m["character_start"]) and int(m["character_end"]) <= end]
                for formula in sentence_formulas:
                    for herb in explicit_composition(formula, sentence_herbs, sentence, start):
                        if crosses_author_attribution_boundary(formula, herb, units_by_id, sibling_index):
                            continue
                        if make_relation(writer, seen, formula, herb, unit, start, end,
                                         sentence, "FORMULA_COMPOSITION_EXPLICIT_V1"):
                            count += 1

            # Many source notes store "组成：药物列表" separately from the
            # nearby formula title or indication block. Link only when the
            # composition header and formula mention share a document and
            # adjacent sibling position, with a unique nearest formula name.
            # Composition blocks may contain multiple sentences. Treat each
            # explicit composition sentence as its own evidence span; never
            # let unrelated later sentences expand the relation evidence.
            for start, end in sentence_ranges(text):
                sentence = text[start:end]
                if not re.match(r"^\s*(?:【?组成】?|方剂组成)\s*[:：]", sentence):
                    continue
                sentence_herbs = [
                    herb for herb in herbs
                    if start <= int(herb["character_start"])
                    and int(herb["character_end"]) <= end
                ]
                if not sentence_herbs:
                    continue
                formula = nearby_formula(
                    formulas_by_document.get(source["document"], []), unit
                )
                if formula is not None:
                    for herb in sentence_herbs:
                        if crosses_author_attribution_boundary(formula, herb, units_by_id, sibling_index):
                            continue
                        if make_relation(writer, seen, formula, herb, unit, start, end,
                                         sentence, "FORMULA_COMPOSITION_NEARBY_BLOCK_V1"):
                            count += 1

    return {"relation_candidates": count, "unique_relation_ids": len(seen)}


def validate(path: Path, units_path: Path, mentions_path: Path | None = None) -> int:
    units = {}
    mentions = {}
    if mentions_path is not None:
        with gzip.open(mentions_path, "rt", encoding="utf-8", newline="") as mention_stream:
            for mention_line, row in enumerate(csv.DictReader(mention_stream), 2):
                mention_id = row["mention_id"]
                if not mention_id:
                    raise ValueError(f"mention row {mention_line}: missing mention_id")
                if mention_id in mentions:
                    raise ValueError(f"mention row {mention_line}: duplicate mention_id {mention_id}")
                mentions[mention_id] = row
    with gzip.open(units_path, "rt", encoding="utf-8", newline="") as stream:
        for raw in stream:
            unit = json.loads(raw)
            units[unit["unit_id"]] = unit

    sibling_index = build_sibling_unit_index(units)
    count = 0
    seen_relations: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("relation output missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                raise ValueError(f"row {line}: invalid resolution status")
            if row["predicate"] != "FORMULA_CONTAINS_HERB":
                raise ValueError(f"row {line}: unsupported predicate")
            rule = row["extraction_rule"]
            if rule not in {"FORMULA_COMPOSITION_EXPLICIT_V1", "FORMULA_COMPOSITION_NEARBY_BLOCK_V1"}:
                raise ValueError(f"row {line}: unsupported formula-herb extraction rule")
            unit = units.get(row["unit_id"])
            if unit is None:
                raise ValueError(f"row {line}: source unit not found")
            source = unit["source"]
            if (source["document"] != row["document"]
                or source["sha256"] != row["source_sha256"]
                or source["tree_position"] != row["tree_position"]
                or source.get("block_id", "") != row["block_id"]):
                raise ValueError(f"row {line}: source provenance mismatch")

            text = unit["content"]["source_text"]
            start, end = int(row["sentence_start"]), int(row["sentence_end"])
            if start < 0 or end <= start or text[start:end] != row["evidence_text"]:
                raise ValueError(f"row {line}: evidence span mismatch")
            if rule == "FORMULA_COMPOSITION_EXPLICIT_V1":
                if (start, end) not in set(sentence_ranges(text)):
                    raise ValueError(f"row {line}: explicit evidence crosses a source sentence boundary")
            else:
                if ((start, end) not in set(sentence_ranges(text))
                    or not re.match(r"^\s*(?:【?组成】?|方剂组成)\s*[:：]", row["evidence_text"])):
                    raise ValueError(f"row {line}: nearby composition evidence is not one complete composition sentence")

            if mentions_path is not None:
                subject = mentions.get(row["subject_mention_id"])
                obj = mentions.get(row["object_mention_id"])
                if subject is None or obj is None:
                    raise ValueError(f"row {line}: relation mention reference not found")
                if (subject["entity_type"] != "FORMULA" or obj["entity_type"] != "HERB"
                    or subject["matched_text"] != row["subject_text"]
                    or obj["matched_text"] != row["object_text"]
                    or obj["unit_id"] != row["unit_id"]):
                    raise ValueError(f"row {line}: relation endpoints do not match source mentions")

                endpoint_records = {}
                for endpoint_name, endpoint in (("subject", subject), ("object", obj)):
                    endpoint_unit = units.get(endpoint["unit_id"])
                    if endpoint_unit is None:
                        raise ValueError(f"row {line}: {endpoint_name} source unit not found")
                    endpoint_source = endpoint_unit["source"]
                    if (endpoint_source["document"] != endpoint["document"]
                        or endpoint_source["sha256"] != endpoint["source_sha256"]
                        or endpoint_source["tree_position"] != endpoint["tree_position"]
                        or endpoint_source.get("block_id", "") != endpoint["block_id"]):
                        raise ValueError(f"row {line}: {endpoint_name} mention provenance mismatch")
                    endpoint_text = endpoint_unit["content"]["source_text"]
                    endpoint_start = int(endpoint["character_start"])
                    endpoint_end = int(endpoint["character_end"])
                    if (endpoint_start < 0 or endpoint_end <= endpoint_start
                        or endpoint_text[endpoint_start:endpoint_end] != endpoint["matched_text"]):
                        raise ValueError(f"row {line}: {endpoint_name} mention span mismatch")
                    endpoint_records[endpoint_name] = (endpoint_unit, endpoint_text, endpoint_start, endpoint_end)

                subject_unit, subject_source_text, subject_start, subject_end = endpoint_records["subject"]
                if (subject["document"] != row["document"]
                    or subject["source_sha256"] != row["source_sha256"]):
                    raise ValueError(f"row {line}: formula mention belongs to a different source document")
                if (obj["document"] != row["document"]
                    or obj["source_sha256"] != row["source_sha256"]
                    or obj["tree_position"] != row["tree_position"]
                    or obj["block_id"] != row["block_id"]):
                    raise ValueError(f"row {line}: object mention does not belong to evidence source")

                if rule == "FORMULA_COMPOSITION_EXPLICIT_V1":
                    if (subject["unit_id"] != row["unit_id"]
                        or not (start <= subject_start < subject_end <= end)):
                        raise ValueError(f"row {line}: explicit formula endpoint is outside evidence sentence")
                else:
                    subject_record = dict(subject)
                    subject_record["_source_text"] = subject_source_text
                    subject_record["_unit_type"] = subject_unit["unit_type"]
                    if not has_explicit_formula_context(subject_record):
                        raise ValueError(f"row {line}: nearby formula candidate lacks an explicit formula anchor")
                    if subject["unit_id"] != row["unit_id"]:
                        subject_pos = position_parts(subject["tree_position"])
                        evidence_pos = position_parts(row["tree_position"])
                        if (len(subject_pos) < 2 or len(evidence_pos) < 2
                            or subject_pos[:-1] != evidence_pos[:-1]
                            or not 1 <= abs(subject_pos[-1] - evidence_pos[-1]) <= 5):
                            raise ValueError(f"row {line}: nearby formula candidate is outside sibling proximity")
                if not (start <= int(obj["character_start"]) < int(obj["character_end"]) <= end):
                    raise ValueError(f"row {line}: herb endpoint is outside composition evidence")
                if crosses_author_attribution_boundary(subject, obj, units, sibling_index):
                    raise ValueError(f"row {line}: relation crosses an author-attribution boundary or has overlapping endpoints")

                expected_relation_id = hashlib.sha256("\0".join((
                    subject["mention_id"], row["predicate"], obj["mention_id"],
                    row["unit_id"], str(start), str(end), rule,
                )).encode("utf-8")).hexdigest()
                if row["relation_id"] != expected_relation_id:
                    raise ValueError(f"row {line}: relation ID does not match referenced source candidate IDs")
            if row["relation_id"] in seen_relations:
                raise ValueError(f"row {line}: duplicate relation ID")
            seen_relations.add(row["relation_id"])
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
