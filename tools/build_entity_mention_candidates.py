#!/usr/bin/env python3
"""Extract dictionary-backed TCM entity mentions with exact source spans.

This is lexical candidate extraction, not medical interpretation or entity
resolution. Overlapping mentions are intentionally retained (e.g. a herb name
inside a formula name). Every mention points back to one indexed source block.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REQUIRED_CONTENT_FIELDS = {
    "document", "source_sha256", "tree_position", "block_id",
    "content_type", "section_path", "content_text",
}
LEXICON_FIELDS = {"entity_type", "term"}
OUTPUT_FIELDS = [
    "mention_id", "unit_id", "entity_type", "matched_text",
    "character_start", "character_end", "document", "source_sha256",
    "tree_position", "block_id", "content_type", "section_path",
    "lexicon_version", "extraction_method", "resolution_status",
]


def unit_id(row: dict[str, str]) -> str:
    identity = "\0".join((
        row["document"], row["source_sha256"], row["tree_position"],
        row.get("block_id", ""),
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def read_lexicon(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = LEXICON_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("lexicon missing fields: " + ", ".join(sorted(missing)))
        terms = []
        seen = set()
        for row in reader:
            entity_type = (row.get("entity_type") or "").strip().upper()
            term = (row.get("term") or "").strip()
            version = (row.get("lexicon_version") or "1.0.0").strip()
            if not entity_type or not term:
                raise ValueError("lexicon entity_type and term must be non-empty")
            key = (entity_type, term)
            if key in seen:
                continue
            seen.add(key)
            terms.append({"entity_type": entity_type, "term": term, "lexicon_version": version})
    return sorted(terms, key=lambda item: (item["entity_type"], item["term"]))


def build_matcher(lexicon: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Build an Aho-Corasick automaton; overlapping terms are retained."""
    nodes: list[dict[str, Any]] = [{"next": {}, "fail": 0, "output": []}]
    for item in lexicon:
        state = 0
        for char in item["term"].casefold():
            if char not in nodes[state]["next"]:
                nodes[state]["next"][char] = len(nodes)
                nodes.append({"next": {}, "fail": 0, "output": []})
            state = nodes[state]["next"][char]
        nodes[state]["output"].append(item)
    queue = list(nodes[0]["next"].values())
    cursor = 0
    while cursor < len(queue):
        state = queue[cursor]
        cursor += 1
        for char, child in nodes[state]["next"].items():
            queue.append(child)
            fallback = nodes[state]["fail"]
            while fallback and char not in nodes[fallback]["next"]:
                fallback = nodes[fallback]["fail"]
            nodes[child]["fail"] = nodes[fallback]["next"].get(char, 0)
            nodes[child]["output"].extend(nodes[nodes[child]["fail"]]["output"])
    return nodes


def find_matches(text: str, nodes: list[dict[str, Any]]):
    state = 0
    matches = []
    for index, char in enumerate(text.casefold()):
        while state and char not in nodes[state]["next"]:
            state = nodes[state]["fail"]
        state = nodes[state]["next"].get(char, 0)
        for item in nodes[state]["output"]:
            end = index + 1
            matches.append((end - len(item["term"]), end, item))
    # Distinct lexicon formula names may be nested (e.g. a named base formula
    # inside a modified formula name). Preserve every exact lexical hit with
    # its own source span; downstream relations remain unresolved candidates.
    matches.sort(key=lambda hit: (hit[0], hit[1], hit[2]["entity_type"], hit[2]["term"]))
    return matches


