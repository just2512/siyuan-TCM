#!/usr/bin/env python3
"""Run real-corpus end-to-end smoke queries for the TCM knowledge-path API."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from search_classical_knowledge_paths import search_classical_knowledge_paths


CASES = (
    ("SHANG_HAN_LUN symptom", "恶寒", "SHANG_HAN_LUN", "SYMPTOM"),
    ("SHANG_HAN_LUN formula", "桂枝汤", "SHANG_HAN_LUN", "FORMULA"),
    ("SHANG_HAN_LUN herb", "桂枝", "SHANG_HAN_LUN", "HERB"),
    ("HUANG_DI_NEI_JING theory", "腠理", "HUANG_DI_NEI_JING", "CLASSICAL_THEORY"),
    ("ZHEN_JIU_DA_CHENG symptom", "头痛", "ZHEN_JIU_DA_CHENG", "SYMPTOM"),
    ("ZHEN_JIU_DA_CHENG acupoint", "玉枕穴", "ZHEN_JIU_DA_CHENG", None),
    ("ZHEN_JIU_DA_CHENG technique", "放血", "ZHEN_JIU_DA_CHENG", "ACUPUNCTURE_TECHNIQUE"),
)


def smoke(database_path: Path) -> dict[str, Any]:
    """Check all major knowledge types against the freshly built full-corpus DB."""
    if not database_path.is_file():
        raise FileNotFoundError(database_path)

    cases: list[dict[str, Any]] = []
    for label, query, source_work, term_type in CASES:
        result = search_classical_knowledge_paths(
            database_path,
            query,
            limit=20,
            source_work=source_work,
            term_type=term_type,
        )
        if result["matched_occurrences"] == 0:
            raise AssertionError(
                f"real-corpus knowledge-path query returned no match: "
                f"{label} ({source_work}, {term_type}, {query})"
            )

        invalid_spans = [
            item["match"]["occurrence_id"]
            for item in result["matches"]
            if not item["match"]["source_span_matches_term"]
        ]
        if invalid_spans:
            raise AssertionError(
                f"query returned source-span mismatches for {label}: {invalid_spans[:5]}"
            )

        missing_locators = [
            item["match"]["occurrence_id"]
            for item in result["matches"]
            if not item["source"]["document"]
            or not item["source"]["source_sha256"]
            or not item["source"]["tree_position"]
            or not item["source"]["block_id"]
            or not item["source"]["passage_id"]
        ]
        if missing_locators:
            raise AssertionError(
                f"query returned incomplete source locators for {label}: {missing_locators[:5]}"
            )

        navigation_links = sum(
            len(item["navigational_links"]) for item in result["matches"]
        )
        cases.append({
            "label": label,
            "query": query,
            "source_work": source_work,
            "term_type": term_type,
            "matched_occurrences_returned": len(result["matches"]),
            "source_spans_exact": True,
            "source_locators_complete": True,
            "navigation_links_returned": navigation_links,
        })

    acupoint_case = next(item for item in cases if item["label"].endswith("acupoint"))
    if acupoint_case["navigation_links_returned"] == 0:
        raise AssertionError(
            "玉枕穴 query did not expand to a same-passage symptom/acupoint link"
        )

    return {
        "schema_version": 1,
        "database": str(database_path),
        "checks": cases,
        "relation_semantics": (
            "same-passage links are navigation-only; explicit relation candidates "
            "remain unresolved and are not clinical assertions"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=Path("catalog/generated/siyuan_search.sqlite3")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("catalog/generated/knowledge_path_query_smoke.json"),
    )
    args = parser.parse_args()
    result = smoke(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
