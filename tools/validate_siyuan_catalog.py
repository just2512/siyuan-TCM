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
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError(f"{path.name} 存在重复列名")
        fields = set(headers)
        missing = required - fields
        if missing:
            raise ValueError(f"{path.name} 缺少字段：{', '.join(sorted(missing))}")
        rows = list(reader)
        for line, row in enumerate(rows, start=2):
            if None in row:
                raise ValueError(f"{path.name} 第 {line} 行列数超过表头")
        return rows


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
        "asset_ref_count", "parent_document", "document_depth",
        "child_document_count", "search_text",
    })
    docs = unique_index(documents, "path", "documents.csv")
    hierarchy_rows = read_csv(generated / "document_hierarchy.csv", {
        "document", "parent_document", "document_depth", "child_document_count",
        "structure_role",
    })
    hierarchy = unique_index(hierarchy_rows, "document", "document_hierarchy.csv")
    if set(hierarchy) != set(docs):
        raise ValueError("document_hierarchy.csv 与 documents.csv 文档集合不一致")
    expected_children: Counter[str] = Counter()
    for path, row in docs.items():
        parent = row.get("parent_document", "")
        if parent:
            if parent not in docs:
                raise ValueError(f"{path} 的父文档不存在：{parent}")
            expected_children[parent] += 1
    for path, row in hierarchy.items():
        source = docs[path]
        parent = source.get("parent_document", "")
        if row["parent_document"] != parent:
            raise ValueError(f"{path} 的层级父文档与 documents.csv 不一致")
        try:
            depth = int(source["document_depth"])
            child_count = int(source["child_document_count"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{path} 的文档层级数值字段无效") from exc
        if depth < 0 or child_count < 0:
            raise ValueError(f"{path} 的文档层级数值不能为负数")
        expected_depth = 0 if not parent else int(docs[parent]["document_depth"]) + 1
        if depth != expected_depth:
            raise ValueError(f"{path} 的文档层级深度与父文档关系不一致")
        if int(row["document_depth"]) != depth or int(row["child_document_count"]) != child_count:
            raise ValueError(f"{path} 的层级索引与 documents.csv 不一致")
        if child_count != expected_children[path]:
            raise ValueError(f"{path} 的直接子文档数与父子关系不一致")
        expected_role = "CONTAINER" if child_count else "LEAF"
        if row["structure_role"] != expected_role:
            raise ValueError(f"{path} 的结构角色与子文档数不一致")
    for path, row in docs.items():
        if row["parse_status"] not in PARSE_STATES:
            raise ValueError(f"{path} 的 parse_status 无效：{row['parse_status']}")
        if row["title_source"] not in TITLE_SOURCES:
            raise ValueError(f"{path} 的 title_source 无效：{row['title_source']}")
        topics = [item for item in row["topics"].split(";") if item]
        if not topics or any(topic not in TOPIC_STATES for topic in topics):
            raise ValueError(f"{path} 的 topics 为空或包含未知主题")
        evidence_fields = {"topic_matched_terms", "title_topic_matched_terms", "body_topic_matched_terms"}
        if evidence_fields.issubset(row):
            if row["topic_matched_terms"] != ";".join(
                item for item in (row["title_topic_matched_terms"], row["body_topic_matched_terms"]) if item
            ):
                raise ValueError(f"{path} 的主题命中词汇总与标题/正文证据不一致")
            evidence_topics = {
                item.split(":", 1)[0]
                for field in ("title_topic_matched_terms", "body_topic_matched_terms")
                for item in row[field].split(";") if item
            }
            expected_topics = sorted(evidence_topics) if evidence_topics else ["其他与待归类"]
            if sorted(topics) != expected_topics:
                raise ValueError(f"{path} 的 topics 与标题/正文命中证据不一致")
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
        "topic_review_status", "source_status", "source_version_status",
        "collation_status", "evidence_reference", "parent_document",
        "document_depth", "child_document_count",
    })
    review = unique_index(review_rows, "document", "document_review.csv")
    if set(review) != set(docs):
        raise ValueError("document_review.csv 与 documents.csv 文档集合不一致")
    for path, row in review.items():
        source = docs[path]
        for field in ("title", "topics", "parse_status", "parent_document", "document_depth", "child_document_count"):
            if row[field] != source[field]:
                raise ValueError(f"{path} 的 document_review.{field} 与 documents.csv 不一致")
        allowed_statuses = {
            "title_review_status": {"NOT_REVIEWED", "CONFIRMED", "RENAME_REQUIRED", "UNRESOLVED"},
            "topic_review_status": {"NOT_REVIEWED", "CONFIRMED", "REMOVE_TOPIC", "ADD_TOPIC", "SPLIT_REQUIRED", "UNRESOLVED"},
            "source_status": {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"},
            "source_version_status": {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"},
            "collation_status": {"NOT_REVIEWED", "COLLATION_CONFIRMED", "CORRECTION_REQUIRED", "UNRESOLVED"},
        }
        for field, allowed in allowed_statuses.items():
            if row[field] not in allowed:
                raise ValueError(f"{path} 的 {field} 无效：{row[field]}")
        conclusion_values = {
            "CONFIRMED", "RENAME_REQUIRED", "REMOVE_TOPIC", "ADD_TOPIC",
            "SPLIT_REQUIRED", "VERIFIED", "CONFLICT", "UNRESOLVED",
            "COLLATION_CONFIRMED", "CORRECTION_REQUIRED",
        }
        if any(row[field] in conclusion_values for field in allowed_statuses) and not row["evidence_reference"].strip():
            raise ValueError(f"{path} 已有人工核验结论但缺少 evidence_reference")

    empty_rows = read_csv(generated / "empty_body_review.csv", {
        "document", "review_status", "parent_document", "document_depth",
        "child_document_count",
    })
    empty = unique_index(empty_rows, "document", "empty_body_review.csv")
    expected_empty = {path for path, row in docs.items() if not row["search_text"].strip()}
    if set(empty) != expected_empty:
        raise ValueError("empty_body_review.csv 与 documents.csv 的空正文集合不一致")
    empty_statuses = {
        "NEEDS_SOURCE_INSPECTION", "SOURCE_EMPTY_CONFIRMED",
        "LOCAL_SOURCE_HAS_CONTENT", "RESTORE_REQUIRED", "UNRESOLVED",
    }
    for path, row in empty.items():
        if row["review_status"] not in empty_statuses:
            raise ValueError(f"{path} 的 empty_body review_status 无效：{row['review_status']}")
        for field in ("parent_document", "document_depth", "child_document_count"):
            if row[field] != docs[path][field]:
                raise ValueError(f"{path} 的 empty_body_review.{field} 与 documents.csv 不一致")

    title_rows = read_csv(generated / "title_review_candidates.csv", {"document", "review_status"})
    title = unique_index(title_rows, "document", "title_review_candidates.csv")
    if not set(title).issubset(docs):
        raise ValueError("title_review_candidates.csv 引用了未知文档")
    for path, row in title.items():
        if row["review_status"] not in {"NOT_REVIEWED", "CONFIRMED", "RENAME_REQUIRED", "UNRESOLVED"}:
            raise ValueError(f"{path} 的标题复核状态无效")
        if row["review_status"] != review[path]["title_review_status"]:
            raise ValueError(f"{path} 的标题复核队列状态与逐篇核验状态不一致")

    topic_rows = read_csv(generated / "topic_review.csv", {
        "document", "catalog_topics", "catalog_topic_count", "review_bucket", "review_status",
        "catalog_matched_terms", "catalog_title_matched_terms", "catalog_body_matched_terms",
    })
    topic = unique_index(topic_rows, "document", "topic_review.csv")
    for path, row in topic.items():
        if path not in docs:
            raise ValueError(f"topic_review.csv 引用了未知文档：{path}")
        if row.get("review_status") not in {"NOT_REVIEWED", "CONFIRMED", "REMOVE_TOPIC", "ADD_TOPIC", "SPLIT_REQUIRED", "UNRESOLVED"}:
            raise ValueError(f"{path} 的主题复核状态无效")
        if row["review_status"] != review[path]["topic_review_status"]:
            raise ValueError(f"{path} 的主题复核队列状态与逐篇核验状态不一致")
        expected = [item for item in docs[path]["topics"].split(";") if item]
        if row["catalog_topics"] != docs[path]["topics"] or int(row["catalog_topic_count"]) != len(expected):
            raise ValueError(f"{path} 的主题复核证据与 documents.csv 不一致")
        for review_field, document_field in (
            ("catalog_matched_terms", "topic_matched_terms"),
            ("catalog_title_matched_terms", "title_topic_matched_terms"),
            ("catalog_body_matched_terms", "body_topic_matched_terms"),
        ):
            if row[review_field] != docs[path][document_field]:
                raise ValueError(f"{path} 的 topic_review.{review_field} 与 documents.csv 不一致")
        if len(expected) <= 1:
            raise ValueError(f"{path} 不应进入多主题复核队列")

    batches = read_csv(generated / "topic_review_batches.csv", {"document", "batch_id", "batch_position", "batch_size"})
    batch_doc_index = unique_index(batches, "document", "topic_review_batches.csv")
    if set(batch_doc_index) != set(topic):
        raise ValueError("topic_review_batches.csv 与 topic_review.csv 文档集合不一致")
    batch_positions: dict[str, list[int]] = {}
    for row in batches:
        if not row["batch_id"]:
            raise ValueError("topic_review_batches.csv 缺少 batch_id")
        try:
            position = int(row["batch_position"])
            size = int(row.get("batch_size", ""))
        except ValueError as exc:
            raise ValueError("topic_review_batches.csv 的批次序号或批次大小不是整数") from exc
        if position < 1 or size < 1 or position > size:
            raise ValueError("topic_review_batches.csv 的批次序号或批次大小越界")
        batch_positions.setdefault(row["batch_id"], []).append(position)
    if any(sorted(values) != list(range(1, len(values) + 1)) for values in batch_positions.values()):
        raise ValueError("topic_review_batches.csv 批内序号不连续")
    for batch_id, positions in batch_positions.items():
        batch_size_values = {int(row["batch_size"]) for row in batches if row["batch_id"] == batch_id}
        if len(batch_size_values) != 1 or next(iter(batch_size_values)) != len(positions):
            raise ValueError(f"{batch_id} 的 batch_size 与实际批次记录数不一致")

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
        try:
            candidate_count = int(row["candidate_count"])
        except ValueError as exc:
            raise ValueError(f"{reference} 的附件候选数不是整数") from exc
        if candidate_count < 0:
            raise ValueError(f"{reference} 的附件候选数不能为负数")
        expected_status = "NO_CANDIDATE" if candidate_count == 0 else "ONE_CANDIDATE" if candidate_count == 1 else "MULTIPLE_CANDIDATES"
        if row["candidate_status"] != expected_status:
            raise ValueError(f"{reference} 的附件候选状态与候选数不一致")

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
        if row["verification_status"] not in {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"}:
            raise ValueError(f"{path} 的来源核验状态无效")
        if row["verification_status"] != "UNVERIFIED" and not row["evidence_reference"].strip():
            raise ValueError(f"{path} 已有来源核验结论但缺少 evidence_reference")

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
