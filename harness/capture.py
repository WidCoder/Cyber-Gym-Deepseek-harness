"""Summarize request/response captures without exposing API credentials."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def summarize_captures(
    capture_dir: Path | None,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
) -> dict[str, Any]:
    """Return task-window capture metadata; never include request headers/bodies."""
    root = capture_dir
    if root is None:
        configured = os.getenv("CAPTURE_LOG_DIR")
        root = Path(configured) if configured else None
    completed = root / "raw" / "completed" if root else None
    result: dict[str, Any] = {
        "status": "disabled" if completed is None else "missing",
        "directory": str(root) if root else None,
        "request_count": 0,
        "complete_count": 0,
        "partial_count": 0,
        "capture_ids": [],
    }
    if completed is None or not completed.is_dir():
        return result

    result["status"] = "captured"
    for item in sorted(completed.iterdir()):
        if not item.is_dir():
            continue
        request = _read(item / "request.json") or {}
        response = _read(item / "response.json") or {}
        request_time = _timestamp(request.get("captured_at"))
        response_time = _timestamp(response.get("finished_at"))
        probe_time = response_time or request_time or item.stat().st_mtime
        if start_time is not None and probe_time < start_time - 1:
            continue
        if end_time is not None and request_time is not None and request_time > end_time + 1:
            continue
        result["request_count"] += 1
        result["capture_ids"].append(item.name)
        state = (_read(item / "state.json") or {}).get("state")
        if state == "complete":
            result["complete_count"] += 1
        else:
            result["partial_count"] += 1
    return result
