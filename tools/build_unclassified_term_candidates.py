#!/usr/bin/env python3
"""Mine corpus-driven Chinese term candidates from machine-readable knowledge units.

This is an unsupervised vocabulary-discovery stage, not medical interpretation.
Every candidate retains occurrence counts and a small set of exact source spans.
Aggregation is disk-backed so a large corpus cannot exhaust runner memory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
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
COMMIT_EVERY_UNITS = 500
PROGRESS_EVERY_UNITS = 25000


def count_ngrams(text: str, min_length: int = 2, max_length: int = 6) -> Counter[str]:
    """Count overlapping Han n-grams using regex scanning and a per-unit Counter."""
    counts: Counter[str] = Counter()
    for match in HAN_RUN.finditer(text):
        run = match.group(0)
        for length in range(min_length, min(max_length, len(run)) + 1):
            pattern = NGRAM_PATTERNS.get(length)
            if pattern is None:
                pattern = re.compile(rf"(?=([\u3400-\u4dbf\u4e00-\u9fff]{{{length}}}))")
                NGRAM_PATTERNS[length] = pattern
            counts.update(pattern.findall(run))
    return counts


def candidate_id(term: str) -> str:
    return "term_" + hashlib.sha256(term.encode("utf-8")).hexdigest()[:24]


def _sample_evidence(unit: dict[str, Any], document: str, text: str,
                     term: str, unit_id: str, line_number: int) -> str:
    start = text.find(term)
    if start < 0:
        raise ValueError(f"line {line_number}: mined term not found in source text")
    end = start + len(term)
    evidence_start = max(0, start - 12)
    source = unit.get("source") or {}
    sample = {
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
    }
    return json.dumps(sample, ensure_ascii=False, sort_keys=True)


def mine(units_path: Path, output_path: Path, min_occurrences: int = 3,
         min_documents: int = 2, min_length: int = 2, max_length: int = 6,
         sample_limit: int = 5, lexicon_path: Path | None = None) -> dict[str, int]:
    if not units_path.is_file():
        raise FileNotFoundError(units_path)
    if min_occurrences < 1 or min_documents < 1:
        raise ValueError("minimum counts must be positive")
    if min_length < 1 or max_length < min_length:
        raise ValueError("invalid n-gram length range")
    if sample_limit < 1:
        raise ValueError("sample_limit must be positive")

    known_terms: set[str] = set()
    if lexicon_path is not None:
        if not lexicon_path.is_file():
            raise FileNotFoundError(lexicon_path)
        with lexicon_path.open("r", encoding="utf-8-sig", newline="") as lexicon_stream:
            known_terms = {
                row["term"].strip()
                for row in csv.DictReader(lexicon_stream)
                if row.get("term", "").strip()
            }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    unit_total = 0
    known_term_occurrences = 0
    distinct_ngrams_seen = 0
    eligible_count = 0

    with tempfile.TemporaryDirectory(
        prefix="tcm-term-mining-", dir=output_path.parent
    ) as temp_dir:
        database_path = Path(temp_dir) / "term-stats.sqlite3"
        connection = sqlite3.connect(database_path)
        try:
            # Keep corpus-wide term/document aggregation on disk. The only
            # in-memory Counter is for the current knowledge unit.
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA cache_size=-32768")
            connection.executescript("""
                CREATE TABLE term_stats (
                    term_id INTEGER PRIMARY KEY,
                    term TEXT NOT NULL UNIQUE,
                    occurrence_count INTEGER NOT NULL,
                    unit_count INTEGER NOT NULL,
                    document_count INTEGER NOT NULL DEFAULT 0,
                    sample_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE documents (
                    document_id INTEGER PRIMARY KEY,
                    document TEXT NOT NULL UNIQUE
                );
                CREATE TABLE term_documents (
                    term_id INTEGER NOT NULL,
                    document_id INTEGER NOT NULL,
                    PRIMARY KEY (term_id, document_id)
                ) WITHOUT ROWID;
                CREATE TABLE term_samples (
                    term_id INTEGER NOT NULL,
                    sample_index INTEGER NOT NULL,
                    sample_evidence TEXT NOT NULL,
                    PRIMARY KEY (term_id, sample_index)
                ) WITHOUT ROWID;
                CREATE TEMP TABLE unit_ngrams (
                    term TEXT PRIMARY KEY,
                    occurrence_count INTEGER NOT NULL
                ) WITHOUT ROWID;
                CREATE TEMP TABLE new_document_terms (
                    term_id INTEGER PRIMARY KEY,
                    term TEXT NOT NULL,
                    sample_index INTEGER,
                    sample_evidence TEXT
                ) WITHOUT ROWID;
            """)
            document_ids: dict[str, int] = {}
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

                    filtered_terms = []
                    for term, occurrences in count_ngrams(text, min_length, max_length).items():
                        if term in STOP_TERMS:
                            continue
                        if term in known_terms:
                            known_term_occurrences += occurrences
                            continue
                        filtered_terms.append((term, occurrences))

                    if filtered_terms:
                        document_id = document_ids.get(document)
                        if document_id is None:
                            connection.execute(
                                "INSERT INTO documents(document) VALUES (?) ON CONFLICT(document) DO NOTHING",
                                (document,),
                            )
                            document_id = connection.execute(
                                "SELECT document_id FROM documents WHERE document = ?", (document,)
                            ).fetchone()[0]
                            document_ids[document] = document_id
                        connection.execute("DELETE FROM unit_ngrams")
                        connection.execute("DELETE FROM new_document_terms")
                        connection.executemany(
                            "INSERT INTO unit_ngrams(term, occurrence_count) VALUES (?, ?)",
                            filtered_terms,
                        )
                        connection.execute("""
                            INSERT INTO term_stats (term, occurrence_count, unit_count)
                            SELECT term, occurrence_count, 1 FROM unit_ngrams WHERE 1
                            ON CONFLICT(term) DO UPDATE SET
                                occurrence_count = occurrence_count + excluded.occurrence_count,
                                unit_count = unit_count + 1
                        """)

                        # Deduplicate by the true (term, document) key. This is
                        # independent of input ordering and handles multiple
                        # blocks from the same document without inflating counts.
                        new_terms = connection.execute("""
                            SELECT stats.term_id, unit.term, stats.sample_count
                            FROM unit_ngrams AS unit
                            JOIN term_stats AS stats ON stats.term = unit.term
                            LEFT JOIN term_documents AS seen
                              ON seen.term_id = stats.term_id AND seen.document_id = ?
                            WHERE seen.term_id IS NULL
                        """, (document_id,)).fetchall()

                        if new_terms:
                            staged_rows = []
                            for term_id, term, sample_count in new_terms:
                                if sample_count < sample_limit:
                                    sample = _sample_evidence(
                                        unit, document, text, term, unit_id, line_number
                                    )
                                    staged_rows.append((term_id, term, sample_count, sample))
                                else:
                                    staged_rows.append((term_id, term, None, None))

                            connection.executemany("""
                                INSERT INTO new_document_terms(
                                    term_id, term, sample_index, sample_evidence
                                ) VALUES (?, ?, ?, ?)
                            """, staged_rows)
                            connection.execute("""
                                INSERT INTO term_documents(term_id, document_id)
                                SELECT term_id, ? FROM new_document_terms
                            """, (document_id,))
                            connection.execute("""
                                INSERT INTO term_samples(term_id, sample_index, sample_evidence)
                                SELECT term_id, sample_index, sample_evidence
                                FROM new_document_terms
                                WHERE sample_evidence IS NOT NULL
                            """)
                            connection.execute("""
                                UPDATE term_stats
                                SET document_count = document_count + 1,
                                    sample_count = sample_count
                                        + CASE WHEN sample_count < ? THEN 1 ELSE 0 END
                                WHERE term_id IN (SELECT term_id FROM new_document_terms)
                            """, (sample_limit,))

                    if unit_total % COMMIT_EVERY_UNITS == 0:
                        connection.commit()
                    if unit_total % PROGRESS_EVERY_UNITS == 0:
                        distinct_so_far = connection.execute(
                            "SELECT COUNT(*) FROM term_stats"
                        ).fetchone()[0]
                        database_bytes = database_path.stat().st_size if database_path.exists() else 0
                        print(
                            f"[term-mining] scanned_units={unit_total} "
                            f"distinct_terms={distinct_so_far} database_bytes={database_bytes}",
                            file=sys.stderr,
                            flush=True,
                        )

            connection.commit()
            distinct_ngrams_seen = connection.execute(
                "SELECT COUNT(*) FROM term_stats"
            ).fetchone()[0]
            eligible_count = connection.execute("""
                SELECT COUNT(*)
                FROM term_stats
                WHERE occurrence_count >= ? AND document_count >= ?
            """, (min_occurrences, min_documents)).fetchone()[0]

            with gzip.open(output_path, "wt", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                candidates = connection.execute("""
                    SELECT term_id, term, occurrence_count, unit_count, document_count
                    FROM term_stats
                    WHERE occurrence_count >= ? AND document_count >= ?
                    ORDER BY document_count DESC, occurrence_count DESC, term ASC
                """, (min_occurrences, min_documents))
                for term_id, term, occurrences, units, documents in candidates:
                    samples = [
                        json.loads(row[0])
                        for row in connection.execute("""
                            SELECT sample_evidence
                            FROM term_samples
                            WHERE term_id = ?
                            ORDER BY sample_index
                        """, (term_id,))
                    ]
                    writer.writerow({
                        "candidate_id": candidate_id(term),
                        "term": term,
                        "ngram_length": len(term),
                        "occurrence_count": occurrences,
                        "unit_count": units,
                        "document_count": documents,
                        "sample_evidence": json.dumps(
                            samples, ensure_ascii=False, sort_keys=True
                        ),
                        "candidate_status": "UNCLASSIFIED_TERM_CANDIDATE",
                    })
        finally:
            connection.close()

    return {
        "knowledge_units_scanned": unit_total,
        "distinct_ngrams_seen": distinct_ngrams_seen,
        "known_lexicon_occurrences_skipped": known_term_occurrences,
        "unclassified_term_candidates": eligible_count,
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
        result = mine(
            args.units, args.output, args.min_occurrences, args.min_documents,
            args.min_length, args.max_length, lexicon_path=args.lexicon
        )
        result["validated_candidates"] = validate(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
