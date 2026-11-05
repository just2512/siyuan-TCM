#!/usr/bin/env python3
"""Build a searchable catalogue for a local SiYuan TCM repository checkout.

The repository excludes assets/. Pass --assets-dir to audit a separately stored
attachment directory without copying it into Git. Python standard library only.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TOPICS = {
    "经典与理论": ["黄帝内经", "素问", "灵枢", "阴阳", "五行", "藏象", "经络", "运气"],
    "伤寒与温病": ["伤寒论", "金匮要略", "六经", "少阳", "太阳病", "阳明病", "太阴病", "少阴病", "厥阴病", "温病"],
    "方剂与用药": ["方剂", "经方", "药方", "处方", "剂量", "配伍", "加减", "煎服", "药性", "用药"],
    "中药与本草": ["本草", "中草药", "药材", "药图", "神农本草经", "性味", "归经"],
    "针灸与经穴": ["针灸", "穴位", "经穴", "艾灸", "刺法", "针法"],
    "诊断与辨证": ["望诊", "闻诊", "问诊", "切诊", "脉诊", "舌诊", "辨证", "合病", "并病"],
    "医家与课程": ["倪海厦", "谭杰中", "jt叔叔", "梁冬", "医案", "讲座", "课程"],
}
ASSET_RE = re.compile(r"""(?:\.\./|/)?assets/[^\s"'<>\\)]+""", re.IGNORECASE)
TRAILING = ".,;:!?，。；：！？)]}）】》、"
GENERIC_TITLES = {"", "笔记", "无标题", "untitled"}

def extract_text(data: Any) -> str:
    """Extract visible SiYuan block text, excluding Properties and Kramdown IAL."""
    parts = []

    def visit(node: Any, node_type: str = "") -> None:
        if isinstance(node, list):
            for child in node:
                visit(child, node_type)
            return
        if not isinstance(node, dict):
            return
        current_type = str(node.get("Type", node_type))
        if "IAL" in current_type:
            return
        for key, value in node.items():
            if key == "TextMarkTextContent" and isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif key == "Data" and isinstance(value, str) and value.strip():
                parts.append(value.strip())
            elif key == "Children":
                visit(value, current_type)
            elif key not in {"Properties", "IAL", "Type", "ID", "Spec"}:
                if isinstance(value, (dict, list)):
                    visit(value, current_type)

    visit(data)
    return "\n".join(parts)

def collect_child_node_types(data: Any) -> dict[str, int]:
    """Count typed nodes below the document root without reading metadata."""
    counts: dict[str, int] = {}

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        node_type = node.get("Type")
        if isinstance(node_type, str) and node_type:
            counts[node_type] = counts.get(node_type, 0) + 1
        for key, value in node.items():
            if key not in {"Properties", "IAL"} and isinstance(value, (dict, list)):
                visit(value)

    if isinstance(data, dict):
        visit(data.get("Children", []))
    return counts

def extract_title_with_source(data: Any, fallback: str) -> tuple[str, str]:
    properties = data.get("Properties", {}) if isinstance(data, dict) else {}
    title = properties.get("title", "") if isinstance(properties, dict) else ""
    title = str(title).strip()
    if title and title.lower() not in GENERIC_TITLES:
        return title, "PROPERTY"
    # First visible line is a navigational fallback, not a verified title.
    first_line = next((line.strip() for line in extract_text(data).splitlines() if line.strip()), "")
    if first_line:
        return first_line[:100], "BODY_FIRST_LINE"
    return fallback, "FILENAME"

def extract_title(data: Any, fallback: str) -> str:
    """Backward-compatible title-only helper."""
    return extract_title_with_source(data, fallback)[0]

def classify(title: str, text: str) -> list[str]:
    haystack = (title + "\n" + text).lower()
    found = [topic for topic, terms in TOPICS.items()
             if any(term.lower() in haystack for term in terms)]
    return found or ["其他与待归类"]

def load_notebook_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("notebook-map JSON 必须是 {目录ID: 显示名称} 对象")
    return {str(k): str(v) for k, v in data.items()}

