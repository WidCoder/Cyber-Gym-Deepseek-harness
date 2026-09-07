"""Write a small, secret-free task summary alongside raw harness logs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from harness.trace import find_session, normalize_session, submit_paths


def write_result(
    log_dir: Path,
    *,
    harness: str,
    model: str,
    image: str,
    provider: str,
    api_format: str,
    llm_base_url: str,
    cybergym_server: str,
    status_code: int,
) -> Path:
    args = json.loads((log_dir / "args.json").read_text(encoding="utf-8"))
    timing_path = log_dir / "timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.is_file() else {}
    session = find_session(log_dir / "logs" / "sessions")
    trajectory = log_dir / "trajectory.jsonl"
    stats = {"events": 0, "thinking": 0, "text": 0, "tool_calls": 0, "tool_results": 0, "errors": 0}
    trace_status = "missing"
    trace_error = None
    if session:
        try:
            stats = normalize_session(session, trajectory)
            trace_status = "normalized"
        except Exception as exc:
            trace_status = "error"
            trace_error = str(exc)

    task = args.get("task", {})
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "task": {
            "task_id": task.get("task_id"),
            "agent_id": task.get("agent_id"),
            "difficulty": task.get("difficulty"),
        },
        "agent": {
            "harness": harness,
            "model": model,
            "image": image,
            "provider": provider,
            "api_format": api_format,
        },
        "server": {
            "llm_base_url": llm_base_url,
            "cybergym_server": cybergym_server,
        },
        "execution": {
            "status": "completed" if status_code == 0 else "failed",
            "status_code": status_code,
            "time_cost_sec": timing.get("time_cost_sec"),
        },
        "trajectory": {
            "status": trace_status,
            "raw_console": "console.log",
            "raw_session": str(session.relative_to(log_dir)) if session else None,
            "normalized": "trajectory.jsonl" if trajectory.is_file() else None,
            "error": trace_error,
        },
        "events": stats,
        "actions": {
            "submit_count": len(submit_paths(log_dir / "console.log")),
            "submitted_pocs": submit_paths(log_dir / "console.log"),
        },
        "verification": {"status": "pending"},
        "generated_at": time.time(),
    }
    output = log_dir / "result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
