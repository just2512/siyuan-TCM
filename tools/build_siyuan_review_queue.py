#!/usr/bin/env python3
"""Create human-review queues from the generated SiYuan document index.

This tool does not validate medical claims or infer bibliographic facts. It
marks missing source/version/collation evidence as unverified and exposes
multi-topic keyword matches for manual review.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import re
from collections import Counter
from pathlib import Path
from typing import Any

GENERIC_TITLE_CANDIDATES = {
    "其他", "方剂", "药势", "总义", "穴", "法门", "收纳", "未命名", "待收录",
}

MODULE_PATH = Path(__file__).with_name("build_siyuan_catalog.py")
SPEC = importlib.util.spec_from_file_location("build_siyuan_catalog", MODULE_PATH)
catalog = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(catalog)


def matched_terms_by_source(title: str, text: str) -> dict[str, dict[str, list[str]]]:
    title_text = title.lower()
    body_text = text.lower()
    evidence = {}
    for topic, terms in catalog.TOPICS.items():
        title_hits = [term for term in terms if term.lower() in title_text]
        body_hits = [term for term in terms if term.lower() in body_text]
        if title_hits or body_hits:
            evidence[topic] = {"title": title_hits, "body_excerpt": body_hits}
    return evidence

def matched_terms(title: str, text: str) -> dict[str, list[str]]:
    """Compatibility helper returning combined title/body-excerpt matches."""
    return {
        topic: evidence["title"] + evidence["body_excerpt"]
        for topic, evidence in matched_terms_by_source(title, text).items()
    }

def review_bucket(topic_count: int) -> str:
    if topic_count <= 1:
        return "0_TO_1_TOPICS"
    if topic_count >= 5:
        return "5_PLUS_TOPICS"
    if topic_count >= 3:
        return "3_TO_4_TOPICS"
    return "2_TOPICS"

def title_candidate_reason(title: str, title_source: str) -> str:
    """Flag risky navigational fallbacks without rewriting the extracted title."""
    if title_source != "PROPERTY":
        normalized = " ".join(title.split())
        if title_source == "BODY_FIRST_LINE":
            if re.fullmatch(r"\d+[、.．)]?", normalized):
                return "NUMBER_ONLY_BODY_FALLBACK"
            if len(normalized) > 60 or re.search(r"[。！？；;]", normalized):
                return "BODY_SENTENCE_USED_AS_TITLE"
        return "FALLBACK_TITLE_SOURCE"
    if title.lower() in GENERIC_TITLE_CANDIDATES:
        return "POSSIBLE_SECTION_OR_PLACEHOLDER_TITLE"
    if not title:
        return "EMPTY_TITLE"
    return ""


def read_documents(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


DECISION_FIELDS = {
    "title_review_status": {"NOT_REVIEWED", "CONFIRMED", "RENAME_REQUIRED", "UNRESOLVED"},
    "source_status": {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"},
    "source_version_status": {"UNVERIFIED", "VERIFIED", "CONFLICT", "UNRESOLVED"},
    "collation_status": {"NOT_REVIEWED", "COLLATION_CONFIRMED", "CORRECTION_REQUIRED", "UNRESOLVED"},
    "topic_review_status": {"NOT_REVIEWED", "CONFIRMED", "REMOVE_TOPIC", "ADD_TOPIC", "SPLIT_REQUIRED", "UNRESOLVED"},
    "empty_body_status": {"NEEDS_SOURCE_INSPECTION", "SOURCE_EMPTY_CONFIRMED", "LOCAL_SOURCE_HAS_CONTENT", "RESTORE_REQUIRED", "UNRESOLVED"},
}
DECISION_COLUMNS = [
    "document", "reviewer", "title_review_status", "human_corrected_title",
    "source_status", "source_version_status", "collation_status",
    "topic_review_status", "human_approved_topics", "empty_body_status",
    "review_notes", "evidence_reference",
]


def load_decisions(path: Path, known_documents: set[str]) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(DECISION_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"人工核验覆盖表缺少字段：{', '.join(sorted(missing))}")
        decisions = {}
        for line_number, row in enumerate(reader, start=2):
            document = (row.get("document") or "").strip()
            if not document:
                raise ValueError(f"人工核验覆盖表第 {line_number} 行缺少 document")
            if document not in known_documents:
                raise ValueError(f"人工核验覆盖表第 {line_number} 行引用不存在的文档：{document}")
            if document in decisions:
                raise ValueError(f"人工核验覆盖表存在重复文档键：{document}")
            decision = {key: (value or "").strip() for key, value in row.items() if key}
            for field, allowed in DECISION_FIELDS.items():
                value = decision.get(field, "")
                if value and value not in allowed:
                    raise ValueError(f"{document} 的 {field} 状态无效：{value}")
            conclusion_fields = set(DECISION_FIELDS) | {
                "human_corrected_title", "human_approved_topics"
            }
            changed = any(
                value and value not in {"NOT_REVIEWED", "UNVERIFIED", "NEEDS_SOURCE_INSPECTION"}
                for field, value in decision.items() if field in conclusion_fields
            )
            if changed and not decision.get("evidence_reference"):
                raise ValueError(f"{document} 已填写人工结论但缺少 evidence_reference")
            if changed and not decision.get("reviewer"):
                raise ValueError(f"{document} 已填写人工结论但缺少 reviewer")

            topic_status = decision.get("topic_review_status", "")
            approved_topics = [item.strip() for item in decision.get("human_approved_topics", "").split(";") if item.strip()]
            if topic_status and topic_status != "NOT_REVIEWED":
                if not approved_topics:
                    raise ValueError(f"{document} 已提交主题复核状态但缺少 human_approved_topics")
                if len(approved_topics) != len(set(approved_topics)):
                    raise ValueError(f"{document} 的 human_approved_topics 存在重复主题")
                unknown_topics = set(approved_topics) - set(catalog.TOPICS)
                if unknown_topics:
                    raise ValueError(f"{document} 的 human_approved_topics 包含未知主题：{', '.join(sorted(unknown_topics))}")
            elif approved_topics and not topic_status:
                raise ValueError(f"{document} 填写 human_approved_topics 但未填写 topic_review_status")

            title_status = decision.get("title_review_status", "")
            corrected_title = decision.get("human_corrected_title", "")
            if title_status == "RENAME_REQUIRED" and not corrected_title:
                raise ValueError(f"{document} 标题状态为 RENAME_REQUIRED 但缺少 human_corrected_title")
            if corrected_title and title_status != "RENAME_REQUIRED":
                raise ValueError(f"{document} 填写 human_corrected_title 时 title_review_status 必须为 RENAME_REQUIRED")
            decisions[document] = decision
    return decisions


def apply_decisions(rows: list[dict[str, Any]], decisions: dict[str, dict[str, str]],
                    field_map: dict[str, str]) -> None:
    for row in rows:
        decision = decisions.get(str(row.get("document", "")))
        if not decision:
            continue
        for decision_field, output_field in field_map.items():
            value = decision.get(decision_field, "")
            if value:
                row[output_field] = value
        if decision.get("reviewer"):
            row["reviewer"] = decision["reviewer"]
        if decision.get("review_notes"):
            row["review_notes"] = decision["review_notes"]
        if decision.get("evidence_reference"):
            row["evidence_reference"] = decision["evidence_reference"]



def assign_review_batches(rows: list[dict[str, Any]], batch_size: int = 50) -> list[dict[str, Any]]:
    """Assign deterministic batches by repository-relative document path."""
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    ordered = sorted(rows, key=lambda row: str(row.get("document", "")))
    total = len(ordered)
    for index, row in enumerate(ordered, start=1):
        batch_number = (index - 1) // batch_size + 1
        row["batch_id"] = f"TOPIC-{batch_number:03d}"
        row["batch_position"] = index - (batch_number - 1) * batch_size
        row["batch_size"] = min(batch_size, total - (batch_number - 1) * batch_size)
    return ordered


def build_review_queues(documents_csv: Path, output: Path,
                        decisions_csv: Path | None = None) -> dict[str, int]:
    docs = read_documents(documents_csv)
    decisions_path = decisions_csv or documents_csv.parent.parent / "review-decisions.csv"
    decisions = load_decisions(decisions_path, {doc.get("path", "") for doc in docs})
    review_rows = []
    topic_rows = []
    empty_rows = []
    title_candidate_rows = []
    empty_count = 0
    title_sources = Counter()
    for doc in docs:
        title_source = doc.get("title_source", "UNKNOWN")
        title_sources[title_source] += 1
        title = doc.get("title", "").strip()
        title_reason = title_candidate_reason(title, title_source)
        if title_reason:
            title_candidate_rows.append({
                "document": doc.get("path", ""),
                "notebook": doc.get("notebook", ""),
                "title": title,
                "title_source": title_source,
                "reason": title_reason,
                "review_status": "NOT_REVIEWED",
                "review_notes": "",
            })
        body_status = "EMPTY_BODY" if not doc.get("search_text", "").strip() else "HAS_EXTRACTED_TEXT"
        empty_count += body_status == "EMPTY_BODY"
        if body_status == "EMPTY_BODY":
            node_types = doc.get("node_types", "")
            node_type_names = {
                part.rsplit(":", 1)[0] for part in node_types.split(";") if part
            }
            if doc.get("parse_status") != "PARSED":
                structure_status = "RAW_FALLBACK_NOT_PARSED"
            elif not node_type_names:
                structure_status = "NO_TYPED_CHILD_NODES"
            elif node_type_names == {"NodeParagraph"}:
                structure_status = "PARAGRAPH_NODES_WITHOUT_EXTRACTED_TEXT"
            else:
                structure_status = "NON_PARAGRAPH_OR_UNSUPPORTED_EMPTY_STRUCTURE"
            empty_rows.append({
                "document": doc.get("path", ""),
                "notebook": doc.get("notebook", ""),
                "parent_document": doc.get("parent_document", ""),
                "document_depth": doc.get("document_depth", 0),
                "child_document_count": doc.get("child_document_count", 0),
                "title": doc.get("title", ""),
                "title_source": title_source,
                "parse_status": doc.get("parse_status", ""),
                "bytes": doc.get("bytes", ""),
                "asset_ref_count": doc.get("asset_ref_count", ""),
                "node_types": node_types,
                "child_node_count": doc.get("child_node_count", ""),
                "structure_status": structure_status,
                "review_status": "NEEDS_SOURCE_INSPECTION",
                "review_notes": "",
            })
        review_rows.append({
            "document": doc.get("path", ""),
            "notebook": doc.get("notebook", ""),
            "parent_document": doc.get("parent_document", ""),
            "document_depth": doc.get("document_depth", 0),
            "child_document_count": doc.get("child_document_count", 0),
            "title": doc.get("title", ""),
            "title_source": title_source,
            "topics": doc.get("topics", ""),
            "parse_status": doc.get("parse_status", ""),
            "body_status": body_status,
            "title_review_status": "NOT_REVIEWED",
            "topic_review_status": "NOT_REVIEWED",
            "source_status": "UNVERIFIED",
            "source_version_status": "UNVERIFIED",
            "collation_status": "NOT_REVIEWED",
            "reviewer": "",
            "review_notes": "",
        })
        evidence = matched_terms_by_source(doc.get("title", ""), doc.get("search_text", ""))
        matches = {topic: hits["title"] + hits["body_excerpt"] for topic, hits in evidence.items()}
        catalog_topics = [topic for topic in doc.get("topics", "").split(";") if topic]
        # The catalogue classifies the full body, while this review tool only
        # receives a 2,000-character excerpt. Queue either source of multi-topic
        # evidence so truncated excerpts cannot hide a full-body multi-topic row.
        if len(matches) > 1 or len(catalog_topics) > 1:
            topic_rows.append({
                "document": doc.get("path", ""),
                "notebook": doc.get("notebook", ""),
                "title": doc.get("title", ""),
                "title_source": title_source,
                "catalog_topics": doc.get("topics", ""),
                "catalog_matched_terms": doc.get("topic_matched_terms", ""),
                "catalog_title_matched_terms": doc.get("title_topic_matched_terms", ""),
                "catalog_body_matched_terms": doc.get("body_topic_matched_terms", ""),
                "catalog_topic_count": len(catalog_topics),
                "excerpt_topic_count": len(matches),
                "topic_count": len(catalog_topics),
                "review_bucket": review_bucket(len(catalog_topics)),
                "excerpt_topics": ";".join(matches),
                "evidence_scope": "TITLE_PLUS_FIRST_2000_BODY_CHARS",
                "title_matched_terms": ";".join(
                    f"{topic}:{'、'.join(hits['title'])}"
                    for topic, hits in evidence.items() if hits["title"]
                ),
                "body_excerpt_matched_terms": ";".join(
                    f"{topic}:{'、'.join(hits['body_excerpt'])}"
                    for topic, hits in evidence.items() if hits["body_excerpt"]
                ),
                "matched_terms": ";".join(
                    f"{topic}:{'、'.join(terms)}" for topic, terms in matches.items()
                ),
                "search_text": doc.get("search_text", ""),
                "review_status": "NOT_REVIEWED",
                "review_notes": "",
            })

    apply_decisions(review_rows, decisions, {
        "title_review_status": "title_review_status",
        "topic_review_status": "topic_review_status",
        "source_status": "source_status",
        "source_version_status": "source_version_status",
        "collation_status": "collation_status",
        "human_corrected_title": "human_corrected_title",
        "human_approved_topics": "human_approved_topics",
    })
    apply_decisions(title_candidate_rows, decisions, {
        "title_review_status": "review_status",
        "human_corrected_title": "human_corrected_title",
    })
    apply_decisions(topic_rows, decisions, {"topic_review_status": "review_status"})
    apply_decisions(empty_rows, decisions, {"empty_body_status": "review_status"})
    topic_rows = assign_review_batches(topic_rows)

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "document_review.csv", review_rows, [
        "document", "notebook", "parent_document", "document_depth", "child_document_count",
        "title", "title_source", "topics", "parse_status", "body_status",
        "title_review_status", "topic_review_status", "source_status", "source_version_status",
        "collation_status", "human_corrected_title", "human_approved_topics",
        "reviewer", "review_notes", "evidence_reference",
    ])
    write_csv(output / "title_review_candidates.csv", title_candidate_rows, [
        "document", "notebook", "title", "title_source", "reason",
        "review_status", "human_corrected_title", "review_notes", "evidence_reference",
    ])
    write_csv(output / "empty_body_review.csv", empty_rows, [
        "document", "notebook", "parent_document", "document_depth", "child_document_count",
        "title", "title_source", "parse_status",
        "bytes", "asset_ref_count", "node_types", "child_node_count",
        "structure_status", "review_status", "review_notes", "evidence_reference",
    ])
    write_csv(output / "topic_review.csv", topic_rows, [
        "document", "notebook", "title", "title_source", "catalog_topics", "catalog_matched_terms",
        "catalog_title_matched_terms", "catalog_body_matched_terms", "catalog_topic_count", "excerpt_topic_count", "topic_count", "review_bucket",
        "excerpt_topics", "title_matched_terms", "body_excerpt_matched_terms",
        "matched_terms", "evidence_scope",
        "search_text", "review_status", "review_notes", "evidence_reference",
    ])
    write_csv(output / "topic_review_batches.csv", topic_rows, [
        "batch_id", "batch_position", "batch_size", "document", "notebook", "title",
        "title_source", "catalog_topics", "catalog_matched_terms", "catalog_title_matched_terms",
        "catalog_body_matched_terms", "catalog_topic_count",
        "excerpt_topic_count", "topic_count", "review_bucket", "excerpt_topics",
        "title_matched_terms", "body_excerpt_matched_terms", "matched_terms",
        "evidence_scope", "search_text", "review_status", "review_notes", "evidence_reference",
    ])
    batch_counts = Counter(row["batch_id"] for row in topic_rows)
    report = [
        "# 逐篇人工核验队列",
        "",
        f"- 文档记录：{len(docs)}",
        f"- 正文抽取为空：{empty_count}",
        f"- 多主题关键词命中、待人工复核：{len(topic_rows)}",
        "- 多主题复核分组：" + "；".join(
            f"{bucket}={sum(row['review_bucket'] == bucket for row in topic_rows)}"
            for bucket in ("5_PLUS_TOPICS", "3_TO_4_TOPICS", "2_TOPICS", "0_TO_1_TOPICS")
        ),
        "- 标题来源分布：" + "；".join(f"{key}={value}" for key, value in sorted(title_sources.items())),
        "- catalog_matched_terms 保留标题和完整正文的机器命中词；人工复核的 excerpt 证据仍只覆盖标题和前 2000 字正文片段，两者可能不完全一致。",
        "- 所有来源、版本及校勘状态均初始化为 UNVERIFIED / NOT_REVIEWED；未从文件名或关键词推断出处。",
        "",
        "## 文件",
        "",
        "- 人工核验状态、证据要求和附件本地检查方法见 catalog/REVIEW_GUIDE.md。",
        "- 人工结论从 catalog/review-decisions.csv 读取；该文件与自动生成产物分离，重建索引不会覆盖人工结论。",
        f"- 已应用人工核验覆盖记录：{len(decisions)} 篇；无覆盖记录时保持 NOT_REVIEWED / UNVERIFIED。",
        "- document_review.csv：逐篇标题、正文、来源、版本、校勘人工核验状态及父子文档上下文。",
        "- topic_review.csv：完整多主题复核清单。",
        f"- topic_review_batches.csv：按文档仓库相对路径排序后每批 50 篇的人工工作包索引，共 {len(batch_counts)} 批；批次只用于组织工作，不保存人工结论。",
        "- empty_body_review.csv：单独列出正文抽取为空的文档，等待回看原始 .sy。",
        f"- title_review_candidates.csv：标题来源回退或命中少量通用目录标签的候选项，共 {len(title_candidate_rows)} 篇；均未自动判错。",
        "",
        "## 边界",
        "",
        "- 主题命中只是字符串包含关系，不是语义分类；多主题记录只是复核队列，不自动判为错误。",
        "- title_source 区分 Properties 字段、正文首行回退、文件名回退及原始文本回退；回退标题不得当作已核验书名或篇名。",
        "- title_matched_terms 与 body_excerpt_matched_terms 分开记录标题命中和前 2000 字正文片段命中；二者都只是字符串证据。",
        "- review_bucket 仅按当前主题标签数量分组，方便分批检查，不代表错误程度或医学风险。",
        "- topic_review_batches.csv 每次按 document 路径字典序重新分批；新增/删除文档可能改变后续批次边界。人工结论仍只写入 catalog/review-decisions.csv。",
        "- 空正文可能来自空白文档、非文本内容或提取器尚未覆盖的节点类型，必须回看原始 .sy。",
        "- 本清单不构成医学内容真实性、出处或临床有效性的证明。",
        "",
    ]
    (output / "review_queue.md").write_text("\n".join(report), encoding="utf-8")
    return {"documents": len(docs), "empty_bodies": empty_count,
            "multi_topic_review": len(topic_rows), "topic_review_batches": len(batch_counts)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, default=None,
                        help="人工核验覆盖 CSV；默认 <repo>/catalog/review-decisions.csv")
    args = parser.parse_args()
    result = build_review_queues(args.documents, args.output, args.decisions)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