def parse_document(path: Path, root: Path, notebook_map: dict[str, str]) -> dict[str, Any]:
    raw = path.read_bytes()
    rel = path.relative_to(root).as_posix()
    notebook_id = path.relative_to(root).parts[0] if len(path.relative_to(root).parts) > 1 else "ROOT"
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        title, title_source = extract_title_with_source(data, path.stem)
        text, status = extract_text(data), "PARSED"
    except (UnicodeDecodeError, json.JSONDecodeError):
        title, title_source = path.stem, "RAW_FILENAME"
        text, status = raw.decode("utf-8", errors="replace"), "RAW_FALLBACK"
    refs = sorted({m.rstrip(TRAILING) for m in ASSET_RE.findall(raw.decode("utf-8", errors="ignore"))})
    node_type_counts = collect_child_node_types(data) if status == "PARSED" else {}
    properties = data.get("Properties", {}) if status == "PARSED" and isinstance(data, dict) else {}
    properties_fields = sorted(
        str(key) for key, value in properties.items()
        if str(key) and value is not None and value != "" and value != [] and value != {}
    ) if isinstance(properties, dict) else []
    title_text = title.lower()
    body_text = text.lower()
    title_topic_matched_terms = ";".join(
        f"{topic}:{'、'.join(term for term in terms if term.lower() in title_text)}"
        for topic, terms in TOPICS.items()
        if any(term.lower() in title_text for term in terms)
    )
    body_topic_matched_terms = ";".join(
        f"{topic}:{'、'.join(term for term in terms if term.lower() in body_text)}"
        for topic, terms in TOPICS.items()
        if any(term.lower() in body_text for term in terms)
    )
    topic_matched_terms = ";".join(
        item for item in (title_topic_matched_terms, body_topic_matched_terms) if item
    )
    return {
        "path": rel, "notebook_id": notebook_id,
        "notebook": notebook_map.get(notebook_id, notebook_id),
        "title": title, "title_source": title_source, "topics": ";".join(classify(title, text)),
        "parse_status": status, "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "asset_ref_count": len(refs), "asset_refs": refs,
        "node_types": ";".join(f"{name}:{count}" for name, count in sorted(node_type_counts.items())),
        "child_node_count": sum(node_type_counts.values()),
        "properties_fields": properties_fields,
        "topic_matched_terms": topic_matched_terms,
        "title_topic_matched_terms": title_topic_matched_terms,
        "body_topic_matched_terms": body_topic_matched_terms,
        "search_text": re.sub(r"\s+", " ", text)[:2000],
    }

def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ";".join(v) if isinstance(v, list) else v for k, v in row.items()})

def build_asset_lookup(assets_dir: Path) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    exact: dict[str, Path] = {}
    by_name: dict[str, list[Path]] = defaultdict(list)
    root = assets_dir.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            continue
        relative = resolved.relative_to(root).as_posix()
        exact[relative] = resolved
        by_name[path.name].append(resolved)
    return exact, by_name


