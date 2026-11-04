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
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name("build_siyuan_catalog.py")
SPEC = importlib.util.spec_from_file_location("build_siyuan_catalog", MODULE_PATH)
catalog = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(catalog)


def matched_terms(title: str, text: str) -> dict[str, list[str]]:
    haystack = (title + "\n" + text).lower()
    return {
        topic: [term for term in terms if term.lower() in haystack]
        for topic, terms in catalog.TOPICS.items()
        if any(term.lower() in haystack for term in terms)
    }


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
    empty_count = 0
    for doc in docs:
        body_status = "EMPTY_BODY" if not doc.get("search_text", "").strip() else "HAS_EXTRACTED_TEXT"
        empty_count += body_status == "EMPTY_BODY"
        review_rows.append({
            "document": doc.get("path", ""),
            "notebook": doc.get("notebook", ""),
            "title": doc.get("title", ""),
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
        matches = matched_terms(doc.get("title", ""), doc.get("search_text", ""))
        if len(matches) > 1:
            topic_rows.append({
                "document": doc.get("path", ""),
                "notebook": doc.get("notebook", ""),
                "title": doc.get("title", ""),
                "topic_count": len(matches),
                "topics": ";".join(matches),
                "matched_terms": ";".join(
                    f"{topic}:{'、'.join(terms)}" for topic, terms in matches.items()
                ),
                "search_text": doc.get("search_text", ""),
                "review_status": "NOT_REVIEWED",
                "review_notes": "",
            })

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "document_review.csv", review_rows, [
        "document", "notebook", "title", "topics", "parse_status", "body_status",
        "title_review_status", "source_status", "source_version_status",
        "collation_status", "reviewer", "review_notes",
    ])
    write_csv(output / "topic_review.csv", topic_rows, [
        "document", "notebook", "title", "topic_count", "topics",
        "matched_terms", "search_text", "review_status", "review_notes",
    ])
    report = [
        "# 逐篇人工核验队列",
        "",
        f"- 文档记录：{len(docs)}",
        f"- 正文抽取为空：{empty_count}",
        f"- 多主题关键词命中、待人工复核：{len(topic_rows)}",
        "- 所有来源、版本及校勘状态均初始化为 UNVERIFIED / NOT_REVIEWED；未从文件名或关键词推断出处。",
        "- 标题状态统一为 NOT_REVIEWED；当前索引没有可靠的标题来源字段，因此不伪造“已核验标题”。",
        "",
        "## 文件",
        "",
        "- document_review.csv：逐篇标题、正文、来源、版本、校勘人工核验状态。",
        "- topic_review.csv：多主题命中的关键词证据和正文片段，供人工判断是否误分类。",
        "",
        "## 边界",
        "",
        "- 主题命中只是字符串包含关系，不是语义分类；多主题记录只是复核队列，不自动判为错误。",
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
