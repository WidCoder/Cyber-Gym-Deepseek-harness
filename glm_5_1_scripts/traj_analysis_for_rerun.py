#!/usr/bin/env python3
"""统计 CyberGym 轨迹问题，并输出汇总与定位明细。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


问题类型 = [
    "调用子智能体",
    "尝试联网",
    "暴力扫描或枚举",
    "命令或工具不可用",
    "超时或中断",
    "工具显式报错",
]

联网命令 = re.compile(
    r"(?:^|[;&|\s])(?:curl|wget|aria2c|ping|nslookup|dig|ssh|scp|nc|netcat)\b"
    r"|\bgit\s+(?:clone|fetch|pull)\b"
    r"|\b(?:pip|pip3)\s+install\b"
    r"|\b(?:npm|yarn|pnpm)\s+(?:install|add)\b"
    r"|\b(?:apt(?:-get)?|yum|dnf|apk)\s+(?:update|install)\b",
    re.I,
)
扫描命令 = re.compile(
    r"(?:^|[;&|\s])(?:nmap|masscan|gobuster|ffuf|dirb|dirsearch|feroxbuster|wfuzz|hydra|sqlmap|nikto)\b"
    r"|\b(?:for|while)\b.*\b(?:curl|wget|nc|bash\s+\./submit\.sh)\b",
    re.I,
)
基础命令 = re.compile(r"(?:^|[;&|\s])(?:unzip|python|python3)\b", re.I)
提交命令 = re.compile(r"(?:^|[;&|\s])(?:bash\s+)?(?:\./)?submit\.sh\b", re.I)
工具不可用 = re.compile(
    r"command not found|not recognized as an internal|no such command|unknown tool|tool .* not (?:available|found)",
    re.I,
)
权限错误 = re.compile(r"permission denied|operation not permitted|unauthorized|forbidden", re.I)
文件不存在 = re.compile(r"no such file or directory|cannot find|file not found", re.I)
超时中断 = re.compile(r"timed?\s*out|timeout|interrupted", re.I)

联网工具 = {"webfetch", "websearch", "browser", "fetch", "search"}
子智能体工具 = {"task", "agent", "subagent", "spawn_agent"}
命令行工具 = {"bash", "shell", "terminal", "exec", "exec_command"}


def 转成文本(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(转成文本(item) for item in value)
    if isinstance(value, dict):
        if "text" in value and len(value) <= 3:
            return 转成文本(value["text"])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def 读取事件(path: Path) -> list[tuple[int, dict[str, Any]]]:
    events: list[tuple[int, dict[str, Any]]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON：{exc}") from exc
            if isinstance(value, dict):
                events.append((line_number, value))
    return events


def 查找日志(inputs: list[str]) -> list[Path]:
    logs: set[Path] = set()
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_file():
            logs.add(path.resolve())
        elif path.is_dir():
            logs.update(
                item.resolve()
                for item in path.rglob("console.log")
                if item.is_file() and item.parent.parent.name == "logs"
            )
        else:
            raise FileNotFoundError(f"路径不存在：{path}")
    return sorted(logs)


def 内容块(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content", [])
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    return []


def 取得命令(tool: str, tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "cmd"):
        if key in tool_input:
            return 转成文本(tool_input[key])
    if tool.lower() in 命令行工具:
        return 转成文本(tool_input)
    return ""


def 提取工具调用(events: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    """用 tool_use.id 和 tool_result.tool_use_id 关联调用及结果。"""
    calls: list[dict[str, Any]] = []
    calls_by_id: dict[str, dict[str, Any]] = {}

    for line_number, event in events:
        for block in 内容块(event):
            block_type = str(block.get("type", "")).lower()
            if block_type == "tool_use":
                tool = 转成文本(block.get("name"))
                tool_input = block.get("input", {})
                call_id = 转成文本(block.get("id")) or f"匿名调用-{len(calls) + 1}"
                call = {
                    "sequence": len(calls) + 1,
                    "id": call_id,
                    "tool": tool,
                    "input": 转成文本(tool_input),
                    "command": 取得命令(tool, tool_input),
                    "result": "",
                    "is_error": False,
                    "use_line": line_number,
                    "result_line": "",
                }
                calls.append(call)
                calls_by_id[call_id] = call
            elif block_type == "tool_result":
                call_id = 转成文本(block.get("tool_use_id"))
                call = calls_by_id.get(call_id)
                if call is not None:
                    call["result"] = 转成文本(block.get("content"))
                    call["is_error"] = bool(block.get("is_error", False))
                    call["result_line"] = line_number

        # 该日志格式还可能把结构化结果放在事件外层，用它补充错误标记和 stdout。
        outer_result = event.get("tool_use_result")
        if isinstance(outer_result, dict):
            for block in 内容块(event):
                if str(block.get("type", "")).lower() != "tool_result":
                    continue
                call_id = 转成文本(block.get("tool_use_id"))
                call = calls_by_id.get(call_id)
                if call is None:
                    continue
                call["is_error"] |= bool(outer_result.get("is_error", False))
                if not call["result"]:
                    call["result"] = 转成文本(outer_result.get("stdout", outer_result))
                if not call["result_line"]:
                    call["result_line"] = line_number
    return calls



def 判断结束原因(events: list[tuple[int, dict[str, Any]]]) -> str:
    if not events:
        return "超时结束"
    subtype = str(events[-1][1].get("subtype", "")).lower()
    is_error = events[-1][1].get("is_error", "")
    if is_error:
        return "网络错误结束"
    if subtype == "success":
        return "正常结束"
    if subtype == "error_max_turns":
        return "达到最大轮数"
    return "超时结束"


def 分析单个日志(path: Path) -> tuple[list[dict[str, Any]], str]:
    details: list[dict[str, Any]] = []
    task_type = str(path).split("/")[-2].split("_")[0]
    task_index = str(path).split("/")[-2].split("_")[1].split("-")[0]
    task_id = task_type + ":" + task_index
    events = 读取事件(path)
    return task_id, 判断结束原因(events)


def 写入结果(
    output_dir,
    details: list[str],
    end_counts: Counter[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"{end_counts}")

    with open(str(output_dir) + "/rerun_list", "w", encoding="utf-8") as f:
        for d in details:
            f.write(d)
            f.write("\n")

def traj_analysis(inputs, output=False, output_dir="/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/zhangyuyao/cybergym/glm_5_1_scripts/distribute_scripts_rerun"):
    logs = 查找日志([inputs])
    if not logs:
        parser.error("没有找到 logs/<样本ID>/console.log")
    details = []
    end_counts: Counter[str] = Counter()
    failed_logs = 0
    for path in logs:
        try:
            task_id, end_reason = 分析单个日志(path)
            if end_reason == "网络错误结束":
                print(path, task_id)
                details.append(task_id)
            end_counts[end_reason] += 1
        except (OSError, ValueError) as exc:
            failed_logs += 1
            # print(f"跳过日志：{exc}")
    # print(f"已读取 {len(logs) - failed_logs} 个日志，发现 {len(details)} 条问题记录")
    if output:
        写入结果(output_dir, details, end_counts)
        # print(f"输出目录：{output_dir}")
    return len(details)



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="评测任务目录或单个 console.log")
    parser.add_argument("-o", "--output-dir", default="轨迹问题分析", help="输出目录")
    args = parser.parse_args()

    logs = 查找日志(args.inputs)
    if not logs:
        parser.error("没有找到 logs/<样本ID>/console.log")

    details = []
    end_counts: Counter[str] = Counter()
    failed_logs = 0
    for path in logs:
        try:
            task_id, end_reason = 分析单个日志(path)
            if end_reason == "网络错误结束":
                details.append(task_id)
            end_counts[end_reason] += 1
        except (OSError, ValueError) as exc:
            failed_logs += 1
            print(f"跳过日志：{exc}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    写入结果(output_dir, details, end_counts)
    print(f"已读取 {len(logs) - failed_logs} 个日志，发现 {len(details)} 条问题记录")
    print(f"输出目录：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
