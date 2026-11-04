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
from collections import Counter
from pathlib import Path
from typing import Any

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
    if topic_count >= 5:
        return "5_PLUS_TOPICS"
    if topic_count >= 3:
        return "3_TO_4_TOPICS"
    return "2_TOPICS"


def read_documents(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_review_queues(documents_csv: Path, output: Path) -> dict[str, int]:
    docs = read_documents(documents_csv)
    review_rows = []
    topic_rows = []
    empty_rows = []
    empty_count = 0
    title_sources = Counter()
    for doc in docs:
        title_source = doc.get("title_source", "UNKNOWN")
        title_sources[title_source] += 1
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
            "title": doc.get("title", ""),
            "title_source": title_source,
            "topics": doc.get("topics", ""),
            "parse_status": doc.get("parse_status", ""),
            "body_status": body_status,
            "title_review_status": "NOT_REVIEWED",
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

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "document_review.csv", review_rows, [
        "document", "notebook", "title", "title_source", "topics", "parse_status", "body_status",
        "title_review_status", "source_status", "source_version_status",
        "collation_status", "reviewer", "review_notes",
    ])
    write_csv(output / "empty_body_review.csv", empty_rows, [
        "document", "notebook", "title", "title_source", "parse_status",
        "bytes", "asset_ref_count", "node_types", "child_node_count",
        "structure_status", "review_status", "review_notes",
    ])
    write_csv(output / "topic_review.csv", topic_rows, [
        "document", "notebook", "title", "title_source", "catalog_topics",
        "catalog_topic_count", "excerpt_topic_count", "topic_count", "review_bucket",
        "excerpt_topics", "title_matched_terms", "body_excerpt_matched_terms",
        "matched_terms", "evidence_scope",
        "search_text", "review_status", "review_notes",
    ])
    report = [
        "# 逐篇人工核验队列",
        "",
        f"- 文档记录：{len(docs)}",
        f"- 正文抽取为空：{empty_count}",
        f"- 多主题关键词命中、待人工复核：{len(topic_rows)}",
        "- 多主题复核分组：" + "；".join(
            f"{bucket}={sum(row['review_bucket'] == bucket for row in topic_rows)}"
            for bucket in ("5_PLUS_TOPICS", "3_TO_4_TOPICS", "2_TOPICS")
        ),
        "- 标题来源分布：" + "；".join(f"{key}={value}" for key, value in sorted(title_sources.items())),
        "- 命中证据仅覆盖标题和前 2000 字正文片段；正式主题标签使用完整正文，两者可能不完全一致。",
        "- 所有来源、版本及校勘状态均初始化为 UNVERIFIED / NOT_REVIEWED；未从文件名或关键词推断出处。",
        "",
        "## 文件",
        "",
        "- document_review.csv：逐篇标题、正文、来源、版本、校勘人工核验状态。",
        "- topic_review.csv：多主题命中的关键词证据和正文片段，供人工判断是否误分类。",
        "- empty_body_review.csv：单独列出正文抽取为空的文档，等待回看原始 .sy。",
        "",
        "## 边界",
        "",
        "- 主题命中只是字符串包含关系，不是语义分类；多主题记录只是复核队列，不自动判为错误。",
        "- title_source 区分 Properties 字段、正文首行回退、文件名回退及原始文本回退；回退标题不得当作已核验书名或篇名。",
        "- title_matched_terms 与 body_excerpt_matched_terms 分开记录标题命中和前 2000 字正文片段命中；二者都只是字符串证据。",
        "- review_bucket 仅按当前主题标签数量分组，方便分批检查，不代表错误程度或医学风险。",
        "- 空正文可能来自空白文档、非文本内容或提取器尚未覆盖的节点类型，必须回看原始 .sy。",
        "- 本清单不构成医学内容真实性、出处或临床有效性的证明。",
        "",
    ]
    (output / "review_queue.md").write_text("\n".join(report), encoding="utf-8")
    return {"documents": len(docs), "empty_bodies": empty_count,
            "multi_topic_review": len(topic_rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_review_queues(args.documents, args.output)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
