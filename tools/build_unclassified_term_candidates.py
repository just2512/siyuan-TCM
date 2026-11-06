#!/usr/bin/env python3
"""Mine corpus-driven Chinese term candidates from machine-readable knowledge units.

This is an unsupervised vocabulary-discovery stage, not medical interpretation.
Every candidate retains occurrence counts and a small set of exact source spans.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any

HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
STOP_TERMS = {
    "我们", "你们", "他们", "这个", "那个", "这些", "那些", "因为", "所以",
    "如果", "但是", "然后", "而且", "以及", "可以", "应该", "需要", "进行",
    "一个", "一种", "一些", "没有", "不是", "就是", "时候", "方面", "其中",
    "因此", "此外", "例如", "比如", "这里", "那里", "什么", "怎么", "如何",
    "已经", "还是", "或者", "并且", "同时", "通过", "根据", "对于", "关于",
}
FIELDS = [
    "candidate_id", "term", "ngram_length", "occurrence_count",
    "unit_count", "document_count", "sample_evidence", "candidate_status",
]


NGRAM_PATTERNS = {
    length: re.compile(rf"(?=([\u3400-\u4dbf\u4e00-\u9fff]{{{length}}}))")
    for length in range(2, 7)
}


def count_ngrams(text: str, min_length: int = 2, max_length: int = 6) -> Counter[str]:
    """Count overlapping Han n-grams using regex scanning and a per-unit Counter."""
    counts: Counter[str] = Counter()
    for match in HAN_RUN.finditer(text):
        run = match.group(0)
        for length in range(min_length, min(max_length, len(run)) + 1):
            counts.update(NGRAM_PATTERNS[length].findall(run))
    return counts


def candidate_id(term: str) -> str:
    return "term_" + hashlib.sha256(term.encode("utf-8")).hexdigest()[:24]


def mine(units_path: Path, output_path: Path, min_occurrences: int = 3,
         min_documents: int = 2, min_length: int = 2, max_length: int = 6,
         sample_limit: int = 5, lexicon_path: Path | None = None) -> dict[str, int]:
    if not units_path.is_file():
        raise FileNotFoundError(units_path)
    if min_occurrences < 1 or min_documents < 1:
        raise ValueError("minimum counts must be positive")
    known_terms: set[str] = set()
    if lexicon_path is not None:
        if not lexicon_path.is_file():
            raise FileNotFoundError(lexicon_path)
        with lexicon_path.open("r", encoding="utf-8-sig", newline="") as lexicon_stream:
            known_terms = {row["term"].strip() for row in csv.DictReader(lexicon_stream) if row.get("term", "").strip()}
    stats: dict[str, dict[str, Any]] = {}
    unit_total = 0
    known_term_occurrences = 0
    with gzip.open(units_path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            unit = json.loads(line)
            source = unit.get("source") or {}
            content = unit.get("content") or {}
            text = content.get("source_text", "")
            if not isinstance(text, str) or not text:
                continue
            unit_id = str(unit.get("unit_id") or "")
            document = str(source.get("document") or "")
            if not unit_id or not document:
                raise ValueError(f"line {line_number}: missing unit/source identity")
            unit_total += 1
            for term, occurrences in count_ngrams(text, min_length, max_length).items():
                if term in STOP_TERMS:
                    continue
                if term in known_terms:
                    known_term_occurrences += occurrences
                    continue
                item = stats.get(term)
                if item is None:
                    item = {"occurrences": 0, "units": 0, "documents": set(), "samples": []}
                    stats[term] = item
                item["occurrences"] += occurrences
                item["units"] += 1
                if document not in item["documents"]:
                    item["documents"].add(document)
                    if len(item["samples"]) < sample_limit:
                        start = text.find(term)
                        end = start + len(term)
                        evidence_start = max(0, start - 12)
                        item["samples"].append({
                            "unit_id": unit_id,
                            "document": document,
                            "source_sha256": str(source.get("sha256") or ""),
                            "tree_position": str(source.get("tree_position") or ""),
                            "block_id": str(source.get("block_id") or ""),
                            "character_start": start,
                            "character_end": end,
                            "evidence_start": evidence_start,
                            "matched_text": term,
                            "evidence_text": text[evidence_start:min(len(text), end + 12)],
                        })

    eligible = [
        (term, item) for term, item in stats.items()
        if item["occurrences"] >= min_occurrences
        and len(item["documents"]) >= min_documents
    ]
    eligible.sort(key=lambda pair: (-len(pair[1]["documents"]), -pair[1]["occurrences"], pair[0]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for term, item in eligible:
            writer.writerow({
                "candidate_id": candidate_id(term),
                "term": term,
                "ngram_length": len(term),
                "occurrence_count": item["occurrences"],
                "unit_count": item["units"],
                "document_count": len(item["documents"]),
                "sample_evidence": json.dumps(item["samples"], ensure_ascii=False, sort_keys=True),
                "candidate_status": "UNCLASSIFIED_TERM_CANDIDATE",
            })
    return {
        "knowledge_units_scanned": unit_total,
        "distinct_ngrams_seen": len(stats),
        "known_lexicon_occurrences_skipped": known_term_occurrences,
        "unclassified_term_candidates": len(eligible),
        "minimum_occurrences": min_occurrences,
        "minimum_documents": min_documents,
    }


def validate(path: Path) -> int:
    seen: set[str] = set()
    count = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("term candidate index missing fields: " + ", ".join(sorted(missing)))
        for line_number, row in enumerate(reader, 2):
            if row["candidate_status"] != "UNCLASSIFIED_TERM_CANDIDATE":
                raise ValueError(f"line {line_number}: invalid candidate status")
            if row["candidate_id"] != candidate_id(row["term"]):
                raise ValueError(f"line {line_number}: unstable candidate ID")
            if row["candidate_id"] in seen:
                raise ValueError(f"line {line_number}: duplicate candidate ID")
            if int(row["occurrence_count"]) < 1 or int(row["document_count"]) < 1:
                raise ValueError(f"line {line_number}: invalid occurrence/document count")
            samples = json.loads(row["sample_evidence"])
            if not samples:
                raise ValueError(f"line {line_number}: missing source evidence")
            for sample in samples:
                if int(sample["character_end"]) - int(sample["character_start"]) != len(row["term"]):
                    raise ValueError(f"line {line_number}: evidence span length mismatch")
                if sample.get("matched_text") != row["term"]:
                    raise ValueError(f"line {line_number}: evidence text does not match candidate")
                evidence_start = int(sample.get("evidence_start", -1))
                relative_start = int(sample["character_start"]) - evidence_start
                relative_end = int(sample["character_end"]) - evidence_start
                if evidence_start < 0 or sample["evidence_text"][relative_start:relative_end] != row["term"]:
                    raise ValueError(f"line {line_number}: candidate does not match evidence snippet")
            seen.add(row["candidate_id"])
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units", type=Path, default=Path("catalog/generated/knowledge_units.jsonl.gz"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/unclassified_term_candidates.csv.gz"))
    parser.add_argument("--min-occurrences", type=int, default=3)
    parser.add_argument("--min-documents", type=int, default=2)
    parser.add_argument("--min-length", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=6)
    parser.add_argument("--lexicon", type=Path, default=Path("catalog/entity-lexicon.csv"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        result = {"validated_candidates": validate(args.output)}
    else:
        result = mine(args.units, args.output, args.min_occurrences, args.min_documents,
                      args.min_length, args.max_length, lexicon_path=args.lexicon)
        result["validated_candidates"] = validate(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