def extract(content_index: Path, lexicon_path: Path, output: Path) -> dict[str, Any]:
    if not content_index.is_file():
        raise FileNotFoundError(content_index)
    lexicon = read_lexicon(lexicon_path)
    if not lexicon:
        raise ValueError("lexicon contains no terms")
    output.mkdir(parents=True, exist_ok=True)
    target = output / "entity_mention_candidates.csv.gz"
    counts: dict[str, int] = {}
    blocks = 0
    mentions = 0
    seen_ids: set[str] = set()
    matcher = build_matcher(lexicon)
    with (gzip.open(content_index, "rt", encoding="utf-8-sig", newline="") as source,
          gzip.open(target, "wt", encoding="utf-8", newline="") as destination):
        reader = csv.DictReader(source)
        missing = REQUIRED_CONTENT_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("content index missing fields: " + ", ".join(sorted(missing)))
        writer = csv.DictWriter(destination, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in reader:
            text = row.get("content_text") or ""
            if not text:
                continue
            blocks += 1
            source_unit_id = unit_id(row)
            for start, end, item in find_matches(text, matcher):
                term = item["term"]
                identity = "\0".join((source_unit_id, item["entity_type"], str(start), str(end), term))
                mention_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                if mention_id in seen_ids:
                    raise ValueError("duplicate mention_id: " + mention_id)
                seen_ids.add(mention_id)
                writer.writerow({
                    "mention_id": mention_id, "unit_id": source_unit_id,
                    "entity_type": item["entity_type"], "matched_text": text[start:end],
                    "character_start": start, "character_end": end,
                    "document": row["document"], "source_sha256": row["source_sha256"],
                    "tree_position": row["tree_position"], "block_id": row.get("block_id", ""),
                    "content_type": row["content_type"], "section_path": row.get("section_path", ""),
                    "lexicon_version": item["lexicon_version"],
                    "extraction_method": "EXACT_LEXICON_MATCH",
                    "resolution_status": "UNRESOLVED_CANDIDATE",
                })
                counts[item["entity_type"]] = counts.get(item["entity_type"], 0) + 1
                mentions += 1

    report = [
        "# 词典匹配实体候选",
        "",
        f"- 扫描内容块：{blocks}",
        f"- 词典词条：{len(lexicon)}",
        f"- 实体提及候选：{mentions}",
        f"- 唯一提及 ID：{len(seen_ids)}",
        "",
        "## 类型分布",
        "",
        *[f"- {kind}: {count}" for kind, count in sorted(counts.items())],
        "",
        "## 输出与边界",
        "",
        "- entity_mention_candidates.csv.gz：逐次出现的实体提及，保留精确字符区间及原始块定位。",
        "- 使用精确词典匹配；不做同义词推断、实体消歧、否定识别或医学关系推断。",
        "- 重叠匹配会同时保留，例如方剂名称与其中包含的药名。",
        "- 所有记录标记为 UNRESOLVED_CANDIDATE，不代表已经确认实体或医学事实。",
        "- 扩充词典只增加候选覆盖，不修改原始笔记。",
    ]
    (output / "entity_mention_candidates.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return {"content_blocks": blocks, "lexicon_terms": len(lexicon), "mentions": mentions, **{f"type_{k.lower()}": v for k, v in sorted(counts.items())}}


def validate(path: Path, knowledge_units_path: Path | None = None) -> int:
    units: dict[str, dict[str, Any]] = {}
    if knowledge_units_path is not None:
        with gzip.open(knowledge_units_path, "rt", encoding="utf-8", newline="") as source:
            for unit_line, raw in enumerate(source, 1):
                unit = json.loads(raw)
                units[unit["unit_id"]] = unit
    count = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            start, end = int(row["character_start"]), int(row["character_end"])
            if start < 0 or end <= start:
                raise ValueError(f"row {line}: invalid character span")
            if row["resolution_status"] != "UNRESOLVED_CANDIDATE":
                raise ValueError(f"row {line}: candidate status was changed")
            if row["extraction_method"] != "EXACT_LEXICON_MATCH":
                raise ValueError(f"row {line}: unexpected extraction method")
            if not row["mention_id"] or not row["unit_id"] or not row["document"]:
                raise ValueError(f"row {line}: missing identity or provenance")
            if knowledge_units_path is not None:
                unit = units.get(row["unit_id"])
                if unit is None:
                    raise ValueError(f"row {line}: unit_id not found in knowledge units")
                source = unit["source"]
                text = unit["content"]["source_text"]
                if text[start:end] != row["matched_text"]:
                    raise ValueError(f"row {line}: source span does not match knowledge unit text")
                if (source["document"] != row["document"]
                    or source["sha256"] != row["source_sha256"]
                    or source["tree_position"] != row["tree_position"]
                    or source.get("block_id", "") != row["block_id"]):
                    raise ValueError(f"row {line}: provenance differs from knowledge unit")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-index", type=Path, default=Path("catalog/generated/content_block_index.csv.gz"))
    parser.add_argument("--lexicon", type=Path, default=Path("catalog/entity-lexicon.csv"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated"))
    parser.add_argument("--knowledge-units", type=Path, default=Path("catalog/generated/knowledge_units.jsonl.gz"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        count = validate(args.output / "entity_mention_candidates.csv.gz", args.knowledge_units)
        print(json.dumps({"validated_mentions": count}, ensure_ascii=False))
    else:
        result = extract(args.content_index, args.lexicon, args.output)
        validate(args.output / "entity_mention_candidates.csv.gz", args.knowledge_units)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
