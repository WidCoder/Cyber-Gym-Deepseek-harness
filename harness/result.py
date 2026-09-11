"""Write a small, secret-free task summary alongside raw harness logs."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any

from harness.capture import summarize_captures, write_capture_manifest
from harness.trace import find_session, normalize_opencode_console, normalize_session, submit_paths


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
    workspace_dir: Path | None = None,
) -> Path:
    args = json.loads((log_dir / "args.json").read_text(encoding="utf-8"))
    timing_path = log_dir / "timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.is_file() else {}
    session = find_session(log_dir / "logs" / "sessions")
    console = log_dir / "console.log"
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
    elif console.is_file():
        try:
            stats = normalize_opencode_console(console, trajectory)
            trace_status = "normalized"
        except Exception as exc:
            trace_status = "error"
            trace_error = str(exc)

    task = args.get("task", {})
    submitted = submit_paths(console)
    artifacts: list[dict[str, Any]] = []
    artifact_dir = log_dir / "artifacts"
    if workspace_dir is not None:
        for submitted_path in submitted:
            relative = submitted_path
            if relative.startswith("/workspace/"):
                relative = relative[len("/workspace/") :]
            source = workspace_dir / relative if not Path(relative).is_absolute() else Path(relative)
            if not source.is_file():
                continue
            target = artifact_dir / Path(relative).name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            artifacts.append({
                "source": submitted_path,
                "file": str(target.relative_to(log_dir)),
                "sha256": digest,
                "size_bytes": target.stat().st_size,
            })
    capture_summary = summarize_captures(
        None,
        start_time=timing.get("start_time"),
        end_time=timing.get("end_time"),
    )
    manifest_path = log_dir / "capture_manifest.json"
    output = log_dir / "result.json"
    result: dict[str, Any] = {
        "schema_version": "cybergym-agent-v1",
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
            "agent_kind": os.getenv("CYBERGYM_AGENT_KIND", "main"),
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
            "submit_count": len(submitted),
            "submitted_pocs": submitted,
            "artifacts": artifacts,
        },
        "verification": {
            "status": "unknown",
            "flag_found": False,
            "checker": None,
        },
        "api_capture": {
            **capture_summary,
            "manifest": str(manifest_path),
        },
        "provenance": {
            "task_log_dir": str(log_dir),
            "capture_manifest": str(manifest_path),
            "harness_logs": {
                "args": str(log_dir / "args.json"),
                "timing": str(timing_path),
                "console": str(console),
                "trajectory": str(trajectory),
                "result": str(output),
            },
        },
        "generated_at": time.time(),
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    capture_root_value = capture_summary.get("directory")
    capture_root = Path(capture_root_value) if isinstance(capture_root_value, str) else None
    write_capture_manifest(
        capture_root,
        log_dir,
        task_id=task.get("task_id"),
        agent_id=task.get("agent_id"),
        start_time=timing.get("start_time"),
        end_time=timing.get("end_time"),
    )
    return output
