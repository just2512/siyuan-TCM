"""Shared writer for machine-readable SQLite source-audit reports."""
from __future__ import annotations

import json
from pathlib import Path


def write_audit_report(path: Path, result: dict) -> None:
    payload = {"schema_version": 1, **result}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
