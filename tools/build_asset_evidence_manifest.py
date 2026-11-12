#!/usr/bin/env python3
"""Build a local-only SHA-256 manifest for asset review candidates.

The manifest proves only that a candidate file exists at a safe path and records
its byte-level fingerprint. It never confirms that the file depicts or contains
the referenced material.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path, PurePosixPath

REQUIRED_FIELDS = {"reference", "candidate_status", "candidate_count", "candidate_paths"}
OUTPUT_FIELDS = [
    "reference", "candidate_path", "file_status", "file_size_bytes",
    "sha256", "suffix", "resolved_relative_path", "evidence_scope",
]


def read_queue(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"附件复核队列缺少字段：{', '.join(sorted(missing))}")
        rows = list(reader)
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        reference = (row.get("reference") or "").strip()
        if not reference or reference in seen:
            raise ValueError(f"附件复核队列第 {line} 行 reference 为空或重复：{reference}")
        seen.add(reference)
        paths = [item for item in (row.get("candidate_paths") or "").split(";") if item]
        try:
            count = int(row.get("candidate_count", ""))
        except ValueError as exc:
            raise ValueError(f"{reference} 的 candidate_count 不是整数") from exc
        expected = "NO_CANDIDATE" if count == 0 else "ONE_CANDIDATE" if count == 1 else "MULTIPLE_CANDIDATES"
        if count < 0 or count != len(paths) or row.get("candidate_status") != expected:
            raise ValueError(f"{reference} 的候选数量、路径和状态不一致")
    return rows


def safe_candidate_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or path.parts[0] != "assets":
        raise ValueError(f"候选路径必须是 assets/ 下的相对路径：{value}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"候选路径包含非法路径段：{value}")
    return PurePosixPath(*path.parts[1:])


def fingerprint(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return path.stat().st_size, digest.hexdigest()


def build_manifest(rows: list[dict[str, str]], assets_dir: Path, output: Path) -> dict[str, int]:
    root = assets_dir.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"assets 根路径不是目录：{assets_dir}")
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str]] = []
    cache: dict[str, tuple[str, str, str]] = {}
    counts = {"references": len(rows), "candidate_files": 0, "present": 0, "missing": 0, "unsafe": 0, "no_candidate": 0}

    for row in rows:
        candidates = [item for item in (row.get("candidate_paths") or "").split(";") if item]
        if not candidates:
            records.append({
                "reference": row["reference"], "candidate_path": "", "file_status": "NO_CANDIDATE",
                "file_size_bytes": "", "sha256": "", "suffix": "",
                "resolved_relative_path": "", "evidence_scope": "NO_FILE_CANDIDATE_FOUND",
            })
            counts["no_candidate"] += 1
            continue

        for candidate in candidates:
            counts["candidate_files"] += 1
            try:
                relative = safe_candidate_path(candidate)
                target = root.joinpath(*relative.parts)
                resolved = target.resolve(strict=False)
                if not resolved.is_relative_to(root):
                    raise ValueError("候选路径解析后越过 assets 根目录")
            except (ValueError, OSError):
                records.append({
                    "reference": row["reference"], "candidate_path": candidate, "file_status": "UNSAFE_PATH",
                    "file_size_bytes": "", "sha256": "", "suffix": Path(candidate).suffix.lower(),
                    "resolved_relative_path": "", "evidence_scope": "PATH_REJECTED_NO_CONTENT_CHECK",
                })
                counts["unsafe"] += 1
                continue

            key = str(resolved)
            if key not in cache:
                if not resolved.is_file():
                    cache[key] = ("MISSING", "", "")
                else:
                    size, digest = fingerprint(resolved)
                    cache[key] = ("PRESENT", str(size), digest)
            status, size, digest = cache[key]
            counts["present" if status == "PRESENT" else "missing"] += 1
            records.append({
                "reference": row["reference"], "candidate_path": candidate,
                "file_status": status, "file_size_bytes": size, "sha256": digest,
                "suffix": resolved.suffix.lower(),
                "resolved_relative_path": resolved.relative_to(root).as_posix() if status == "PRESENT" else "",
                "evidence_scope": "BYTE_FINGERPRINT_ONLY_CONTENT_AND_REFERENCE_UNVERIFIED",
            })

    with (output / "asset_evidence_manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(records)

    report = [
        "# 本地附件文件指纹清单",
        "",
        f"- 引用数：{counts['references']}",
        f"- 候选文件记录数：{counts['candidate_files']}",
        f"- 文件存在：{counts['present']}",
        f"- 文件不存在：{counts['missing']}",
        f"- 安全路径拒绝：{counts['unsafe']}",
        f"- 无候选引用：{counts['no_candidate']}",
        "",
        "## 证据边界",
        "",
        "- PRESENT 仅表示文件在指定 assets 根目录下存在，并记录字节数与 SHA-256。",
        "- SHA-256 用于识别字节完全相同的文件，不证明文件内容、版本、出处或与思源引用的语义关系。",
        "- MISSING 仅表示该候选相对路径在本次扫描根目录下不存在；不证明原始附件已丢失。",
        "- UNSAFE_PATH 表示路径不符合 assets/ 相对路径约束或解析后越过根目录，未读取文件。",
        "- 不会将任何 NEEDS_INSPECTION 自动改为 CONFIRMED_MATCH，也不会改动来源核验状态。",
        "",
        "详细结果见 `asset_evidence_manifest.csv`。",
        "",
    ]
    (output / "asset_evidence_manifest.md").write_text("\n".join(report), encoding="utf-8")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True, help="generated/asset_review_queue.csv")
    parser.add_argument("--assets-dir", type=Path, required=True, help="用户本地 assets 目录")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build_manifest(read_queue(args.queue), args.assets_dir, args.output))


if __name__ == "__main__":
    main()
