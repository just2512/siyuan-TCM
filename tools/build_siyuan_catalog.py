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
        if current_type == "NodeKramdownSpanIAL":
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

def extract_title(data: Any, fallback: str) -> str:
    properties = data.get("Properties", {}) if isinstance(data, dict) else {}
    title = properties.get("title", "") if isinstance(properties, dict) else ""
    title = str(title).strip()
    if title and title.lower() not in GENERIC_TITLES:
        return title
    # A large portion of this corpus uses the generic document title "笔记".
    # Use the first visible text line as a navigational fallback, not as a verified title.
    first_line = next((line.strip() for line in extract_text(data).splitlines() if line.strip()), "")
    return first_line[:100] if first_line else fallback

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
        title, text, status = extract_title(data, path.stem), extract_text(data), "PARSED"
    except (UnicodeDecodeError, json.JSONDecodeError):
        title, text, status = path.stem, raw.decode("utf-8", errors="replace"), "RAW_FALLBACK"
    refs = sorted({m.rstrip(TRAILING) for m in ASSET_RE.findall(raw.decode("utf-8", errors="ignore"))})
    return {
        "path": rel, "notebook_id": notebook_id,
        "notebook": notebook_map.get(notebook_id, notebook_id),
        "title": title, "topics": ";".join(classify(title, text)),
        "parse_status": status, "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "asset_ref_count": len(refs), "asset_refs": refs,
        "search_text": re.sub(r"\s+", " ", text)[:2000],
    }

def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ";".join(v) if isinstance(v, list) else v for k, v in row.items()})

def build(root: Path, output: Path, assets_dir: Path | None, notebook_map: dict[str, str]):
    files = sorted(p for p in root.rglob("*.sy") if p.is_file() and "assets" not in p.parts)
    docs = [parse_document(p, root, notebook_map) for p in files]
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "documents.csv", docs, [
        "path", "notebook_id", "notebook", "title", "topics", "parse_status",
        "bytes", "sha256", "asset_ref_count", "search_text"])
    topic_rows = [{"topic": topic, "title": d["title"], "path": d["path"], "notebook": d["notebook"]}
                  for d in docs for topic in d["topics"].split(";")]
    write_csv(output / "topic_index.csv", topic_rows, ["topic", "title", "path", "notebook"])
    asset_rows = []
    for d in docs:
        for ref in d["asset_refs"]:
            relref = ref.replace("\\", "/").removeprefix("../").removeprefix("/")
            candidates = [assets_dir / relref, assets_dir / Path(relref).name] if assets_dir else []
            found = next((p for p in candidates if p.is_file()), None)
            asset_rows.append({"document": d["path"], "title": d["title"], "reference": ref,
                               "local_status": "FOUND" if found else ("NOT_CHECKED" if not assets_dir else "MISSING"),
                               "local_path": str(found) if found else ""})
    write_csv(output / "asset_references.csv", asset_rows,
              ["document", "title", "reference", "local_status", "local_path"])
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
        f"- 扫描根目录：{root}", f"- .sy 文档数：{len(docs)}",
        f"- 解析状态：{dict(statuses)}", f"- 完全相同文件内容组：{len(duplicates)}",
        f"- 附件引用条目：{len(asset_rows)}",
        f"- 附件目录：{'已检查 ' + str(assets_dir) if assets_dir else '未提供，只有引用清单'}",
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
              "- asset_references.csv：文档引用的 assets 路径及本地映射状态。",
              "- catalog.md：本概况报告。", "",
              "## 使用边界", "",
              "- 仓库 .gitignore 排除了 assets/。未提供附件目录时，附件状态为 NOT_CHECKED，不代表附件缺失。",
              "- 使用 --assets-dir 指向本地附件目录进行映射；脚本不会复制或上传附件。",
              "- 使用 --notebook-map 提供目录 ID 到笔记本显示名的 JSON 映射。",
              "- 自动主题标签仅用于检索导航，须人工复核，不能作为辨证、处方或临床决策规则。",
              "- 索引生成不改变原始资料的版权、授权及使用限制。", ""]
    (output / "catalog.md").write_text("\n".join(lines), encoding="utf-8")
    audit = ["# 附件引用审计", "", f"- 引用条目：{len(asset_rows)}",
             f"- 已找到：{sum(x['local_status']=='FOUND' for x in asset_rows)}",
             f"- 未找到：{sum(x['local_status']=='MISSING' for x in asset_rows)}",
             f"- 未检查：{sum(x['local_status']=='NOT_CHECKED' for x in asset_rows)}",
             "", "详细记录见 asset_references.csv。未提供 --assets-dir 时不对附件是否存在作判断。", ""]
    (output / "asset_audit.md").write_text("\n".join(audit), encoding="utf-8")
    return {"documents": len(docs), "asset_references": len(asset_rows),
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