def resolve_asset_reference(reference: str, assets_dir: Path | None,
                            lookup: tuple[dict[str, Path], dict[str, list[Path]]] | None = None
                            ) -> tuple[str, str, str]:
    if assets_dir is None:
        return "NOT_CHECKED", "", "NOT_CHECKED"
    raw = reference.replace("\\", "/")
    # SiYuan exports commonly use either assets/... or ../assets/... .
    # Accept only those explicit prefixes; never normalize away arbitrary
    # parent-directory segments because that can turn traversal into a valid path.
    if raw.startswith("../assets/"):
        normalized = raw[len("../assets/"):]
    elif raw.startswith("assets/"):
        normalized = raw[len("assets/"):]
    else:
        return "INVALID_REFERENCE", "", "UNSAFE_OR_UNSUPPORTED_PREFIX"
    parts = Path(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return "INVALID_REFERENCE", "", "UNSAFE_OR_EMPTY_PATH"
    normalized = Path(*parts).as_posix()
    exact, by_name = lookup or build_asset_lookup(assets_dir)
    if normalized in exact:
        return "FOUND", f"assets/{normalized}", "EXACT_RELATIVE_PATH"
    matches = by_name.get(Path(normalized).name, [])
    if len(matches) == 1:
        return "FOUND_BY_UNIQUE_BASENAME", f"assets/{matches[0].relative_to(assets_dir.resolve()).as_posix()}", "UNIQUE_BASENAME_FALLBACK"
    if len(matches) > 1:
        return "AMBIGUOUS", "", "DUPLICATE_BASENAME"
    return "MISSING", "", "NO_MATCH"



def build_asset_prefix_candidates(
    asset_rows: list[dict[str, str]],
    assets_dir: Path | None,
    lookup: tuple[dict[str, Path], dict[str, list[Path]]] | None,
) -> list[dict[str, str]]:
    """List possible filename-prefix/extension candidates without auto-matching."""
    if assets_dir is None or lookup is None:
        return []
    exact, _ = lookup
    all_paths = sorted(set(exact.values()), key=lambda path: path.as_posix().casefold())
    grouped: dict[str, dict[str, Any]] = {}
    for row in asset_rows:
        if row.get("local_status") != "MISSING":
            continue
        reference = str(row.get("reference", ""))
        group = grouped.setdefault(reference, {
            "documents": [], "titles": [],
        })
        group["documents"].append(str(row.get("document", "")))
        group["titles"].append(str(row.get("title", "")))

    result = []
    root = assets_dir.resolve()
    for reference, group in sorted(grouped.items()):
        basename = reference.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = Path(basename).suffix
        if suffix:
            candidate_class = "IMAGE_REFERENCE" if suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"} else "EXTENSIONED_REFERENCE"
            stem = Path(basename).stem
            matches = [
                path for path in all_paths
                if path.name == basename or (path.stem == stem and path.name != basename)
            ]
        else:
            candidate_class = "NO_EXTENSION_REFERENCE"
            stem = basename
            matches = [
                path for path in all_paths
                if path.name.startswith((stem + "-", stem + "_", stem + "."))
            ]
        candidate_paths = sorted({
            "assets/" + path.relative_to(root).as_posix()
            for path in matches if path.resolve().is_relative_to(root)
        })
        count = len(candidate_paths)
        if count == 0:
            candidate_status = "NO_CANDIDATE"
        elif count == 1:
            candidate_status = "ONE_CANDIDATE"
        else:
            candidate_status = "MULTIPLE_CANDIDATES"
        result.append({
            "reference": reference,
            "candidate_class": candidate_class,
            "occurrence_count": str(len(group["documents"])),
            "candidate_status": candidate_status,
            "candidate_count": str(count),
            "candidate_paths": ";".join(candidate_paths),
            "document_paths": ";".join(sorted(set(group["documents"]))),
            "titles": ";".join(sorted(set(group["titles"]))),
            "candidate_basis": "ASSETS_DIRECTORY_FILENAME_ONLY_NOT_CONTENT_VERIFIED",
            "manual_status": "NEEDS_INSPECTION",
            "manual_note": "",
        })
    return result

def attach_document_hierarchy(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive parent/child links from SiYuan's nested export directory layout."""
    by_path = {str(doc["path"]): doc for doc in docs}
    children: dict[str, list[str]] = defaultdict(list)
    for doc in docs:
        parts = Path(str(doc["path"])).parts
        parent = ""
        if len(parts) >= 3:
            candidate = Path(*parts[:-2], parts[-2] + ".sy").as_posix()
            if candidate in by_path:
                parent = candidate
        doc["parent_document"] = parent
        if parent:
            children[parent].append(str(doc["path"]))

    def depth(path: str, seen: set[str] | None = None) -> int:
        seen = set() if seen is None else seen
        if path in seen:
            raise ValueError(f"思源文档父子关系出现循环：{path}")
        parent = str(by_path[path].get("parent_document", ""))
        return 0 if not parent else 1 + depth(parent, seen | {path})

    for doc in docs:
        path = str(doc["path"])
        doc["document_depth"] = depth(path)
        doc["child_document_count"] = len(children.get(path, []))
    return docs


def build(root: Path, output: Path, assets_dir: Path | None, notebook_map: dict[str, str]):
    files = sorted(p for p in root.rglob("*.sy") if p.is_file() and "assets" not in p.parts)
    docs = attach_document_hierarchy([parse_document(p, root, notebook_map) for p in files])
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "documents.csv", docs, [
        "path", "notebook_id", "notebook", "title", "title_source", "topics", "parse_status",
        "bytes", "sha256", "asset_ref_count", "node_types", "child_node_count",
        "properties_fields", "topic_matched_terms", "title_topic_matched_terms",
        "body_topic_matched_terms", "parent_document", "document_depth",
        "child_document_count", "search_text"])
    topic_rows = [{"topic": topic, "title": d["title"], "path": d["path"], "notebook": d["notebook"]}
                  for d in docs for topic in d["topics"].split(";")]
    property_field_counts = Counter(
        field for doc in docs for field in doc.get("properties_fields", [])
    )
    metadata_rows = [
        {"property_field": field, "document_count": count}
        for field, count in sorted(property_field_counts.items())
    ]
    write_csv(output / "metadata_inventory.csv", metadata_rows,
              ["property_field", "document_count"])
    hierarchy_rows = [{
        "document": d["path"], "parent_document": d["parent_document"],
        "notebook": d["notebook"], "title": d["title"],
        "document_depth": d["document_depth"],
        "child_document_count": d["child_document_count"],
        "structure_role": "CONTAINER" if d["child_document_count"] else "LEAF",
    } for d in docs]
    write_csv(output / "document_hierarchy.csv", hierarchy_rows, [
        "document", "parent_document", "notebook", "title", "document_depth",
        "child_document_count", "structure_role",
    ])
    write_csv(output / "topic_index.csv", topic_rows, ["topic", "title", "path", "notebook"])
    asset_rows = []
    asset_lookup = build_asset_lookup(assets_dir) if assets_dir else None
    for d in docs:
        for ref in d["asset_refs"]:
            local_status, local_path, match_method = resolve_asset_reference(
                ref, assets_dir, asset_lookup
            )
            asset_rows.append({
                "document": d["path"], "title": d["title"], "reference": ref,
                "local_status": local_status, "local_path": local_path,
                "match_method": match_method,
            })
    write_csv(output / "asset_references.csv", asset_rows,
              ["document", "title", "reference", "local_status", "local_path", "match_method"])
    prefix_candidates = build_asset_prefix_candidates(asset_rows, assets_dir, asset_lookup)
    write_csv(output / "asset_prefix_candidates.csv", prefix_candidates, [
        "reference", "candidate_class", "occurrence_count", "candidate_status",
        "candidate_count", "candidate_paths", "document_paths", "titles",
        "candidate_basis", "manual_status", "manual_note",
    ])
    notebooks = Counter(d["notebook"] for d in docs)
    topics = Counter(row["topic"] for row in topic_rows)
    statuses = Counter(d["parse_status"] for d in docs)
    hashes = defaultdict(list)
    for d in docs:
        hashes[d["sha256"]].append(d["path"])
    duplicates = [v for v in hashes.values() if len(v) > 1]
    lines = [
        "# 思源中医资料自动索引", "",
        "> 本文件由 tools/build_siyuan_catalog.py 生成。主题分类是关键词机器初筛，不代表医学语义审核或内容校勘。", "",
        "## 扫描概况", "",
        "- 扫描根目录：本机输入目录（绝对路径不写入报告）", f"- .sy 文档数：{len(docs)}",
        f"- 解析状态：{dict(statuses)}", f"- 完全相同文件内容组：{len(duplicates)}",
        f"- 附件引用条目：{len(asset_rows)}",
        f"- 附件目录：{'已提供并完成本地映射（绝对路径不写入报告）' if assets_dir else '未提供，只有引用清单'}",
        "", "## 按笔记本", "", "| 笔记本/目录 | 文档数 |", "|---|---:|"
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(notebooks.items()))
    lines += ["", "## 按主题（关键词初筛）", "", "| 主题 | 文档条目数 |", "|---|---:|"]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(topics.items()))
    lines += ["", "## 完全重复文件", "", "按原始文件 SHA-256 完全一致识别；相似或改写内容不在此列。", ""]
    lines.extend("- " + "；".join(v) for v in duplicates) if duplicates else lines.append("- 未发现完全相同的 .sy 文件。")
    lines += ["", "## 输出文件", "",
              "- documents.csv：逐篇文件清单、标题、目录、主题标签、解析状态、哈希及正文检索片段。",
              "- topic_index.csv：按主题展开的文档索引。",
              "- metadata_inventory.csv：Properties 中非空字段的文档覆盖数；不导出字段值。",
              "- asset_references.csv：文档引用的 assets 路径及本地映射状态。",
              "- asset_prefix_candidates.csv：未匹配引用的本地文件名候选，仅供人工核验，不自动认定为匹配。",
              "- catalog.md：本概况报告。", "",
              "## 使用边界", "",
              "- 仓库 .gitignore 排除了 assets/。未提供附件目录时，附件状态为 NOT_CHECKED，不代表附件缺失。",
              "- 使用 --assets-dir 指向本地附件目录进行映射；脚本不会复制或上传附件。",
              "- 使用 --notebook-map 提供目录 ID 到笔记本显示名的 JSON 映射。",
              "- 自动主题标签仅用于检索导航，须人工复核，不能作为辨证、处方或临床决策规则。",
              "- 索引生成不改变原始资料的版权、授权及使用限制。", ""]
    (output / "catalog.md").write_text("\n".join(lines), encoding="utf-8")
    prefix_counts = Counter(row["candidate_status"] for row in prefix_candidates)
    prefix_audit = (
        [
            "- 候选扫描状态：COMPLETED",
            f"- 未匹配引用唯一项：{len(prefix_candidates)}",
            f"- 文件名候选唯一命中：{prefix_counts.get('ONE_CANDIDATE', 0)}",
            f"- 文件名候选多重命中：{prefix_counts.get('MULTIPLE_CANDIDATES', 0)}",
            f"- 文件名无候选：{prefix_counts.get('NO_CANDIDATE', 0)}",
        ]
        if assets_dir
        else [
            "- 候选扫描状态：NOT_RUN（未提供 --assets-dir）",
            "- 未匹配引用唯一项：未执行本地映射，不能统计",
            "- 文件名候选：未执行本地扫描",
        ]
    )
    audit = ["# 附件引用审计", "", f"- 引用条目：{len(asset_rows)}",
             f"- 本地附件目录：{'已提供' if assets_dir else '未提供'}",
             *prefix_audit,
             f"- 精确路径找到：{sum(x['local_status']=='FOUND' for x in asset_rows)}",
             f"- 唯一文件名回退找到：{sum(x['local_status']=='FOUND_BY_UNIQUE_BASENAME' for x in asset_rows)}",
             f"- 文件名冲突待处理：{sum(x['local_status']=='AMBIGUOUS' for x in asset_rows)}",
             f"- 未找到：{sum(x['local_status']=='MISSING' for x in asset_rows)}",
             f"- 非法引用路径：{sum(x['local_status']=='INVALID_REFERENCE' for x in asset_rows)}",
             f"- 未检查：{sum(x['local_status']=='NOT_CHECKED' for x in asset_rows)}",
             "", "详细记录见 asset_references.csv。未提供 --assets-dir 时不对附件是否存在作判断。", ""]
    (output / "asset_audit.md").write_text("\n".join(audit), encoding="utf-8")
    return {"documents": len(docs), "asset_references": len(asset_rows),
            "asset_scan_performed": assets_dir is not None,
            "asset_prefix_candidates": len(prefix_candidates),
            "duplicate_groups": len(duplicates), "output": str(output)}

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                   help="思源 data 目录或包含笔记本目录的仓库根目录")
    p.add_argument("--output", type=Path, default=None, help="默认 <root>/catalog/generated")
    p.add_argument("--assets-dir", type=Path, default=None, help="本地 assets 目录，可位于仓库外")
    p.add_argument("--notebook-map", type=Path, default=None, help="目录 ID 到笔记本名称的 JSON 文件")
    args = p.parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        p.error(f"扫描根目录不存在或不是目录：{root}")
    output = (args.output or root / "catalog" / "generated").expanduser().resolve()
    assets = args.assets_dir.expanduser().resolve() if args.assets_dir else None
    if assets and not assets.is_dir():
        p.error(f"assets 目录不存在：{assets}")
    default_map = Path(__file__).resolve().parents[1] / "catalog" / "notebook-map.json"
    map_path = args.notebook_map or (default_map if default_map.is_file() else None)
    try:
        result = build(root, output, assets, load_notebook_map(map_path))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
