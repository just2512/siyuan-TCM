#!/usr/bin/env python3
"""Classify every corpus occurrence of mined terms using exact local context.

The mined-term file supplies the candidate vocabulary; classification is
performed against every occurrence in the source knowledge units, not only
the bounded sample snippets retained for vocabulary discovery.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None
from pathlib import Path

from build_unclassified_term_candidates import candidate_id

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
        ("SYNDROME_CONTEXT_01", r"(?:辨证为|辨证属|(?<!条)辨为|证属|属于|证候|证型|此证|本证)"),
    ],
    "TREATMENT": [
        ("TREATMENT_CONTEXT_01", r"(?:治法(?:为|是)|治法[：:]|治宜|宜.{0,4}法|治以|当以|治疗原则|治疗方法)"),
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
HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
NGRAM_PATTERNS = {
    length: re.compile(rf"(?=([\u3400-\u4dbf\u4e00-\u9fff]{{{length}}}))")
    for length in range(2, 7)
}
PUNCTUATION = "，。！？；、\n"


PREFIX_ONLY_TYPES = {"SYNDROME", "TREATMENT", "FORMULA", "HERB"}


def classify_span(text: str, start: int, end: int) -> list[tuple[str, str]]:
    if start < 0 or end <= start or end > len(text):
        raise ValueError("candidate span is outside source text")
    term = text[start:end]
    left_boundary = max(text.rfind(mark, 0, start) for mark in PUNCTUATION) + 1
    before = text[max(left_boundary, start - 10):start]
    found = []
    for candidate_type, rules in RULES.items():
        for rule_id, pattern in rules:
            # “可用” is an operational phrase, not a treatment entity;
            # do not let the generic “治法” prefix type this two-character span.
            if candidate_type == "TREATMENT" and term == "可用":
                continue
            # “辨为六名” is a classical naming/counting construction, not a
            # syndrome assertion. Keep the exception tied to the grammatical
            # object shape (a term ending in 名), not a global term blacklist.
            if (
                candidate_type == "SYNDROME"
                and term.endswith("名")
                and re.search(r"辨为[\s:：、]{0,2}$", before)
            ):
                continue
            # Prefix cues must precede the candidate. Intrinsic cues may be
            # part of the candidate itself; cues after it are never borrowed.
            if candidate_type in PREFIX_ONLY_TYPES:
                # A prefix cue must terminate immediately before the candidate
                # (allowing only a tiny punctuation/whitespace separator).
                matched = re.search(
                    rf"(?:{pattern})[\s:：、]{{0,2}}$",
                    before,
                )
            elif candidate_type == "SYMPTOM" and rule_id == "SYMPTOM_CONTEXT_01":
                # Symptom labels such as “症状” describe the following list;
                # they are not symptoms themselves. Allow a short list-intro
                # bridge (是/为/有 plus punctuation) before the first item.
                symptom_left = max(
                    text.rfind(mark, 0, start) for mark in "。！？；\n"
                ) + 1
                symptom_before = text[symptom_left:start]
                symptom_intro = re.compile(
                    r"(?:症见|症状(?:是|为|有)?|表现为|伴有|主诉)"
                    r"[\s:：，、]{0,4}"
                    r"(?:[\u3400-\u9fff]{1,12}[，、]\s*){0,8}$"
                )
                # A list cue cannot carry a symptom label across a new
                # narrative clause (diagnosis, attribution, treatment, etc.).
                non_symptom_clause = re.compile(
                    r"(?:西医|中医|医生|医师|患者|病人|认为|诊断|治疗|处方|药物|"
                    r"目前|经过|导致|造成|因此|所以|可见|说明|表示|相继|只是由)"
                )
                matched = (
                    None if non_symptom_clause.search(symptom_before)
                    or non_symptom_clause.search(term)
                    else symptom_intro.search(symptom_before)
                )
            elif (candidate_type == "SYMPTOM" and rule_id == "SYMPTOM_CONTEXT_02") or candidate_type in {"PULSE", "TONGUE"}:
                # Intrinsic clinical descriptors must occur inside the candidate
                # span itself. A cue in the preceding ten characters belongs to
                # the previous term and must not type this unrelated n-gram.
                matched = re.search(pattern, term)
            else:
                matched = re.search(pattern, before + term)
            if matched:
                found.append((candidate_type, rule_id))
    return found


def classify_sample(sample: dict[str, str]) -> list[tuple[str, str]]:
    text = sample.get("evidence_text", "")
    term = sample.get("matched_text", "")
    if not term:
        return []
    start = int(sample.get("character_start", 0)) - int(sample.get("evidence_start", 0))
    end = start + len(term)
    if start < 0 or end > len(text) or text[start:end] != term:
        raise ValueError("candidate term does not match its source evidence span")
    return classify_span(text, start, end)


def load_candidate_terms(source_path: Path) -> set[str]:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    terms: set[str] = set()
    with gzip.open(source_path, "rt", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"candidate_id", "term", "candidate_status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("term candidate input missing fields: " + ", ".join(sorted(missing)))
        for line, candidate in enumerate(reader, 2):
            term = candidate["term"]
            if candidate["candidate_status"] != "UNCLASSIFIED_TERM_CANDIDATE":
                raise ValueError(f"input row {line} contains a non-unclassified candidate")
            if not term or candidate["candidate_id"] != candidate_id(term):
                raise ValueError(f"input row {line} has an invalid candidate identity")
            if len(term) < 2 or len(term) > 6:
                raise ValueError(f"input row {line} has a term outside the mined n-gram range")
            if term in terms:
                raise ValueError(f"input row {line} contains a duplicate candidate term")
            terms.add(term)
    return terms


def build(source_path: Path, output_path: Path,
          units_path: Path = Path("catalog/generated/knowledge_units.jsonl.gz")) -> dict[str, int]:
    if not units_path.is_file():
        raise FileNotFoundError(units_path)
    candidate_terms = load_candidate_terms(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    classified_terms: set[str] = set()
    units_scanned = 0

    with (
        gzip.open(units_path, "rt", encoding="utf-8", newline="") as source,
        gzip.open(output_path, "wt", encoding="utf-8", newline="") as target,
    ):
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        writer.writeheader()
        for line_number, line in enumerate(source, 1):
            unit = json.loads(line)
            source_info = unit.get("source") or {}
            unit_id = str(unit.get("unit_id") or "")
            text = (unit.get("content") or {}).get("source_text", "")
            if not unit_id or not source_info.get("document") or not source_info.get("sha256"):
                raise ValueError(f"unit line {line_number}: missing source identity")
            if not isinstance(text, str) or not text:
                continue
            units_scanned += 1
            for run in HAN_RUN.finditer(text):
                run_text = run.group(0)
                for length, pattern in NGRAM_PATTERNS.items():
                    if len(run_text) < length:
                        continue
                    for match in pattern.finditer(run_text):
                        term = match.group(1)
                        if term not in candidate_terms:
                            continue
                        start = run.start() + match.start(1)
                        end = start + length
                        classifications = classify_span(text, start, end)
                        if not classifications:
                            continue
                        evidence_start = max(0, start - 12)
                        evidence_text = text[evidence_start:min(len(text), end + 12)]
                        cid = candidate_id(term)
                        for candidate_type, rule_id in classifications:
                            writer.writerow({
                                "candidate_id": cid,
                                "term": term,
                                "candidate_type": candidate_type,
                                "rule_id": rule_id,
                                "evidence_document": source_info["document"],
                                "source_sha256": source_info["sha256"],
                                "tree_position": str(source_info.get("tree_position", "")),
                                "block_id": str(source_info.get("block_id", "")),
                                "unit_id": unit_id,
                                "character_start": start,
                                "character_end": end,
                                "evidence_start": evidence_start,
                                "evidence_text": evidence_text,
                                "classification_status": "CONTEXT_RULE_CANDIDATE",
                            })
                            rows += 1
                            classified_terms.add(term)
            if units_scanned % 25000 == 0:
                print(
                    f"[context-classification] scanned_units={units_scanned} "
                    f"candidate_terms={len(candidate_terms)} typed_occurrences={rows}",
                    file=sys.stderr,
                    flush=True,
                )

    peak_rss_kib = None
    if resource is not None:
        peak_rss_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            peak_rss_kib //= 1024
    return {
        "source_units_scanned": units_scanned,
        "candidate_terms_loaded": len(candidate_terms),
        "contextual_classification_candidates": rows,
        "distinct_terms_classified": len(classified_terms),
        "peak_rss_kib": peak_rss_kib,
    }


RULE_IDS_BY_TYPE = {
    candidate_type: {rule_id for rule_id, _ in rules}
    for candidate_type, rules in RULES.items()
}


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
            if (row["candidate_type"] not in RULES
                or row["rule_id"] not in RULE_IDS_BY_TYPE[row["candidate_type"]]):
                raise ValueError(f"row {line}: rule does not belong to candidate type")
            if not all(row[field] for field in (
                "candidate_id", "term", "unit_id", "evidence_document", "source_sha256"
            )):
                raise ValueError(f"row {line}: missing source identity")
            if row["candidate_id"] != candidate_id(row["term"]):
                raise ValueError(f"row {line}: candidate identity does not match term")
            start, end, evidence_start = (
                int(row["character_start"]), int(row["character_end"]), int(row["evidence_start"])
            )
            left, right = start - evidence_start, end - evidence_start
            if (start < 0 or end <= start or evidence_start < 0 or left < 0
                or right > len(row["evidence_text"])
                or row["evidence_text"][left:right] != row["term"]):
                raise ValueError(f"row {line}: term span does not match evidence")
            identity = (
                row["candidate_id"], row["candidate_type"], row["rule_id"],
                row["unit_id"], start, end,
            )
            if identity in seen:
                raise ValueError(f"row {line}: duplicate classification evidence")
            seen.add(identity)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("catalog/generated/unclassified_term_candidates.csv.gz"))
    parser.add_argument("--units", type=Path, default=Path("catalog/generated/knowledge_units.jsonl.gz"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    result = {"validated_candidates": validate(args.output)} if args.validate else build(args.input, args.output, args.units)
    if not args.validate:
        result["validated_candidates"] = validate(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
