"""Export captured API rounds as multi-turn JSONL training samples.

The capture proxy stores one request/response pair per directory.  This
converter keeps the complete request message history and tools, then appends
the assistant response reconstructed from either a normal JSON response or
OpenAI/Anthropic SSE chunks.  It intentionally omits HTTP headers and keys.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _body(request: dict[str, Any]) -> dict[str, Any]:
    value = request.get("body_json")
    if isinstance(value, dict):
        return value
    body = request.get("body")
    if isinstance(body, dict) and isinstance(body.get("json"), dict):
        return body["json"]
    return {}


def _slug(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    return text.strip("-_.") or "unknown"


def _dataset(task_id: Any) -> str:
    if not isinstance(task_id, str) or not task_id.strip():
        return "unknown"
    return task_id.split(":", 1)[0] or "unknown"


def _meta_blocks(body: dict[str, Any], request: dict[str, Any], response: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for container in (body, request, response):
        for key in ("metadata", "meta", "cybergym"):
            value = container.get(key) if isinstance(container, dict) else None
            if isinstance(value, dict):
                blocks.append(value)
    return blocks


def _agent_kind(body: dict[str, Any], request: dict[str, Any], response: dict[str, Any]) -> str:
    def normalize(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        lowered = value.strip().lower().replace("-", "_")
        aliases = {
            "main": "main",
            "primary": "main",
            "root": "main",
            "sub": "subagent",
            "subagent": "subagent",
            "sub_agent": "subagent",
            "compress": "compress",
            "compression": "compress",
            "compact": "compress",
            "compaction": "compress",
        }
        return aliases.get(lowered)

    for container in [body, request, response, *_meta_blocks(body, request, response)]:
        if not isinstance(container, dict):
            continue
        for key in ("agent_kind", "agent_type", "role_kind", "instruction_type", "sample_kind", "kind", "type"):
            value = normalize(container.get(key))
            if value:
                return value

    haystack_parts: list[str] = []
    for container in [body, request, response, *_meta_blocks(body, request, response)]:
        try:
            haystack_parts.append(json.dumps(container, ensure_ascii=False, sort_keys=True))
        except TypeError:
            continue
    haystack = " ".join(haystack_parts).lower()
    if any(token in haystack for token in ("compress", "compaction", "context compaction", "summarize context")):
        return "compress"
    if any(token in haystack for token in ("subagent", "sub agent", "spawn_agent")):
        return "subagent"
    return "main"


def _sample_id(task_id: Any, model: Any, agent_kind: str, capture_id: str) -> str:
    return "-".join(
        [
            _slug(_dataset(task_id)),
            _slug(model),
            _slug(agent_kind),
            _slug(capture_id),
        ]
    )


def _string_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), str):
            return value["content"]
    return None


def _normalize_messages(message: Any) -> list[dict[str, Any]]:
    """Convert common Anthropic/OpenAI message shapes to OpenAI messages."""
    if not isinstance(message, dict):
        return []
    role = str(message.get("role") or "user")
    content = message.get("content")
    result: dict[str, Any] = {"role": role, "content": None}
    reasoning: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    text_parts: list[str] = []

    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type in {"text", "input_text"}:
                text = _string_content(block)
                if text:
                    text_parts.append(text)
            elif block_type in {"thinking", "reasoning", "thinking_delta"}:
                text = _string_content(block) or block.get("thinking")
                if isinstance(text, str):
                    reasoning.append(text)
            elif block_type in {"tool_use", "server_tool_use"}:
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(
                                block.get("input", {}),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                )
            elif block_type in {"tool_result", "server_tool_result"}:
                block_content = block.get("content")
                if isinstance(block_content, list):
                    block_content = "".join(
                        text
                        for text in (_string_content(item) for item in block_content)
                        if text
                    )
                if not isinstance(block_content, str):
                    block_content = json.dumps(block_content, ensure_ascii=False)
                tool_results.append(
                    {
                        "role": "tool",
                        "content": block_content,
                        "tool_call_id": block.get("tool_use_id") or block.get("id"),
                    }
                )
    else:
        text = _string_content(content)
        if text is not None:
            text_parts.append(text)
        elif content is not None:
            result["content"] = copy.deepcopy(content)

    if text_parts:
        result["content"] = "".join(text_parts)
    if isinstance(message.get("reasoning_content"), str):
        reasoning.insert(0, message["reasoning_content"])
    if reasoning:
        result["reasoning_content"] = "".join(reasoning)
    if isinstance(message.get("tool_calls"), list):
        tool_calls = copy.deepcopy(message["tool_calls"])
    if tool_calls:
        result["tool_calls"] = tool_calls
    for key in ("tool_call_id", "name"):
        if key in message and message[key] is not None:
            result[key] = copy.deepcopy(message[key])

    normalized = [result]
    normalized.extend(tool_results)
    return normalized


def _normalize_message(message: Any) -> dict[str, Any] | None:
    messages = _normalize_messages(message)
    return messages[0] if messages else None


def _sse_payloads(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    buffer: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line:
            if buffer:
                raw = "\n".join(buffer)
                buffer = []
                if raw != "[DONE]":
                    try:
                        value = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict):
                        yield value
            continue
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
    if buffer and "\n".join(buffer) != "[DONE]":
        try:
            value = json.loads("\n".join(buffer))
        except json.JSONDecodeError:
            return
        if isinstance(value, dict):
            yield value


def _openai_stream(round_dir: Path) -> dict[str, Any] | None:
    message: dict[str, Any] = {"role": "assistant", "content": ""}
    tool_calls: dict[int, dict[str, Any]] = {}
    found = False
    for chunk in _sse_payloads(round_dir / "response.body"):
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            continue
        delta = choices[0].get("delta")
        if not isinstance(delta, dict):
            continue
        found = True
        if isinstance(delta.get("role"), str):
            message["role"] = delta["role"]
        for key in ("content", "reasoning_content", "reasoning"):
            if isinstance(delta.get(key), str):
                message[key] = str(message.get(key) or "") + delta[key]
        calls = delta.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if not isinstance(call, dict):
                    continue
                index = call.get("index", len(tool_calls))
                if not isinstance(index, int):
                    continue
                target = tool_calls.setdefault(index, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    target["id"] = call["id"]
                if call.get("type"):
                    target["type"] = call["type"]
                function = call.get("function")
                if isinstance(function, dict):
                    if isinstance(function.get("name"), str):
                        target["function"]["name"] += function["name"]
                    if isinstance(function.get("arguments"), str):
                        target["function"]["arguments"] += function["arguments"]
    if tool_calls:
        message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    if not found:
        return None
    if not message.get("content"):
        message["content"] = None
    return _normalize_message(message)


def _anthropic_message(response: dict[str, Any]) -> dict[str, Any] | None:
    value = response.get("message")
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {"role": "assistant", "content": ""}
    thinking: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in value.get("content", []):
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and isinstance(block.get("text"), str):
            result["content"] += block["text"]
        elif kind in {"thinking", "reasoning"} and isinstance(block.get("thinking"), str):
            thinking.append(block["thinking"])
        elif kind in {"tool_use", "server_tool_use"}:
            tool_calls.append({
                "id": block.get("id"),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False, separators=(",", ":")),
                },
            })
    if thinking:
        result["reasoning_content"] = "".join(thinking)
    if tool_calls:
        result["tool_calls"] = tool_calls
    if not result["content"] and not tool_calls:
        return None
    if not result["content"]:
        result["content"] = None
    return _normalize_message(result)


def _anthropic_stream(round_dir: Path) -> dict[str, Any] | None:
    result: dict[str, Any] = {"role": "assistant", "content": ""}
    reasoning: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    current_index = -1
    found = False
    for event in _sse_payloads(round_dir / "response.body"):
        event_type = str(event.get("type") or "")
        if event_type == "message_start":
            message = event.get("message")
            if isinstance(message, dict) and isinstance(message.get("role"), str):
                result["role"] = message["role"]
        elif event_type == "content_block_start":
            current_index += 1
            block = event.get("content_block")
            if isinstance(block, dict) and block.get("type") in {"tool_use", "server_tool_use"}:
                tool_calls[current_index] = {
                    "id": block.get("id"),
                    "type": "function",
                    "function": {"name": block.get("name", ""), "arguments": ""},
                }
            found = True
        elif event_type == "content_block_delta":
            delta = event.get("delta")
            if not isinstance(delta, dict):
                continue
            delta_type = delta.get("type")
            if delta_type == "text_delta" and isinstance(delta.get("text"), str):
                result["content"] += delta["text"]
                found = True
            elif delta_type == "thinking_delta" and isinstance(delta.get("thinking"), str):
                reasoning.append(delta["thinking"])
                found = True
            elif delta_type == "input_json_delta" and current_index in tool_calls:
                partial = delta.get("partial_json")
                if isinstance(partial, str):
                    tool_calls[current_index]["function"]["arguments"] += partial
                    found = True
    if reasoning:
        result["reasoning_content"] = "".join(reasoning)
    if tool_calls:
        result["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    if not found:
        return None
    if not result.get("content"):
        result["content"] = None
    return _normalize_message(result)


def _assistant_message(round_dir: Path, response: dict[str, Any], body: dict[str, Any]) -> dict[str, Any] | None:
    message = _anthropic_message(response)
    if message:
        return message
    body_json = response.get("body_json")
    if isinstance(body_json, dict):
        choices = body_json.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            value = choices[0].get("message")
            if isinstance(value, dict):
                return _normalize_message(value)
    if response.get("stream") or (round_dir / "response.body").is_file():
        stream = _openai_stream(round_dir) or _anthropic_stream(round_dir)
        if stream:
            return stream
    return None


def _training_messages(body: dict[str, Any]) -> list[Any]:
    messages = []
    for item in body.get("messages", []):
        messages.extend(_normalize_messages(item))
    system = body.get("system")
    if system is not None and not (
        messages and isinstance(messages[0], dict) and messages[0].get("role") == "system"
    ):
        system_messages = _normalize_messages({"role": "system", "content": system})
        messages[0:0] = system_messages
    return messages


def _capture_in_window(round_dir: Path, start_time: float | None, end_time: float | None) -> bool:
    request = _read(round_dir / "request.json") or {}
    response = _read(round_dir / "response.json") or {}
    values = [request.get("captured_at"), response.get("finished_at")]
    timestamps: list[float] = []
    from datetime import datetime

    for value in values:
        if isinstance(value, str):
            try:
                timestamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
    if not timestamps:
        return True
    first = min(timestamps)
    last = max(timestamps)
    return (start_time is None or last >= start_time - 1) and (end_time is None or first <= end_time + 1)


def export(
    capture_dir: Path,
    output: Path,
    result_metadata: dict[str, Any] | None = None,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
    agent_kind: str | None = None,
) -> int:
    completed = capture_dir / "raw" / "completed"
    if not completed.is_dir():
        raise SystemExit(f"capture directory not found: {completed}")
    written = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for round_dir in sorted(path for path in completed.iterdir() if path.is_dir()):
            if not _capture_in_window(round_dir, start_time, end_time):
                continue
            request = _read(round_dir / "request.json")
            response = _read(round_dir / "response.json")
            if not request or not response:
                continue
            body = _body(request)
            messages = body.get("messages")
            if not isinstance(messages, list):
                continue
            assistant = _assistant_message(round_dir, response, body)
            if not assistant:
                continue
            metadata = result_metadata if isinstance(result_metadata, dict) else {}
            sample_agent_kind = (
                agent_kind
                or metadata.get("agent_kind")
                or _agent_kind(body, request, response)
            )
            task_id = metadata.get("task_id")
            model = body.get("model") or metadata.get("model")
            sample_id = _sample_id(
                task_id,
                model,
                sample_agent_kind,
                round_dir.name,
            )
            tools = copy.deepcopy(body["tools"]) if isinstance(body.get("tools"), list) else []
            sample: dict[str, Any] = {
                "id": sample_id,
                "messages": _training_messages(body) + [assistant],
                "tools": tools,
                "metadata": {
                    "capture_id": round_dir.name,
                    "model": model,
                    "dataset": _dataset(task_id),
                    "agent_kind": sample_agent_kind,
                    "api_format": "openai-compatible",
                    "source_request": str(round_dir / "request.json"),
                    "source_response": str(round_dir / "response.json"),
                },
            }
            if metadata:
                sample["metadata"].update(metadata)
            stream.write(json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n")
            written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--start-time", type=float)
    parser.add_argument("--end-time", type=float)
    parser.add_argument("--agent-kind", choices=("main", "subagent", "compress"))
    args = parser.parse_args(argv)
    metadata = None
    if args.result:
        value = _read(args.result)
        if value:
            task = value.get("task", {})
            verification = value.get("verification", {})
            metadata = {
                "task_id": task.get("task_id"),
                "agent_id": task.get("agent_id"),
                "harness": value.get("agent", {}).get("harness"),
                "model": value.get("agent", {}).get("model"),
                "agent_kind": value.get("agent", {}).get("agent_kind"),
                "vul_exit_code": verification.get("vul_exit_code"),
                "fix_exit_code": verification.get("fix_exit_code"),
            }
    count = export(
        args.capture_dir,
        args.output,
        metadata,
        start_time=args.start_time,
        end_time=args.end_time,
        agent_kind=args.agent_kind or os.getenv("CAPTURE_AGENT_KIND"),
    )
    print(f"exported_samples={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
