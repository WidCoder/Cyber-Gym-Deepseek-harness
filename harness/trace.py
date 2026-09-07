"""Normalize DeepSeek Harness session chunks into readable JSONL events."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterator


def find_session(root: Path) -> Path | None:
    sessions = sorted(root.rglob("session*.jsonl.zstd"), key=lambda p: p.stat().st_mtime)
    return sessions[-1] if sessions else None


def _iter_compressed(path: Path) -> Iterator[str]:
    try:
        import zstandard  # type: ignore
    except ImportError:
        zstandard = None
    if zstandard is not None:
        with path.open("rb") as source:
            reader = zstandard.ZstdDecompressor().stream_reader(source)
            buffer = b""
            while True:
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    yield line.decode("utf-8", errors="replace")
            if buffer:
                yield buffer.decode("utf-8", errors="replace")
        return

    for command in (("zstd", "-dc", str(path)), ("zstdcat", str(path))):
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            continue
        assert process.stdout is not None
        for line in process.stdout:
            yield line.decode("utf-8", errors="replace").rstrip("\n")
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        if process.wait() == 0:
            return
        if stderr:
            raise RuntimeError(f"cannot decompress {path}: {stderr.strip()}")
    raise RuntimeError("zstandard support is unavailable; install neither packages nor dependencies at runtime")


def _iter_records(path: Path) -> Iterator[dict[str, Any]]:
    lines = _iter_compressed(path) if path.name.endswith(".zstd") else path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def _text(value: Any, depth: int = 0) -> str:
    if depth > 5 or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_text(item, depth + 1) for item in value)
    if isinstance(value, dict):
        for key in ("text", "thinking", "reasoning", "content", "message", "delta", "value", "output"):
            if key in value:
                result = _text(value[key], depth + 1)
                if result:
                    return result
        for item in value.values():
            result = _text(item, depth + 1)
            if result:
                return result
    return ""


def _find_value(value: Any, names: set[str], depth: int = 0) -> Any:
    if depth > 5 or not isinstance(value, (dict, list)):
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in names and isinstance(item, (str, int, float, bool, dict, list)):
                return item
            found = _find_value(item, names, depth + 1)
            if found is not None:
                return found
    else:
        for item in value:
            found = _find_value(item, names, depth + 1)
            if found is not None:
                return found
    return None


def _kind(record: dict[str, Any]) -> str:
    raw = str(record.get("type") or record.get("event") or record.get("kind") or "unknown")
    lower = raw.lower()
    if "error" in lower or "fail" in lower:
        return "error"
    if "tool" in lower and any(word in lower for word in ("result", "output", "return", "end")):
        return "tool_result"
    if "tool" in lower or "call" in lower or "invoke" in lower:
        return "tool_call"
    if "think" in lower or "reason" in lower:
        return "assistant_thinking"
    if any(word in lower for word in ("start", "create", "init")):
        return "session_start"
    if any(word in lower for word in ("finish", "complete", "stop", "dispose")):
        return "session_end"
    if any(word in lower for word in ("text", "message", "assistant", "spliced", "delta")):
        return "assistant_text"
    return "unknown"


def _normalize(record: dict[str, Any], index: int) -> dict[str, Any]:
    kind = _kind(record)
    raw_type = str(record.get("type") or record.get("event") or record.get("kind") or "unknown")
    text = _text(record)
    tool = _find_value(record, {"tool", "tool_name", "name"})
    command = _find_value(record, {"command", "cmd", "arguments", "input", "params"})
    timestamp = record.get("time", record.get("timestamp"))
    event: dict[str, Any] = {
        "type": kind,
        "seq": record.get("seq", index),
        "timestamp": timestamp,
        "raw_type": raw_type,
    }
    if text:
        event["message"] = {"role": "assistant", "content": text}
    if tool is not None:
        event["tool"] = str(tool)
    if command is not None and command != text:
        event["arguments"] = command
    if kind == "unknown":
        event["raw_keys"] = sorted(record.keys())
    return event


def normalize_session(session: Path, output: Path) -> dict[str, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    stats = {"events": 0, "thinking": 0, "text": 0, "tool_calls": 0, "tool_results": 0, "errors": 0}
    previous: dict[str, Any] | None = None
    with output.open("w", encoding="utf-8") as stream:
        for index, record in enumerate(_iter_records(session), start=1):
            event = _normalize(record, index)
            text = event.get("message", {}).get("content", "")
            if previous and event["type"] == previous["type"] and text and previous.get("message"):
                previous["message"]["content"] += text
                previous["chunk_count"] = previous.get("chunk_count", 1) + 1
                continue
            if previous is not None:
                stream.write(json.dumps(previous, ensure_ascii=False) + "\n")
            previous = event
            stats["events"] += 1
            stats["thinking"] += event["type"] == "assistant_thinking"
            stats["text"] += event["type"] == "assistant_text"
            stats["tool_calls"] += event["type"] == "tool_call"
            stats["tool_results"] += event["type"] == "tool_result"
            stats["errors"] += event["type"] == "error"
        if previous is not None:
            stream.write(json.dumps(previous, ensure_ascii=False) + "\n")
    return stats


def submit_paths(console: Path) -> list[str]:
    if not console.is_file():
        return []
    text = console.read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r"(?:bash|sh)\s+[^\n]*?submit\.sh\s+(\S+)", text)))
