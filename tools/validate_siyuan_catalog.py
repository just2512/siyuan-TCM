#!/usr/bin/env python3
"""Validate cross-file invariants of the generated SiYuan catalogue."""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

PARSE_STATES = {"PARSED", "RAW_FALLBACK"}
TITLE_SOURCES = {"PROPERTY", "BODY_FIRST_LINE", "FILENAME", "RAW_FILENAME"}
ASSET_STATES = {
    "FOUND", "FOUND_BY_UNIQUE_BASENAME", "AMBIGUOUS",
    "MISSING", "INVALID_REFERENCE", "NOT_CHECKED",
}
TOPIC_STATES = {
    "经典与理论", "伤寒与温病", "方剂与用药", "中药与本草",
    "针灸与经穴", "诊断与辨证", "医家与课程", "其他与待归类",
}


def read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"缺少生成文件：{path.name}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or [])
        missing = required - fields
        if missing:
            raise ValueError(f"{path.name} 缺少字段：{', '.join(sorted(missing))}")
        return list(reader)


def unique_index(rows: list[dict[str, str]], key: str, label: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for line, row in enumerate(rows, start=2):
        value = (row.get(key) or "").strip()
        if not value:
            raise ValueError(f"{label} 第 {line} 行缺少 {key}")
        if value in result:
            raise ValueError(f"{label} 存在重复 {key}：{value}")
        result[value] = row
    return result


def validate_catalogue(generated: Path, source_candidates: Path,
                       asset_candidates: Path) -> dict[str, int]:
    documents = read_csv(generated / "documents.csv", {
        "path", "title", "title_source", "topics", "parse_status",
        "asset_ref_count", "search_text",
    })
    docs = unique_index(documents, "path", "documents.csv")
    for path, row in docs.items():
        if row["parse_status"] not in PARSE_STATES:
            raise ValueError(f"{path} 的 parse_status 无效：{row['parse_status']}")
        if row["title_source"] not in TITLE_SOURCES:
            raise ValueError(f"{path} 的 title_source 无效：{row['title_source']}")
        topics = [item for item in row["topics"].split(";") if item]
        if not topics or any(topic not in TOPIC_STATES for topic in topics):
            raise ValueError(f"{path} 的 topics 为空或包含未知主题")
        try:
            if int(row["asset_ref_count"]) < 0:
                raise ValueError(f"{path} 的 asset_ref_count 不能为负数")
        except ValueError as exc:
            raise ValueError(f"{path} 的 asset_ref_count 无效") from exc

    asset_rows = read_csv(generated / "asset_references.csv", {
        "document", "reference", "local_status", "local_path", "match_method",
    })
    asset_counts = Counter()
    for row in asset_rows:
        if row["document"] not in docs:
            raise ValueError(f"asset_references.csv 引用了未知文档：{row['document']}")
        if row["local_status"] not in ASSET_STATES:
            raise ValueError(f"附件状态无效：{row['local_status']}")
        if row["local_status"] in {"FOUND", "FOUND_BY_UNIQUE_BASENAME"} and not row["local_path"]:
            raise ValueError("已找到的附件缺少 local_path")
        if row["local_status"] in {"MISSING", "AMBIGUOUS", "INVALID_REFERENCE", "NOT_CHECKED"} and row["local_path"]:
            raise ValueError("未确认匹配的附件不应输出 local_path")
        if row["local_status"] == "NOT_CHECKED" and row["match_method"] != "NOT_CHECKED":
            raise ValueError("NOT_CHECKED 附件的 match_method 不一致")
        if row["local_status"] == "FOUND" and row["match_method"] != "EXACT_RELATIVE_PATH":
            raise ValueError("FOUND 必须对应精确相对路径")
        if row["local_status"] == "FOUND_BY_UNIQUE_BASENAME" and row["match_method"] != "UNIQUE_BASENAME_FALLBACK":
            raise ValueError("唯一 basename 命中方式不一致")
        asset_counts[row["document"]] += 1
    for path, row in docs.items():
        if asset_counts[path] != int(row["asset_ref_count"]):
            raise ValueError(f"{path} 的附件引用计数与 asset_references.csv 不一致")

    review_rows = read_csv(generated / "document_review.csv", {
        "document", "title", "topics", "parse_status", "title_review_status",
        "source_status", "source_version_status", "collation_status",
    })
    review = unique_index(review_rows, "document", "document_review.csv")
    if set(review) != set(docs):
        raise ValueError("document_review.csv 与 documents.csv 文档集合不一致")
    for path, row in review.items():
        source = docs[path]
        for field in ("title", "topics", "parse_status"):
            if row[field] != source[field]:
                raise ValueError(f"{path} 的 document_review.{field} 与 documents.csv 不一致")
        if row["source_status"] not in {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"}:
            raise ValueError(f"{path} 的 source_status 无效")
        if row["source_version_status"] not in {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"}:
            raise ValueError(f"{path} 的 source_version_status 无效")
        if row["collation_status"] not in {"NOT_REVIEWED", "COLLATION_CONFIRMED", "CORRECTION_REQUIRED", "UNRESOLVED"}:
            raise ValueError(f"{path} 的 collation_status 无效")

    empty_rows = read_csv(generated / "empty_body_review.csv", {"document", "review_status"})
    empty = unique_index(empty_rows, "document", "empty_body_review.csv")
    expected_empty = {path for path, row in docs.items() if not row["search_text"].strip()}
    if set(empty) != expected_empty:
        raise ValueError("empty_body_review.csv 与 documents.csv 的空正文集合不一致")

    title_rows = read_csv(generated / "title_review_candidates.csv", {"document", "review_status"})
    title = unique_index(title_rows, "document", "title_review_candidates.csv")
    if not set(title).issubset(docs):
        raise ValueError("title_review_candidates.csv 引用了未知文档")

    topic_rows = read_csv(generated / "topic_review.csv", {
        "document", "catalog_topics", "catalog_topic_count", "review_bucket",
    })
    topic = unique_index(topic_rows, "document", "topic_review.csv")
    for path, row in topic.items():
        if path not in docs:
            raise ValueError(f"topic_review.csv 引用了未知文档：{path}")
        expected = [item for item in docs[path]["topics"].split(";") if item]
        if row["catalog_topics"] != docs[path]["topics"] or int(row["catalog_topic_count"]) != len(expected):
            raise ValueError(f"{path} 的主题复核证据与 documents.csv 不一致")
        if len(expected) <= 1:
            raise ValueError(f"{path} 不应进入多主题复核队列")

    batches = read_csv(generated / "topic_review_batches.csv", {"document", "batch_id", "batch_position"})
    if {row["document"] for row in batches} != set(topic):
        raise ValueError("topic_review_batches.csv 与 topic_review.csv 文档集合不一致")
    batch_positions: dict[str, list[int]] = {}
    for row in batches:
        batch_positions.setdefault(row["batch_id"], []).append(int(row["batch_position"]))
    if any(sorted(values) != list(range(1, len(values) + 1)) for values in batch_positions.values()):
        raise ValueError("topic_review_batches.csv 批内序号不连续")

    asset_queue = read_csv(generated / "asset_review_queue.csv", {
        "reference", "candidate_status", "candidate_count", "manual_status",
    })
    asset_queue_index = unique_index(asset_queue, "reference", "asset_review_queue.csv")
    persisted_assets = read_csv(asset_candidates, {"reference", "candidate_status", "candidate_count"})
    persisted_asset_index = unique_index(persisted_assets, "reference", "asset candidate source")
    if set(asset_queue_index) != set(persisted_asset_index):
        raise ValueError("asset_review_queue.csv 与持久化本地扫描候选引用集合不一致")
    for reference, row in asset_queue_index.items():
        source = persisted_asset_index[reference]
        if row["candidate_status"] != source["candidate_status"] or row["candidate_count"] != source["candidate_count"]:
            raise ValueError(f"{reference} 的附件候选队列与原始候选表不一致")
        if row["manual_status"] not in {"NEEDS_INSPECTION", "CONFIRMED_MATCH", "NOT_MATCH", "UNRESOLVED"}:
            raise ValueError(f"{reference} 的附件人工状态无效")

    source_queue = read_csv(generated / "source_review_queue.csv", {
        "path", "candidate_category", "verification_status", "evidence_reference",
    })
    source_queue_index = unique_index(source_queue, "path", "source_review_queue.csv")
    persisted_sources = read_csv(source_candidates, {
        "path", "candidate_category", "verification_status", "evidence_reference",
    })
    persisted_source_index = unique_index(persisted_sources, "path", "source candidate source")
    if set(source_queue_index) != set(persisted_source_index):
        raise ValueError("source_review_queue.csv 与来源候选输入集合不一致")
    for path, row in source_queue_index.items():
        source = persisted_source_index[path]
        if row["candidate_category"] != source["candidate_category"] or row["verification_status"] != source["verification_status"] or row["evidence_reference"] != source["evidence_reference"]:
            raise ValueError(f"{path} 的来源核验队列与原始候选表不一致")

    return {
        "documents": len(docs),
        "asset_references": len(asset_rows),
        "document_review": len(review),
        "empty_body_review": len(empty),
        "title_review_candidates": len(title),
        "topic_review": len(topic),
        "asset_review_queue": len(asset_queue_index),
        "source_review_queue": len(source_queue_index),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, required=True)
    parser.add_argument("--source-candidates", type=Path, required=True)
    parser.add_argument("--asset-candidates", type=Path, required=True)
    args = parser.parse_args()
    print(validate_catalogue(args.generated, args.source_candidates, args.asset_candidates))


if __name__ == "__main__":
    main()
