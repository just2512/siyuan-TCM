#!/usr/bin/env python3
"""Classify corpus-mined terms only when nearby source wording supplies explicit context.

The output is a multi-label candidate index. It never upgrades a term to a
confirmed medical concept and always carries the original sample provenance.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from pathlib import Path

RULES = {
    "SYMPTOM": [
        ("SYMPTOM_CONTEXT_01", r"(?:症见|症状|表现为|可见|见有|出现|伴有)"),
        ("SYMPTOM_CONTEXT_02", r"(?:疼痛|胀痛|刺痛|麻木|瘙痒|咳嗽|恶心|呕吐|发热|畏寒)"),
    ],
    "PULSE": [
        ("PULSE_CONTEXT_01", r"(?:脉象|脉诊|脉见|脉为|脉沉|脉浮|脉数|脉迟|脉弦|脉滑|脉细)"),
    ],
    "TONGUE": [
        ("TONGUE_CONTEXT_01", r"(?:舌象|舌质|舌苔|舌红|舌淡|舌绛|苔白|苔黄|苔腻)"),
    ],
    "SYNDROME": [
        ("SYNDROME_CONTEXT_01", r"(?:辨证|证属|属于.{0,4}证|证候|证型|此证|本证)"),
    ],
    "TREATMENT": [
        ("TREATMENT_CONTEXT_01", r"(?:治法|治宜|宜.{0,4}法|治以|法当|治疗原则|治疗方法)"),
    ],
    "FORMULA": [
        ("FORMULA_CONTEXT_01", r"(?:方用|用.{0,8}方|选用.{0,8}方|处方|方剂组成|组成[:：])"),
    ],
    "HERB": [
        ("HERB_CONTEXT_01", r"(?:药用|用药|药物组成|中药|本草|配伍)"),
    ],
}
FIELDS = [
    "candidate_id", "term", "candidate_type", "rule_id",
    "evidence_document", "source_sha256", "tree_position", "block_id",
    "unit_id", "character_start", "character_end", "evidence_start",
    "evidence_text", "classification_status",
]


def classify_sample(sample: dict[str, str]) -> list[tuple[str, str]]:
    text = sample.get("evidence_text", "")
    term = sample.get("matched_text", "")
    if not term:
        return []
    start = int(sample.get("character_start", 0)) - int(sample.get("evidence_start", 0))
    end = start + len(term)
    if start < 0 or end > len(text) or text[start:end] != term:
        raise ValueError("candidate term does not match its source evidence span")
    # Context must belong to the candidate phrase, not an adjacent clause.
    # Restrict the left context to the current punctuation-delimited clause.
    left_boundary = max(
        text.rfind(mark, 0, start) for mark in "，。！？；、\n"
    ) + 1
    before = text[max(left_boundary, start - 10):start]
    found = []
    for candidate_type, rules in RULES.items():
        for rule_id, pattern in rules:
            # Prefix cues (症见/辨证为/治宜/方用/舌/脉) must precede
            # the candidate. Intrinsic cues such as 疼痛/舌红/脉弦 may
            # be part of the candidate itself. Do not borrow cues after
            # the candidate: they may describe a neighboring concept.
            if re.search(pattern, before + term):
                found.append((candidate_type, rule_id))
    return found


def build(source_path: Path, output_path: Path) -> dict[str, int]:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    distinct_terms_classified = 0
    with (
        gzip.open(source_path, "rt", encoding="utf-8-sig", newline="") as source,
        gzip.open(output_path, "wt", encoding="utf-8", newline="") as target,
    ):
        reader = csv.DictReader(source)
        required = {"candidate_id", "term", "sample_evidence", "candidate_status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("term candidate input missing fields: " + ", ".join(sorted(missing)))
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        writer.writeheader()
        for candidate in reader:
            if candidate["candidate_status"] != "UNCLASSIFIED_TERM_CANDIDATE":
                raise ValueError("input contains a non-unclassified candidate")
            # Candidate rows are unique by candidate_id. Deduplicate only within
            # the current candidate: a corpus-wide set grows with every matching
            # term and is unnecessary because evidence samples are grouped here.
            candidate_classifications = set()
            candidate_rows = 0
            samples = json.loads(candidate["sample_evidence"])
            for sample in samples:
                for candidate_type, rule_id in classify_sample(sample):
                    key = (candidate_type, rule_id, sample.get("unit_id", ""))
                    if key in candidate_classifications:
                        continue
                    candidate_classifications.add(key)
                    writer.writerow({
                        "candidate_id": candidate["candidate_id"],
                        "term": candidate["term"],
                        "candidate_type": candidate_type,
                        "rule_id": rule_id,
                        "evidence_document": sample.get("document", ""),
                        "source_sha256": sample.get("source_sha256", ""),
                        "tree_position": sample.get("tree_position", ""),
                        "block_id": sample.get("block_id", ""),
                        "unit_id": sample.get("unit_id", ""),
                        "character_start": sample.get("character_start", ""),
                        "character_end": sample.get("character_end", ""),
                        "evidence_start": sample.get("evidence_start", ""),
                        "evidence_text": sample.get("evidence_text", ""),
                        "classification_status": "CONTEXT_RULE_CANDIDATE",
                    })
                    rows += 1
                    candidate_rows += 1
            if candidate_rows:
                distinct_terms_classified += 1
    return {"contextual_classification_candidates": rows,
            "distinct_terms_classified": distinct_terms_classified}


def validate(path: Path) -> int:
    count = 0
    seen = set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("context classification output missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                raise ValueError(f"row {line}: unsafe classification status")
            if row["candidate_type"] not in RULES or row["rule_id"] not in {
                rule_id for rules in RULES.values() for rule_id, _ in rules
            }:
                raise ValueError(f"row {line}: unknown rule/type")
            if not all(row[field] for field in ("candidate_id", "term", "unit_id", "evidence_document", "source_sha256")):
                raise ValueError(f"row {line}: missing source identity")
            start, end, evidence_start = (
                int(row["character_start"]), int(row["character_end"]), int(row["evidence_start"])
            )
            left, right = start - evidence_start, end - evidence_start
            if start < 0 or end <= start or left < 0 or row["evidence_text"][left:right] != row["term"]:
                raise ValueError(f"row {line}: term span does not match evidence")
            identity = (row["candidate_id"], row["candidate_type"], row["rule_id"], row["unit_id"])
            if identity in seen:
                raise ValueError(f"row {line}: duplicate classification evidence")
            seen.add(identity)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("catalog/generated/unclassified_term_candidates.csv.gz"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    result = {"validated_candidates": validate(args.output)} if args.validate else build(args.input, args.output)
    if not args.validate:
        result["validated_candidates"] = validate(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
