"""Finalize request captures into task-level multi-turn JSONL samples.

The online proxy deliberately stores one request/response pair per capture.
This command is the offline second stage: it reads each task's capture
manifest, rejects incomplete or failed responses, and joins consecutive
requests when the next request contains the previous conversation as a
prefix.  It never changes the Harness execution or verification result.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.export_training_data import (  # noqa: E402
    _assistant_message,
    _body,
    _dataset,
    _sample_id,
    _training_messages,
)


@dataclass(frozen=True)
class CaptureRound:
    capture_id: str
    capture_dir: Path
    request: dict[str, Any]
    response: dict[str, Any]
    state: dict[str, Any]
    request_body: dict[str, Any]
    history: list[dict[str, Any]]
    assistant: dict[str, Any]


@dataclass(frozen=True)
class TaskInput:
    result_path: Path
    result: dict[str, Any]
    manifest_path: Path
    captures: tuple[CaptureRound, ...]

    @property
    def task_id(self) -> str:
        task = self.result.get("task")
        task = task if isinstance(task, dict) else {}
        value = task.get("task_id")
        return str(value) if value else "unknown"

    @property
    def agent_id(self) -> str:
        task = self.result.get("task")
        task = task if isinstance(task, dict) else {}
        value = task.get("agent_id")
        return str(value) if value else "unknown"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _read_object(path: Path) -> dict[str, Any] | None:
    value = _read_json(path)
    return value if isinstance(value, dict) else None


def _resolve_path(value: Any, base: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else base / path


def _timestamp(value: Any) -> float:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0.0


def _slug(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-_.") or "unknown"


def _manifest_path(result_path: Path, result: dict[str, Any]) -> Path | None:
    provenance = result.get("provenance")
    if isinstance(provenance, dict):
        path = _resolve_path(provenance.get("capture_manifest"), result_path.parent)
        if path is not None:
            return path
    capture = result.get("api_capture")
    if isinstance(capture, dict):
        path = _resolve_path(capture.get("manifest"), result_path.parent)
        if path is not None:
            return path
    fallback = result_path.parent / "capture_manifest.json"
    return fallback if fallback.is_file() else None


def _capture_paths(entry: dict[str, Any], manifest_path: Path) -> tuple[Path, Path, Path] | None:
    capture_dir = _resolve_path(entry.get("capture_dir"), manifest_path.parent)
    request_path = _resolve_path(entry.get("request"), manifest_path.parent)
    response_path = _resolve_path(entry.get("response"), manifest_path.parent)
    if capture_dir is None:
        if request_path is None or response_path is None:
            return None
        capture_dir = request_path.parent
    request_path = request_path or capture_dir / "request.json"
    response_path = response_path or capture_dir / "response.json"
    return capture_dir, request_path, response_path


def _load_capture(entry: Any, manifest_path: Path) -> CaptureRound | str:
    if not isinstance(entry, dict):
        return "manifest capture entry is not an object"
    paths = _capture_paths(entry, manifest_path)
    if paths is None:
        return "manifest capture entry has no usable paths"
    capture_dir, request_path, response_path = paths
    request = _read_object(request_path)
    response = _read_object(response_path)
    state = _read_object(capture_dir / "state.json") or {}
    if request is None or response is None:
        return f"missing or invalid request/response JSON: {capture_dir}"
    body = _body(request)
    history = _training_messages(body)
    assistant = _assistant_message(capture_dir, response, body)
    if not history and not isinstance(body.get("messages"), list):
        return f"request has no messages array: {capture_dir}"
    if assistant is None:
        return f"assistant response cannot be reconstructed: {capture_dir}"
    capture_id = str(entry.get("capture_id") or request.get("capture_id") or capture_dir.name)
    return CaptureRound(
        capture_id=capture_id,
        capture_dir=capture_dir,
        request=request,
        response=response,
        state=state,
        request_body=body,
        history=history,
        assistant=assistant,
    )


def _capture_is_usable(
    capture: CaptureRound, *, recover_terminal_sse: bool = False
) -> tuple[bool, str | None]:
    state_complete = capture.state.get("state") == "complete"
    status_code = capture.response.get("status_code")
    if not isinstance(status_code, int) or not 200 <= status_code < 300:
        return False, f"status_code={status_code!r}"
    terminal_event_received = bool(
        capture.response.get("stream_complete")
        or capture.response.get("aggregation_complete")
    )
    if not state_complete and recover_terminal_sse:
        body = capture.capture_dir / "response.body"
        terminal_event_received = terminal_event_received or (
            body.is_file() and b"[DONE]" in body.read_bytes()
        )
        if (
            terminal_event_received
            and not capture.response.get("transport_error")
            and not capture.response.get("client_disconnected")
        ):
            state_complete = True
    if not state_complete:
        return False, f"state={capture.state.get('state')!r}"
    # A client can cancel immediately after receiving [DONE]/message_stop. In
    # that case the proxy records both a transport error and state=complete;
    # the protocol terminal marker is stronger evidence than the late cancel.
    if capture.response.get("transport_error") and not terminal_event_received:
        return False, "transport_error is present"
    if capture.response.get("client_disconnected") and not terminal_event_received:
        return False, "client disconnected before stream completion"
    return True, None


def _load_task(
    result_path: Path, *, recover_terminal_sse: bool = False
) -> tuple[TaskInput | None, str | None]:
    result = _read_object(result_path)
    if result is None:
        return None, "invalid result.json"
    manifest_path = _manifest_path(result_path, result)
    if manifest_path is None or not manifest_path.is_file():
        return None, "capture_manifest.json is missing"
    manifest = _read_object(manifest_path)
    if manifest is None:
        return None, "invalid capture_manifest.json"
    result_task = result.get("task")
    result_task = result_task if isinstance(result_task, dict) else {}
    result_task_id = result_task.get("task_id")
    result_agent_id = result_task.get("agent_id")
    manifest_task_id = manifest.get("task_id")
    manifest_agent_id = manifest.get("agent_id")
    if result_task_id and manifest_task_id and manifest_task_id != result_task_id:
        return None, "capture manifest task_id does not match result.json"
    if result_agent_id and manifest_agent_id and manifest_agent_id != result_agent_id:
        return None, "capture manifest agent_id does not match result.json"
    entries = manifest.get("captures")
    if not isinstance(entries, list) or not entries:
        return None, "capture manifest has no captures"

    captures: list[CaptureRound] = []
    seen_capture_ids: set[str] = set()
    for entry in entries:
        loaded = _load_capture(entry, manifest_path)
        if isinstance(loaded, str):
            return None, loaded
        if loaded.capture_id in seen_capture_ids:
            return None, f"duplicate capture id in manifest: {loaded.capture_id}"
        seen_capture_ids.add(loaded.capture_id)
        usable, reason = _capture_is_usable(
            loaded, recover_terminal_sse=recover_terminal_sse
        )
        if not usable:
            return None, f"capture {loaded.capture_id}: {reason}"
        captures.append(loaded)

    captures.sort(
        key=lambda item: (
            _timestamp(item.request.get("captured_at")),
            _timestamp(item.response.get("finished_at")),
            item.capture_id,
        )
    )
    return TaskInput(result_path, result, manifest_path, tuple(captures)), None


def _tool_map(tools: Any) -> dict[str, Any] | None:
    if tools is None:
        return {}
    if not isinstance(tools, list):
        return None
    result: dict[str, Any] = {}
    for tool in tools:
        if not isinstance(tool, dict):
            return None
        function = tool.get("function")
        name = function.get("name") if isinstance(function, dict) else tool.get("name")
        if not isinstance(name, str) or not name:
            return None
        result[name] = tool
    return result


def _tools_continue(previous: Any, current: Any) -> bool:
    old = _tool_map(previous)
    new = _tool_map(current)
    if old is None or new is None:
        return False
    return all(new.get(name) == definition for name, definition in old.items())


def _continues(previous: CaptureRound, current: CaptureRound, conversation: list[dict[str, Any]]) -> bool:
    if previous.request_body.get("model") != current.request_body.get("model"):
        return False
    if not _tools_continue(previous.request_body.get("tools", []), current.request_body.get("tools", [])):
        return False
    if len(current.history) < len(conversation):
        return False
    return current.history[: len(conversation)] == conversation


def _segments(captures: tuple[CaptureRound, ...]) -> list[tuple[list[CaptureRound], list[dict[str, Any]], dict[str, Any]]]:
    if not captures:
        return []
    result: list[tuple[list[CaptureRound], list[dict[str, Any]], dict[str, Any]]] = []
    rounds: list[CaptureRound] = [captures[0]]
    conversation = copy.deepcopy(captures[0].history)
    conversation.append(copy.deepcopy(captures[0].assistant))
    for current in captures[1:]:
        if _continues(rounds[-1], current, conversation):
            suffix = current.history[len(conversation) :]
            conversation.extend(copy.deepcopy(suffix))
            conversation.append(copy.deepcopy(current.assistant))
            rounds.append(current)
        else:
            result.append((rounds, conversation, rounds[-1].request_body))
            rounds = [current]
            conversation = copy.deepcopy(current.history)
            conversation.append(copy.deepcopy(current.assistant))
    result.append((rounds, conversation, rounds[-1].request_body))
    return result


def _result_is_eligible(task: TaskInput, only_verified: bool, include_failed: bool) -> tuple[bool, str | None]:
    execution = task.result.get("execution")
    execution_status = execution.get("status") if isinstance(execution, dict) else None
    if not include_failed and execution_status != "completed":
        return False, f"execution.status={execution_status!r}"
    if only_verified:
        verification = task.result.get("verification")
        status = verification.get("status") if isinstance(verification, dict) else None
        if status != "verified":
            return False, f"verification.status={status!r}"
    return True, None


def discover_results(run_dir: Path) -> list[Path]:
    # result.json is the task boundary written by the Harness.  Do not require
    # auxiliary files here: a failed task can legitimately lack one of them.
    return sorted(path for path in run_dir.rglob("result.json"))


def export_task_trajectories(
    run_dir: Path,
    output: Path,
    *,
    report_path: Path | None = None,
    only_verified: bool = False,
    include_failed: bool = False,
    allow_shared_captures: bool = False,
    recover_terminal_sse: bool = False,
) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")
    tasks: list[TaskInput] = []
    skipped: list[dict[str, Any]] = []
    for result_path in discover_results(run_dir):
        task, error = _load_task(
            result_path, recover_terminal_sse=recover_terminal_sse
        )
        if task is None:
            skipped.append({"result": str(result_path), "reason": error})
            continue
        eligible, reason = _result_is_eligible(task, only_verified, include_failed)
        if not eligible:
            skipped.append({"result": str(result_path), "task_id": task.task_id, "reason": reason})
            continue
        tasks.append(task)

    owners: dict[str, list[str]] = {}
    for task in tasks:
        owner = f"{task.task_id}/{task.agent_id}"
        for capture in task.captures:
            owners.setdefault(capture.capture_id, []).append(owner)
    shared = {capture_id: values for capture_id, values in owners.items() if len(set(values)) > 1}

    seen_tasks: set[tuple[str, str]] = set()
    samples: list[dict[str, Any]] = []
    for task in tasks:
        key = (task.task_id, task.agent_id)
        if key in seen_tasks:
            skipped.append({"result": str(task.result_path), "task_id": task.task_id, "reason": "duplicate task/agent result"})
            continue
        seen_tasks.add(key)
        shared_ids = [capture.capture_id for capture in task.captures if capture.capture_id in shared]
        if shared_ids and not allow_shared_captures:
            skipped.append({"result": str(task.result_path), "task_id": task.task_id, "reason": "capture ids shared by multiple task manifests", "capture_ids": shared_ids})
            continue
        segments = _segments(task.captures)
        model = task.captures[-1].request_body.get("model")
        agent = task.result.get("agent")
        agent = agent if isinstance(agent, dict) else {}
        agent_kind = agent.get("agent_kind", "main")
        for index, (rounds, conversation, final_body) in enumerate(segments, start=1):
            sample = {
                "id": _sample_id(task.task_id, model, str(agent_kind), f"{_slug(task.agent_id)}-segment-{index}"),
                "messages": conversation,
                "tools": copy.deepcopy(final_body.get("tools", [])) if isinstance(final_body.get("tools", []), list) else [],
                "metadata": {
                    "task_id": task.task_id,
                    "agent_id": task.agent_id,
                    "model": model,
                    "dataset": _dataset(task.task_id),
                    "agent_kind": agent_kind,
                    "capture_ids": [item.capture_id for item in rounds],
                    "capture_count": len(rounds),
                    "segment_index": index,
                    "segment_count": len(segments),
                    "source_result": str(task.result_path),
                    "source_manifest": str(task.manifest_path),
                },
            }
            samples.append(sample)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for sample in samples:
            stream.write(json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n")

    report = {
        "schema_version": "1.0",
        "run_dir": str(run_dir),
        "output": str(output),
        "result_files_found": len(discover_results(run_dir)),
        "eligible_tasks": len(tasks),
        "exported_samples": len(samples),
        "exported_tasks": len({sample["metadata"]["task_id"] for sample in samples}),
        "shared_capture_ids": shared,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "options": {
            "only_verified": only_verified,
            "include_failed": include_failed,
            "allow_shared_captures": allow_shared_captures,
            "recover_terminal_sse": recover_terminal_sse,
        },
    }
    target = report_path or output.with_name(output.stem + ".report.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate complete API captures into task-level multi-turn JSONL")
    parser.add_argument("--run-dir", type=Path, required=True, help="one round directory containing node*/worker*/logs/*/result.json")
    parser.add_argument("--output", type=Path, required=True, help="task-level JSONL output")
    parser.add_argument("--report", type=Path, help="JSON report path; defaults beside --output")
    parser.add_argument("--only-verified", action="store_true", help="export only tasks whose verification.status is verified")
    parser.add_argument("--include-failed", action="store_true", help="allow execution.status=failed when captures themselves are complete")
    parser.add_argument("--allow-shared-captures", action="store_true", help="allow a capture id referenced by multiple manifests; unsafe for strict datasets")
    parser.add_argument(
        "--recover-terminal-sse",
        action="store_true",
        help="accept legacy state=partial captures only when a clean 2xx SSE body contains [DONE]",
    )
    args = parser.parse_args(argv)
    report = export_task_trajectories(
        args.run_dir,
        args.output,
        report_path=args.report,
        only_verified=args.only_verified,
        include_failed=args.include_failed,
        allow_shared_captures=args.allow_shared_captures,
        recover_terminal_sse=args.recover_terminal_sse,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
