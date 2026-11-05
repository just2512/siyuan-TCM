#!/usr/bin/env python3
"""Build conservative, explainable audits for topic-rule and title-extraction risks.

This tool only identifies review signals from generated metadata. It never
changes topic labels or titles and never claims semantic correctness.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

# These terms are deliberately treated as broad retrieval signals, not errors.
BROAD_TERMS = {
    "经典与理论": {"阴阳", "五行", "经络"},
    "伤寒与温病": {"六经", "温病", "少阳"},
    "方剂与用药": {"方剂", "药方", "处方", "剂量", "配伍", "加减", "煎服", "药性", "用药"},
    "中药与本草": {"药材", "药图", "性味", "归经"},
    "针灸与经穴": {"针法", "刺法"},
    "诊断与辨证": {"问诊", "辨证", "合病", "并病"},
    "医家与课程": {"医案", "讲座", "课程"},
}
SENTENCE_MARKS = set("。！？；;!?")
GENERIC_TITLES = {"其他", "方剂", "药势", "总义", "穴", "法门", "收纳", "未命名", "待收录", "笔记", "无标题", "untitled"}


def parse_evidence(value: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in (value or "").split(";"):
        if ":" not in item:
            continue
        topic, terms = item.split(":", 1)
        parsed = [term for term in terms.split("、") if term]
        if topic and parsed:
            result[topic] = parsed
    return result


def title_audit_reason(title: str, title_source: str) -> list[str]:
    normalized = " ".join((title or "").split())
    flags = []
    if title_source != "PROPERTY":
        flags.append("TITLE_IS_FALLBACK")
    if normalized.lower() in GENERIC_TITLES:
        flags.append("GENERIC_OR_PLACEHOLDER_TITLE")
    if len(normalized) > 60 or any(mark in normalized for mark in SENTENCE_MARKS):
        flags.append("TITLE_RESEMBLES_BODY_SENTENCE")
    if not normalized:
        flags.append("EMPTY_TITLE")
    return flags


def build_audits(documents: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    title_rows = []
    topic_rows = []
    for doc in documents:
        path = doc.get("path", "")
        title = doc.get("title", "")
        source = doc.get("title_source", "UNKNOWN")
        title_flags = title_audit_reason(title, source)
        if title_flags:
            title_rows.append({
                "document": path,
                "notebook": doc.get("notebook", ""),
                "title": title,
                "title_source": source,
                "title_length": len(title),
                "audit_flags": ";".join(title_flags),
                "review_status": "NOT_REVIEWED",
                "review_notes": "",
                "evidence_reference": "",
            })

        title_evidence = parse_evidence(doc.get("title_topic_matched_terms", ""))
        body_evidence = parse_evidence(doc.get("body_topic_matched_terms", ""))
        assigned_topics = [x for x in doc.get("topics", "").split(";") if x]
        for topic in assigned_topics:
            terms = sorted(set(title_evidence.get(topic, []) + body_evidence.get(topic, [])))
            if not terms:
                continue
            broad = sorted(set(terms) & BROAD_TERMS.get(topic, set()))
            specific = sorted(set(terms) - set(broad))
            flags = []
            if broad and not specific:
                flags.append("BROAD_TERM_ONLY")
            if topic in title_evidence and topic not in body_evidence:
                flags.append("TITLE_ONLY_MATCH")
            if topic in body_evidence and topic not in title_evidence:
                flags.append("BODY_ONLY_MATCH")
            if len(assigned_topics) > 1:
                flags.append("MULTI_TOPIC_DOCUMENT")
            if not flags:
                flags.append("NO_STATIC_RISK_SIGNAL")
            topic_rows.append({
                "document": path,
                "notebook": doc.get("notebook", ""),
                "title": title,
                "topic": topic,
                "all_matched_terms": "、".join(terms),
                "broad_matched_terms": "、".join(broad),
                "other_matched_terms": "、".join(specific),
                "title_matched_terms": "、".join(title_evidence.get(topic, [])),
                "body_matched_terms": "、".join(body_evidence.get(topic, [])),
                "audit_flags": ";".join(flags),
                "review_status": "NOT_REVIEWED",
                "review_notes": "",
                "evidence_reference": "",
            })
    title_rows.sort(key=lambda row: row["document"])
    topic_rows.sort(key=lambda row: (row["document"], row["topic"]))
    return title_rows, topic_rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(documents_path: Path, output_dir: Path) -> dict[str, int]:
    docs = read_csv(documents_path)
    title_rows, topic_rows = build_audits(docs)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "title_extraction_audit.csv", title_rows, [
        "document", "notebook", "title", "title_source", "title_length",
        "audit_flags", "review_status", "review_notes", "evidence_reference",
    ])
    write_csv(output_dir / "topic_rule_audit.csv", topic_rows, [
        "document", "notebook", "title", "topic", "all_matched_terms",
        "broad_matched_terms", "other_matched_terms", "title_matched_terms",
        "body_matched_terms", "audit_flags", "review_status", "review_notes",
        "evidence_reference",
    ])
    report = [
        "# 主题规则与标题抽取审计",
        "",
        f"- 输入文档：{len(docs)}",
        f"- 标题风险信号：{len(title_rows)}",
        f"- 逐文档主题命中记录：{len(topic_rows)}",
        "",
        "## 输出",
        "",
        "- title_extraction_audit.csv：列出回退标题、通用标题、疑似正文句子标题等静态信号。",
        "- topic_rule_audit.csv：逐文档、逐主题拆分命中词，并标记宽泛词单独触发、仅标题命中、仅正文命中和多主题文档。",
        "",
        "## 判读边界",
        "",
        "- audit_flags 是复核线索，不是误报判定；不自动删除主题、不改写标题。",
        "- broad term 只是当前规则中相对宽泛的词，不代表该词在具体上下文中无效。",
        "- 本审计依赖完整正文生成阶段写入的命中证据字段，不以 2,000 字 search_text 代替完整正文。",
        "- 标题语义、主题相关性、附件内容和书目来源仍需查看原始资料；没有原始证据时保持 NOT_REVIEWED / UNVERIFIED。",
        "",
    ]
    (output_dir / "extraction_audit.md").write_text("\n".join(report), encoding="utf-8")
    return {"documents": len(docs), "title_audit": len(title_rows), "topic_audit": len(topic_rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.documents, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
