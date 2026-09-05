#!/usr/bin/env python3
"""Extract explicit package installation commands from CyberGym trajectory logs."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SHELL_TOOL_NAMES = {"bash", "shell", "terminal", "exec", "exec_command"}

SHELL_COMMAND_SEPARATOR_PATTERN = re.compile(r"\s*(?:&&|\|\||;|\n)\s*")

INSTALL_COMMAND_PATTERN = re.compile(
    r"""
    (?:
        (?<![\w./-])(?:python|python3|py)\s+-m\s+(?:pip|pip3)\s+install\b
      | (?<![\w./-])uv\s+pip\s+install\b
      | (?<![\w./-])(?:pip|pip3|pipx)\s+install\b
      | (?<![\w./-])(?:npm|yarn|pnpm)\s+(?:install|add|i)\b
      | (?<![\w./-])(?:apt|apt-get|yum|dnf|zypper|pacman)\s+install\b
      | (?<![\w./-])apk\s+add\b
      | (?<![\w./-])(?:conda|mamba|micromamba)\s+install\b
      | (?<![\w./-])brew\s+install\b
      | (?<![\w./-])gem\s+install\b
      | (?<![\w./-])cargo\s+install\b
      | (?<![\w./-])go\s+install\b
      | (?<![\w./-])Rscript\s+-e\s+['"][^'"]*install\.packages\s*\(
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

PYTHON_REQUIREMENT_FILE_OPTIONS = {
    "-r",
    "--requirement",
    "--requirements",
    "-c",
    "--constraint",
}

VALUE_OPTIONS = {
    "-i",
    "--index-url",
    "--extra-index-url",
    "--trusted-host",
    "--find-links",
    "-f",
    "--proxy",
    "--platform",
    "--python-version",
    "--implementation",
    "--abi",
    "--target",
    "-t",
    "--prefix",
    "--root",
    "--src",
    "--cache-dir",
    "--timeout",
    "--retries",
    "--config-settings",
    "-C",
    "--registry",
    "--global-folder",
    "--modules-folder",
    "--production",
    "--save-prefix",
    "--tag",
    "--channel",
    "--file",
    "--name",
    "-n",
}

FLAG_OPTIONS = {
    "-y",
    "--yes",
    "-q",
    "-qq",
    "--quiet",
    "--upgrade",
    "-U",
    "--force-reinstall",
    "--no-deps",
    "--user",
    "--system",
    "--break-system-packages",
    "--no-cache-dir",
    "--pre",
    "--editable",
    "-e",
    "--save",
    "--save-dev",
    "-D",
    "--dev",
    "-g",
    "--global",
    "--no-save",
    "--frozen-lockfile",
    "--legacy-peer-deps",
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    "--latest",
    "--HEAD",
    "--cask",
    "--classic",
    "--needed",
    "--noconfirm",
}

PYTHON_INSTALLERS = {"pip", "pip3", "pipx", "uv pip"}
JAVASCRIPT_INSTALLERS = {"npm", "yarn", "pnpm"}


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(stringify(item) for item in value)
    if isinstance(value, dict):
        if "text" in value and len(value) <= 3:
            return stringify(value["text"])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def read_events(log_path: Path) -> list[tuple[int, dict[str, Any]]]:
    events: list[tuple[int, dict[str, Any]]] = []
    with log_path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{log_path} line {line_number} is not valid JSON: {exc}") from exc
            if isinstance(value, dict):
                events.append((line_number, value))
    return events


def find_log_files(inputs: list[str]) -> list[Path]:
    log_files: set[Path] = set()
    for raw_input in inputs:
        input_path = Path(raw_input).expanduser()
        if input_path.is_file():
            log_files.add(input_path.resolve())
        elif input_path.is_dir():
            log_files.update(
                item.resolve()
                for item in input_path.rglob("console.log")
                if item.is_file() and item.parent.parent.name == "logs"
            )
        else:
            raise FileNotFoundError(f"Path does not exist: {input_path}")
    return sorted(log_files)


def get_content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, dict):
        return []

    content = message.get("content", [])
    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    return []


def extract_shell_command(tool_name: str, tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""

    for key in ("command", "cmd"):
        if key in tool_input:
            return stringify(tool_input[key])

    if tool_name.lower() in SHELL_TOOL_NAMES:
        return stringify(tool_input)

    return ""


def extract_tool_calls(events: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    calls_by_id: dict[str, dict[str, Any]] = {}

    for line_number, event in events:
        for block in get_content_blocks(event):
            block_type = str(block.get("type", "")).lower()
            if block_type == "tool_use":
                tool_name = stringify(block.get("name"))
                tool_input = block.get("input", {})
                call_id = stringify(block.get("id")) or f"anonymous-call-{len(calls) + 1}"
                call = {
                    "sequence": len(calls) + 1,
                    "id": call_id,
                    "tool": tool_name,
                    "input": stringify(tool_input),
                    "command": extract_shell_command(tool_name, tool_input),
                    "result": "",
                    "is_error": False,
                    "use_line": line_number,
                    "result_line": "",
                }
                calls.append(call)
                calls_by_id[call_id] = call
            elif block_type == "tool_result":
                call_id = stringify(block.get("tool_use_id"))
                call = calls_by_id.get(call_id)
                if call is not None:
                    call["result"] = stringify(block.get("content"))
                    call["is_error"] = bool(block.get("is_error", False))
                    call["result_line"] = line_number

        outer_result = event.get("tool_use_result")
        if isinstance(outer_result, dict):
            for block in get_content_blocks(event):
                if str(block.get("type", "")).lower() != "tool_result":
                    continue

                call_id = stringify(block.get("tool_use_id"))
                call = calls_by_id.get(call_id)
                if call is None:
                    continue

                call["is_error"] |= bool(outer_result.get("is_error", False))
                if not call["result"]:
                    call["result"] = stringify(outer_result.get("stdout", outer_result))
                if not call["result_line"]:
                    call["result_line"] = line_number

    return calls


def split_install_command_fragments(command: str) -> list[str]:
    fragments: list[str] = []
    for part in SHELL_COMMAND_SEPARATOR_PATTERN.split(command):
        if INSTALL_COMMAND_PATTERN.search(part):
            fragments.append(part.strip())
    return fragments


def tokenize_command(command_fragment: str) -> list[str]:
    try:
        return shlex.split(command_fragment, posix=True)
    except ValueError:
        return command_fragment.split()


def drop_environment_assignments(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
        index += 1
    return tokens[index:]


def identify_installer(tokens: list[str]) -> tuple[str, int]:
    tokens = drop_environment_assignments(tokens)
    lowered = [item.lower() for item in tokens]

    if (
        len(lowered) >= 4
        and lowered[0] in {"python", "python3", "py"}
        and lowered[1] == "-m"
        and lowered[2] in {"pip", "pip3"}
        and lowered[3] == "install"
    ):
        return "pip", 4

    if len(lowered) >= 3 and lowered[0] == "uv" and lowered[1] == "pip" and lowered[2] == "install":
        return "uv pip", 3

    if len(lowered) >= 2 and lowered[0] in {"pip", "pip3", "pipx"} and lowered[1] == "install":
        return lowered[0], 2

    if len(lowered) >= 2 and lowered[0] in {"npm", "yarn", "pnpm"} and lowered[1] in {"install", "add", "i"}:
        return lowered[0], 2

    if len(lowered) >= 2 and lowered[0] in {"apt", "apt-get", "yum", "dnf", "zypper", "pacman"} and lowered[1] == "install":
        return lowered[0], 2

    if len(lowered) >= 2 and lowered[0] == "apk" and lowered[1] == "add":
        return "apk", 2

    if len(lowered) >= 2 and lowered[0] in {"conda", "mamba", "micromamba"} and lowered[1] == "install":
        return lowered[0], 2

    if len(lowered) >= 2 and lowered[0] in {"brew", "gem", "cargo", "go"} and lowered[1] == "install":
        return lowered[0], 2

    return "unknown", 0


def extract_r_packages(command_fragment: str) -> list[str]:
    match = re.search(r"install\.packages\s*\((?P<body>.*?)\)", command_fragment, re.IGNORECASE)
    if not match:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group("body"))


def option_requires_value(installer: str, option: str) -> bool:
    if installer in PYTHON_INSTALLERS and option in PYTHON_REQUIREMENT_FILE_OPTIONS:
        return True
    return option in VALUE_OPTIONS


def parse_package_arguments(installer: str, args: list[str]) -> tuple[list[str], list[str], list[str]]:
    packages: list[str] = []
    requirement_files: list[str] = []
    options: list[str] = []
    index = 0

    while index < len(args):
        item = args[index]

        if item == "--":
            packages.extend(args[index + 1 :])
            break

        if installer in PYTHON_INSTALLERS and item in PYTHON_REQUIREMENT_FILE_OPTIONS:
            if index + 1 < len(args):
                requirement_files.append(args[index + 1])
                options.extend([item, args[index + 1]])
                index += 2
                continue
            options.append(item)
            index += 1
            continue

        if item.startswith("--") and "=" in item:
            option_name, option_value = item.split("=", 1)
            if installer in PYTHON_INSTALLERS and option_name in PYTHON_REQUIREMENT_FILE_OPTIONS:
                requirement_files.append(option_value)
            options.append(item)
            index += 1
            continue

        if option_requires_value(installer, item):
            if index + 1 < len(args):
                options.extend([item, args[index + 1]])
                index += 2
                continue
            options.append(item)
            index += 1
            continue

        if item in FLAG_OPTIONS or item.startswith("-"):
            options.append(item)
            index += 1
            continue

        if installer in JAVASCRIPT_INSTALLERS and item in {".", "./"}:
            options.append(item)
        else:
            packages.append(item)

        index += 1

    return packages, requirement_files, options


def parse_install_fragment(command_fragment: str) -> dict[str, Any] | None:
    if re.search(r"Rscript\s+-e\s+['\"][^'\"]*install\.packages\s*\(", command_fragment, re.IGNORECASE):
        packages = extract_r_packages(command_fragment)
        return {
            "installer": "R install.packages",
            "packages": " | ".join(packages),
            "package_count": len(packages),
            "requirement_files": "",
            "install_options": "",
            "install_command_fragment": command_fragment,
        }

    match = INSTALL_COMMAND_PATTERN.search(command_fragment)
    if match is None:
        return None

    command_for_parse = command_fragment[match.start() :].strip().strip("'\"")
    tokens = tokenize_command(command_for_parse)
    installer, args_start = identify_installer(tokens)
    if not args_start:
        return None

    packages, requirement_files, options = parse_package_arguments(installer, tokens[args_start:])
    return {
        "installer": installer,
        "packages": " | ".join(packages),
        "package_count": len(packages),
        "requirement_files": " | ".join(requirement_files),
        "install_options": " ".join(options),
        "install_command_fragment": command_fragment,
    }


def analyze_log_file(log_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    events = read_events(log_path)

    for call in extract_tool_calls(events):
        command = str(call["command"])
        if not command:
            continue

        for fragment in split_install_command_fragments(command):
            parsed_install = parse_install_fragment(fragment)
            if parsed_install is None:
                continue

            rows.append(
                {
                    "sample_id": log_path.parent.name,
                    "log_file": str(log_path),
                    "tool_call_sequence": call["sequence"],
                    "tool_name": call["tool"],
                    "tool_use_line": call["use_line"],
                    "tool_result_line": call["result_line"],
                    "tool_reported_error": bool(call["is_error"]),
                    "original_command": json.dumps({"command": command},ensure_ascii=False),
                    **parsed_install,
                }
            )

    return rows


def write_outputs(output_dir: Path, rows: list[dict[str, Any]], successful_log_count: int, failed_log_count: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    detail_fields = [
        "sample_id",
        "log_file",
        "tool_call_sequence",
        "tool_name",
        "tool_use_line",
        "tool_result_line",
        "tool_reported_error",
        "installer",
        "packages",
        "package_count",
        "requirement_files",
        "install_options",
        "install_command_fragment",
        "original_command",
    ]
    with (output_dir / "install_command_details.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=detail_fields)
        writer.writeheader()
        writer.writerows(rows)

    installer_counts = Counter(row["installer"] for row in rows)
    logs_by_installer: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        logs_by_installer[str(row["installer"])].add(str(row["log_file"]))

    with (output_dir / "installer_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["installer", "install_command_count", "log_file_count"])
        for installer, count in installer_counts.most_common():
            writer.writerow([installer, count, len(logs_by_installer[installer])])

    package_counts: Counter[tuple[str, str]] = Counter()
    logs_by_package: dict[tuple[str, str], set[str]] = defaultdict(set)
    requirement_counts: Counter[tuple[str, str]] = Counter()
    logs_by_requirement_file: dict[tuple[str, str], set[str]] = defaultdict(set)

    for row in rows:
        installer = str(row["installer"])
        log_file = str(row["log_file"])

        for package in str(row["packages"]).split(" | "):
            if package:
                key = (installer, package)
                package_counts[key] += 1
                logs_by_package[key].add(log_file)

        for requirement_file in str(row["requirement_files"]).split(" | "):
            if requirement_file:
                key = (installer, requirement_file)
                requirement_counts[key] += 1
                logs_by_requirement_file[key].add(log_file)

    with (output_dir / "package_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["installer", "package_or_library", "occurrence_count", "log_file_count"])
        for (installer, package), count in package_counts.most_common():
            writer.writerow([installer, package, count, len(logs_by_package[(installer, package)])])

    with (output_dir / "requirement_file_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["installer", "requirement_file", "occurrence_count", "log_file_count"])
        for (installer, requirement_file), count in requirement_counts.most_common():
            writer.writerow(
                [
                    installer,
                    requirement_file,
                    count,
                    len(logs_by_requirement_file[(installer, requirement_file)]),
                ]
            )

    # with (output_dir / "read_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    #     writer = csv.writer(handle)
    #     writer.writerow(["metric", "value"])
    #     writer.writerow(["successful_log_count", successful_log_count])
    #     writer.writerow(["failed_log_count", failed_log_count])
    #     writer.writerow(["install_command_record_count", len(rows)])
    #     writer.writerow(["explicit_package_record_count", sum(int(row["package_count"]) for row in rows)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Evaluation task directories or individual console.log files.")
    parser.add_argument("-o", "--output-dir", default="install_command_analysis", help="Directory for CSV outputs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_files = find_log_files(args.inputs)
    if not log_files:
        raise SystemExit("No logs/<sample_id>/console.log files found.")

    rows: list[dict[str, Any]] = []
    failed_log_count = 0

    for log_path in log_files:
        try:
            rows.extend(analyze_log_file(log_path))
        except (OSError, ValueError) as exc:
            failed_log_count += 1
            print(f"Skipping log: {exc}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    write_outputs(output_dir, rows, len(log_files) - failed_log_count, failed_log_count)

    print(f"Read {len(log_files) - failed_log_count} logs and found {len(rows)} install command records.")
    print(f"Output directory: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
