#!/usr/bin/env python3
"""Classify every corpus occurrence of mined terms using exact local context.

The mined-term file supplies the candidate vocabulary; classification is
performed against every occurrence in the source knowledge units, not only
the bounded sample snippets retained for vocabulary discovery.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
import gzip
import json
import re
import sys
try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None
from pathlib import Path

from build_unclassified_term_candidates import candidate_id

RULES = {
    "SYMPTOM": [
        ("SYMPTOM_CONTEXT_01", r"(?:症见|症状|表现为|可见|见有|出现|伴有)"),
        ("SYMPTOM_CONTEXT_02", r"(?:疼痛|胀痛|刺痛|麻木|瘙痒|咳嗽|恶心|呕吐|发热|畏寒)"),
    ],
    "PULSE": [
        ("PULSE_CONTEXT_01", r"(?:脉象|脉诊|脉见|脉沉|脉浮|脉数|脉迟|脉弦|脉滑|脉细)"),
    ],
    "TONGUE": [
        ("TONGUE_CONTEXT_01", r"(?:舌象|舌质|舌苔|舌红|舌淡|舌绛|苔白|苔黄|苔腻)"),
    ],
    "SYNDROME": [
        ("SYNDROME_CONTEXT_01", r"(?:辨证为|辨证属|(?<!条)辨为|证属|(?<!不)(?<!未)属于|证候|证型|此证|本证)"),
    ],
    "TREATMENT": [
        ("TREATMENT_CONTEXT_01", r"(?:治法(?:为|是)|治法[：:]|治宜|宜.{0,4}法|治以|当以|治疗原则|治疗方法)"),
    ],
    "FORMULA": [
        ("FORMULA_CONTEXT_01", r"(?:方用|用.{0,8}方|选用.{0,8}方|处方|方剂组成|组成[:：])"),
    ],
    "HERB": [
        ("HERB_CONTEXT_01", r"(?:药用|用药|药物组成|中药|本草|配伍)"),
    ],
}
FIELDS = [
    "candidate_id", "term", "candidate_type", "rule_id",
    "evidence_document", "source_sha256", "tree_position", "block_id",
    "unit_id", "character_start", "character_end", "evidence_start",
    "evidence_text", "classification_status",
]
HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
NGRAM_PATTERNS = {
    length: re.compile(rf"(?=([\u3400-\u4dbf\u4e00-\u9fff]{{{length}}}))")
    for length in range(2, 7)
}
PUNCTUATION = "，。！？；、\n"
SENTENCE_BOUNDARIES = "。！？；\n"
AUTHOR_ATTRIBUTION_BOUNDARY = re.compile(
    r"(?:[\u3400-\u9fff]{1,8}(?:曰|云)[：:∶]|《[^》\n]{1,40}》(?:曰|云)[：:∶])"
)


def evidence_window(text: str, start: int, end: int, context: int = 12) -> tuple[int, int]:
    """Return a bounded evidence window that cannot cross sentence or attribution boundaries."""
    if start < 0 or end <= start or end > len(text):
        raise ValueError("candidate span is outside source text")
    left = max(text.rfind(mark, 0, start) for mark in SENTENCE_BOUNDARIES) + 1
    right_candidates = [text.find(mark, end) for mark in SENTENCE_BOUNDARIES]
    right_candidates = [pos for pos in right_candidates if pos >= 0]
    right = min(right_candidates) if right_candidates else len(text)
    for match in AUTHOR_ATTRIBUTION_BOUNDARY.finditer(text, left, start):
        left = max(left, match.end())
    next_attribution = AUTHOR_ATTRIBUTION_BOUNDARY.search(text, end, right)
    if next_attribution:
        right = min(right, next_attribution.start())
    return max(left, start - context), min(right, end + context)


PREFIX_ONLY_TYPES = {"SYNDROME", "TREATMENT", "FORMULA", "HERB"}


class FormulaSpanIndex:
    """Immutable per-unit interval index for repeated formula-overlap queries."""

    __slots__ = ("starts", "prefix_max_ends")

    def __init__(self, spans: list[tuple[int, int]]):
        ordered = sorted((int(start), int(end)) for start, end in spans)
        self.starts = tuple(start for start, _ in ordered)
        prefix_max_ends: list[int] = []
        maximum_end = -1
        for _, end in ordered:
            maximum_end = max(maximum_end, end)
            prefix_max_ends.append(maximum_end)
        self.prefix_max_ends = tuple(prefix_max_ends)

    def overlaps(self, start: int, end: int) -> bool:
        # Find the last formula span whose start is before candidate end.
        # Prefix maxima are necessary: a long earlier interval may contain
        # the candidate even when the immediately preceding interval is short.
        index = bisect_left(self.starts, end) - 1
        return index >= 0 and self.prefix_max_ends[index] > start


def _overlaps_formula_span(
    start: int, end: int,
    formula_spans: FormulaSpanIndex | tuple[tuple[int, int], ...] | list[tuple[int, int]],
) -> bool:
    if isinstance(formula_spans, FormulaSpanIndex):
        return formula_spans.overlaps(start, end)
    # Keep the public helper compatible with callers that pass raw spans.
    return any(start < formula_end and formula_start < end
               for formula_start, formula_end in formula_spans)


def classify_span(
    text: str, start: int, end: int,
    formula_spans: FormulaSpanIndex | tuple[tuple[int, int], ...] | list[tuple[int, int]] = (),
) -> list[tuple[str, str]]:
    if start < 0 or end <= start or end > len(text):
        raise ValueError("candidate span is outside source text")
    term = text[start:end]
    left_boundary = max(text.rfind(mark, 0, start) for mark in PUNCTUATION) + 1
    before = text[max(left_boundary, start - 10):start]
    found = []
    for candidate_type, rules in RULES.items():
        # A lexical formula mention owns its exact source span. A longer
        # n-gram that merely overlaps that formula must not be retyped as a
        # treatment method (e.g. "附子汤温" around the formula "附子汤").
        if candidate_type == "TREATMENT" and _overlaps_formula_span(
            start, end, formula_spans
        ):
            continue
        # Diagnostic observations (pulse/tongue findings) are not treatment
        # methods merely because the sentence uses the broad cue "当以".
        if candidate_type == "TREATMENT" and (
            term.startswith("经脉")
            or re.search(r"舌(?:象|苔|质)", term)
        ):
            continue
        for rule_id, pattern in rules:
            # “可用” is an operational phrase, not a treatment entity;
            # do not let the generic “治法” prefix type this two-character span.
            if candidate_type == "TREATMENT" and term == "可用":
                continue
            # Duration + outcome expressions are prognosis, not treatment methods.
            # Keep this morphology-specific so valid "当以" treatment phrases survive.
            if (
                candidate_type == "TREATMENT"
                and re.fullmatch(r"[零〇一二三四五六七八九十百千万两\d]+日(?:愈|解|差)", term)
            ):
                continue
            # In "当以一生者为佳", 一生 means the raw/unprocessed state,
            # not a treatment method. Keep the exception bound to this exact
            # grammatical construction rather than blacklisting the term globally.
            if (
                candidate_type == "TREATMENT"
                and term == "一生"
                and re.search(r"当以[\s:：、]{0,2}$", before)
                and re.match(r"者为佳(?:[。！？；，、]|$)", text[end:])
            ):
                continue
            # “辨为六名” is a classical naming/counting construction, not a
            # syndrome assertion. Keep the exception tied to the grammatical
            # object shape (a term ending in 名), not a global term blacklist.
            if (
                candidate_type == "SYNDROME"
                and term.endswith("名")
                and re.search(r"辨为[\s:：、]{0,2}$", before)
            ):
                continue
            # "属于可以用的方剂" is a formula-use phrase, not a syndrome name.
            if candidate_type == "SYNDROME" and ("方剂" in term or term.startswith("可以用")):
                continue
            # Generic labels and grammatical/prognostic phrases are not syndrome names.
            if candidate_type == "SYNDROME" and term.startswith((
                "症状", "症见", "表现", "证候", "证型",
                "不能", "不可", "无法", "不属于", "属于",
            )):
                continue
            # Do not retain an n-gram cut in the middle of the clinical term 风寒咳嗽.
            if (
                candidate_type == "SYNDROME"
                and term.endswith("咳")
                and text[end:end + 1] == "嗽"
            ):
                continue
            # Prefix cues must precede the candidate. Intrinsic cues may be
            # part of the candidate itself; cues after it are never borrowed.
            if candidate_type in PREFIX_ONLY_TYPES:
                # A prefix cue must terminate immediately before the candidate
                # (allowing only a tiny punctuation/whitespace separator).
                matched = re.search(
                    rf"(?:{pattern})[\\s:：、]{{0,2}}$",
                    before,
                )
                if matched and candidate_type == "FORMULA":
                    # Generic grammar and outcome phrases are not formula names,
                    # even when a nearby "处方"/"用...方" cue is present.
                    if (
                        term[:1] in "向法式面位子剂的是"
                        or term.startswith(("本草", "药", "方", "治", "处方", "就", "是"))
                    ):
                        matched = None
                    # "使用的地方非常..." can satisfy the broad use...方 regex,
                    # but 地方 is not a formula-introduction cue.
                    elif matched.group(0).endswith("地方"):
                        matched = None
                    # "经方用药..." is a generic expression; the substring 方用
                    # must not make the following word look like a formula.
                    elif (
                        matched.group(0).endswith("方用")
                        and matched.start() > 0
                        and before[matched.start() - 1] == "经"
                    ):
                        matched = None
                    # "地方用药..." contains "方用" but does not introduce a formula.
                    elif (
                        matched.group(0).endswith("方用")
                        and matched.start() > 0
                        and before[matched.start() - 1] == "地"
                    ):
                        matched = None
                if matched and candidate_type == "HERB":
                    # A preceding "用药/中药" cue does not turn grammatical
                    # continuations or generic formula nouns into herb mentions.
                    if term.startswith((
                        "的", "是", "证", "观", "方向", "方法", "方式",
                        "方子", "方剂", "一样", "之", "就", "处方",
                        "药", "方", "后", "治", "导致", "使用"
                    )):
                        matched = None
            elif candidate_type == "SYMPTOM" and rule_id == "SYMPTOM_CONTEXT_01":
                # Symptom labels such as “症状” describe the following list;
                # they are not symptoms themselves. Allow a short list-intro
                # bridge (是/为/有 plus punctuation) before the first item.
                symptom_left = max(
                    text.rfind(mark, 0, start) for mark in "。！？；\n"
                ) + 1
                symptom_before = text[symptom_left:start]
                symptom_intro = re.compile(
                    r"(?:症见|症状(?:是|为|有)?|表现为|伴有|主诉)"
                    r"[\s:：，、]{0,4}"
                    r"(?:[\u3400-\u9fff]{1,12}[，、]\s*){0,8}$"
                )
                # A list cue cannot carry a symptom label across a new
                # narrative clause (diagnosis, attribution, treatment, etc.).
                non_symptom_clause = re.compile(
                    r"(?:西医|中医|医生|医师|患者|病人|认为|诊断|治疗|处方|药物|"
                    r"目前|经过|导致|造成|因此|所以|可见|说明|表示|相继|只是由|"
                    r"用药|药方|方剂|方子|方法|方式|条文|解释|讲法|观点|相对论|"
                    r"那至于说|你看|当以|属于|不属于|"
                    r"脉(?:象|诊|沉|浮|数|迟|弦|滑|细)|"
                    r"舌(?:象|苔|质))"
                )
                matched = (
                    None if term.startswith((
                        "症状", "症见", "表现", "证候", "证型",
                        "或者", "以及", "并且", "而且", "但是", "不过",
                        "都", "就是", "属于", "不属于", "它的", "为",
                    ))
                    or non_symptom_clause.search(symptom_before)
                    or non_symptom_clause.search(term)
                    else symptom_intro.search(symptom_before)
                )
            elif candidate_type == "SYMPTOM" and rule_id == "SYMPTOM_CONTEXT_02":
                # Intrinsic symptom words can occur inside a short anatomical
                # phrase (e.g. 骨节疼痛), but must not type a whole narrative
                # fragment such as 这个人是发热 or 发热而脉沉.
                symptom_match = re.search(pattern, term)
                allowed_prefixes = {
                    "", "头", "头部", "面", "面部", "眼", "耳", "鼻", "咽", "喉",
                    "颈", "项", "肩", "背", "腰", "腹", "小腹", "少腹", "胃", "脘",
                    "胸", "胁", "心", "四肢", "手", "足", "腿", "膝", "关节", "骨节",
                    "周身", "全身", "肌肉", "午后", "夜间", "晨起", "反复", "阵发",
                    "持续", "剧烈", "频繁", "偶发",
                }
                allowed_suffixes = {"", "不止", "不退", "加重"}
                matched = (
                    symptom_match
                    if symptom_match
                    and term[:symptom_match.start()] in allowed_prefixes
                    and term[symptom_match.end():] in allowed_suffixes
                    else None
                )
            elif candidate_type in {"PULSE", "TONGUE"}:
                # Intrinsic pulse/tongue cues must occur inside the candidate.
                # Pulse windows also have to begin at 脉; otherwise phrases like
                # 发热而脉沉 would be misclassified as one oversized pulse term.
                matched = re.search(pattern, term)
                if candidate_type == "PULSE":
                    # A pulse candidate must be a complete clinical pulse
                    # phrase, not a valid prefix followed by discourse text
                    # (脉象虽然/脉浮的/脉象怎么).
                    pulse_phrase = re.fullmatch(
                        r"脉(?:象|诊|见|为|沉|浮|数|迟|弦|滑|细)"
                        r"(?:紧|数|细|迟|缓|滑|弦|沉|浮|弱|虚|实)?",
                        term,
                    )
                    matched = matched if pulse_phrase else None
            else:
                matched = re.search(pattern, before + term)
            if (
                matched
                and candidate_type == "SYNDROME"
                and "属于发热充血的状态" in text[max(0, start - 8):min(len(text), end + 10)]
            ):
                matched = None
            if matched:
                found.append((candidate_type, rule_id))
    return found


def classify_sample(sample: dict[str, str]) -> list[tuple[str, str]]:
    text = sample.get("evidence_text", "")
    term = sample.get("matched_text", "")
    if not term:
        return []
    start = int(sample.get("character_start", 0)) - int(sample.get("evidence_start", 0))
    end = start + len(term)
    if start < 0 or end > len(text) or text[start:end] != term:
        raise ValueError("candidate term does not match its source evidence span")
    return classify_span(text, start, end)


def load_candidate_terms(source_path: Path) -> set[str]:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    terms: set[str] = set()
    with gzip.open(source_path, "rt", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"candidate_id", "term", "candidate_status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("term candidate input missing fields: " + ", ".join(sorted(missing)))
        for line, candidate in enumerate(reader, 2):
            term = candidate["term"]
            if candidate["candidate_status"] != "UNCLASSIFIED_TERM_CANDIDATE":
                raise ValueError(f"input row {line} contains a non-unclassified candidate")
            if not term or candidate["candidate_id"] != candidate_id(term):
                raise ValueError(f"input row {line} has an invalid candidate identity")
            if len(term) < 2 or len(term) > 6:
                raise ValueError(f"input row {line} has a term outside the mined n-gram range")
            if term in terms:
                raise ValueError(f"input row {line} contains a duplicate candidate term")
            terms.add(term)
    return terms


def load_formula_spans(path: Path) -> dict[str, FormulaSpanIndex]:
    if not path.is_file():
        raise FileNotFoundError(path)
    grouped: dict[str, list[tuple[int, int]]] = {}
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"unit_id", "entity_type", "character_start", "character_end"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("entity mention input missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            if row["entity_type"] != "FORMULA":
                continue
            start, end = int(row["character_start"]), int(row["character_end"])
            if start < 0 or end <= start:
                raise ValueError(f"entity mention row {line}: invalid formula span")
            grouped.setdefault(row["unit_id"], []).append((start, end))
    return {unit_id: FormulaSpanIndex(spans) for unit_id, spans in grouped.items()}


def build(source_path: Path, output_path: Path,
          units_path: Path = Path("catalog/generated/knowledge_units.jsonl.gz"),
          entity_mentions_path: Path | None = None) -> dict[str, int]:
    if not units_path.is_file():
        raise FileNotFoundError(units_path)
    candidate_terms = load_candidate_terms(source_path)
    formula_spans_by_unit = (
        load_formula_spans(entity_mentions_path) if entity_mentions_path is not None else {}
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    classified_terms: set[str] = set()
    units_scanned = 0

    with (
        gzip.open(units_path, "rt", encoding="utf-8", newline="") as source,
        gzip.open(output_path, "wt", encoding="utf-8", newline="") as target,
    ):
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        writer.writeheader()
        for line_number, line in enumerate(source, 1):
            unit = json.loads(line)
            source_info = unit.get("source") or {}
            unit_id = str(unit.get("unit_id") or "")
            text = (unit.get("content") or {}).get("source_text", "")
            if not unit_id or not source_info.get("document") or not source_info.get("sha256"):
                raise ValueError(f"unit line {line_number}: missing source identity")
            if not isinstance(text, str) or not text:
                continue
            units_scanned += 1
            for run in HAN_RUN.finditer(text):
                run_text = run.group(0)
                for length, pattern in NGRAM_PATTERNS.items():
                    if len(run_text) < length:
                        continue
                    for match in pattern.finditer(run_text):
                        term = match.group(1)
                        if term not in candidate_terms:
                            continue
                        start = run.start() + match.start(1)
                        end = start + length
                        classifications = classify_span(
                            text, start, end, formula_spans_by_unit.get(unit_id, ())
                        )
                        if not classifications:
                            continue
                        evidence_start, evidence_end = evidence_window(text, start, end)
                        evidence_text = text[evidence_start:evidence_end]
                        cid = candidate_id(term)
                        for candidate_type, rule_id in classifications:
                            writer.writerow({
                                "candidate_id": cid,
                                "term": term,
                                "candidate_type": candidate_type,
                                "rule_id": rule_id,
                                "evidence_document": source_info["document"],
                                "source_sha256": source_info["sha256"],
                                "tree_position": str(source_info.get("tree_position", "")),
                                "block_id": str(source_info.get("block_id", "")),
                                "unit_id": unit_id,
                                "character_start": start,
                                "character_end": end,
                                "evidence_start": evidence_start,
                                "evidence_text": evidence_text,
                                "classification_status": "CONTEXT_RULE_CANDIDATE",
                            })
                            rows += 1
                            classified_terms.add(term)
            if units_scanned % 25000 == 0:
                print(
                    f"[context-classification] scanned_units={units_scanned} "
                    f"candidate_terms={len(candidate_terms)} typed_occurrences={rows}",
                    file=sys.stderr,
                    flush=True,
                )

    peak_rss_kib = None
    if resource is not None:
        peak_rss_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform == "darwin":
            peak_rss_kib //= 1024
    return {
        "source_units_scanned": units_scanned,
        "candidate_terms_loaded": len(candidate_terms),
        "contextual_classification_candidates": rows,
        "distinct_terms_classified": len(classified_terms),
        "peak_rss_kib": peak_rss_kib,
    }


RULE_IDS_BY_TYPE = {
    candidate_type: {rule_id for rule_id, _ in rules}
    for candidate_type, rules in RULES.items()
}


def validate(path: Path) -> int:
    count = 0
    seen = set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError("context classification output missing fields: " + ", ".join(sorted(missing)))
        for line, row in enumerate(reader, 2):
            if row["classification_status"] != "CONTEXT_RULE_CANDIDATE":
                raise ValueError(f"row {line}: unsafe classification status")
            if (row["candidate_type"] not in RULES
                or row["rule_id"] not in RULE_IDS_BY_TYPE[row["candidate_type"]]):
                raise ValueError(f"row {line}: rule does not belong to candidate type")
            if not all(row[field] for field in (
                "candidate_id", "term", "unit_id", "evidence_document", "source_sha256"
            )):
                raise ValueError(f"row {line}: missing source identity")
            if row["candidate_id"] != candidate_id(row["term"]):
                raise ValueError(f"row {line}: candidate identity does not match term")
            start, end, evidence_start = (
                int(row["character_start"]), int(row["character_end"]), int(row["evidence_start"])
            )
            left, right = start - evidence_start, end - evidence_start
            if (start < 0 or end <= start or evidence_start < 0 or left < 0
                or right > len(row["evidence_text"])
                or row["evidence_text"][left:right] != row["term"]):
                raise ValueError(f"row {line}: term span does not match evidence")
            identity = (
                row["candidate_id"], row["candidate_type"], row["rule_id"],
                row["unit_id"], start, end,
            )
            if identity in seen:
                raise ValueError(f"row {line}: duplicate classification evidence")
            seen.add(identity)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("catalog/generated/unclassified_term_candidates.csv.gz"))
    parser.add_argument("--units", type=Path, default=Path("catalog/generated/knowledge_units.jsonl.gz"))
    parser.add_argument("--output", type=Path, default=Path("catalog/generated/contextual_term_type_candidates.csv.gz"))
    parser.add_argument("--entity-mentions", type=Path, default=Path("catalog/generated/entity_mention_candidates.csv.gz"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    result = {"validated_candidates": validate(args.output)} if args.validate else build(
        args.input, args.output, args.units, args.entity_mentions
    )
    if not args.validate:
        result["validated_candidates"] = validate(args.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
