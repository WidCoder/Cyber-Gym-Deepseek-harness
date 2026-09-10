"""Summarize a distributed CyberGym run without reading API secrets."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _counter(value: Counter[str]) -> dict[str, int]:
    return dict(sorted(value.items()))


def analyze_run(run_dir: Path) -> dict[str, Any]:
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")

    result_paths = sorted(run_dir.rglob("result.json"))
    execution: Counter[str] = Counter()
    verification: Counter[str] = Counter()
    capture_meta: Counter[str] = Counter()
    task_ids: Counter[str] = Counter()
    capture_roots: Counter[str] = Counter()
    capture_states: Counter[str] = Counter()
    response_codes: Counter[str] = Counter()
    done_markers: Counter[str] = Counter()
    transport_errors: Counter[str] = Counter()
    disconnects: Counter[str] = Counter()
    invalid_results: list[str] = []
    seen_capture_dirs: set[Path] = set()
    train_files = 0
    trajectory_files = 0

    for result_path in result_paths:
        value = _read_object(result_path)
        if value is None:
            invalid_results.append(str(result_path))
            continue

        task = value.get("task")
        task = task if isinstance(task, dict) else {}
        task_ids[str(task.get("task_id"))] += 1

        execution_value = value.get("execution")
        execution_value = execution_value if isinstance(execution_value, dict) else {}
        execution[str(execution_value.get("status"))] += 1

        verification_value = value.get("verification")
        verification_value = (
            verification_value if isinstance(verification_value, dict) else {}
        )
        verification[str(verification_value.get("status"))] += 1

        if (result_path.parent / "train.jsonl").is_file():
            train_files += 1
        if (result_path.parent / "trajectory.jsonl").is_file():
            trajectory_files += 1

        capture = value.get("api_capture")
        if not isinstance(capture, dict):
            capture_meta["missing"] += 1
            continue
        capture_meta[str(capture.get("status"))] += 1

        directory_value = capture.get("directory")
        if not isinstance(directory_value, str) or not directory_value:
            capture_meta["directory_missing"] += 1
            continue
        capture_root = Path(directory_value)
        capture_roots[str(capture_root)] += 1
        completed = capture_root / "raw" / "completed"
        if not completed.is_dir():
            capture_meta["completed_dir_missing"] += 1
            continue

        for capture_dir in sorted(completed.iterdir()):
            if not capture_dir.is_dir():
                continue
            capture_dir = capture_dir.resolve()
            if capture_dir in seen_capture_dirs:
                continue
            seen_capture_dirs.add(capture_dir)

            state = _read_object(capture_dir / "state.json")
            capture_states[str(state.get("state") if state else None)] += 1

            response = _read_object(capture_dir / "response.json")
            if response is None:
                response_codes["invalid_response"] += 1
            else:
                response_codes[str(response.get("status_code"))] += 1
                error = response.get("transport_error")
                if error:
                    transport_errors[str(error)] += 1
                if response.get("client_disconnected") is True:
                    disconnects["true"] += 1

            body = capture_dir / "response.body"
            try:
                has_done = body.is_file() and b"[DONE]" in body.read_bytes()
            except OSError:
                has_done = False
            done_markers["true" if has_done else "false"] += 1

    task_trajectory_files = sorted(run_dir.glob("task_trajectories*.jsonl"))
    reports = sorted(run_dir.glob("task_trajectories*.report.json"))
    return {
        "run_dir": str(run_dir),
        "result_files": len(result_paths),
        "invalid_result_files": invalid_results,
        "unique_task_ids": len(task_ids),
        "duplicate_task_ids": {
            key: count for key, count in sorted(task_ids.items()) if count > 1
        },
        "execution": _counter(execution),
        "verification": _counter(verification),
        "capture_meta": _counter(capture_meta),
        "capture_roots": {
            key: count for key, count in sorted(capture_roots.items())
        },
        "unique_capture_directories": len(seen_capture_dirs),
        "capture_states": _counter(capture_states),
        "response_codes": _counter(response_codes),
        "done_markers": _counter(done_markers),
        "disconnects": _counter(disconnects),
        "transport_errors": dict(transport_errors.most_common(20)),
        "trajectory_files": trajectory_files,
        "train_jsonl_files": train_files,
        "task_trajectory_files": [str(path) for path in task_trajectory_files],
        "task_trajectory_reports": [str(path) for path in reports],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize CyberGym results and captured API traffic"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--json", action="store_true", help="print machine-readable JSON only"
    )
    args = parser.parse_args(argv)
    report = analyze_run(args.run_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"run_dir: {report['run_dir']}")
    print(f"result_files: {report['result_files']}")
    print(f"unique_task_ids: {report['unique_task_ids']}")
    print(f"duplicate_task_ids: {report['duplicate_task_ids']}")
    for key in (
        "execution",
        "verification",
        "capture_meta",
        "capture_states",
        "response_codes",
        "done_markers",
        "disconnects",
    ):
        print(f"{key}: {report[key]}")
    print(f"unique_capture_directories: {report['unique_capture_directories']}")
    print(f"trajectory_files: {report['trajectory_files']}")
    print(f"train_jsonl_files: {report['train_jsonl_files']}")
    print(f"task_trajectory_files: {report['task_trajectory_files']}")
    print(f"task_trajectory_reports: {report['task_trajectory_reports']}")
    print("transport_errors:")
    for error, count in report["transport_errors"].items():
        print(f"  {count} {error}")
    if report["invalid_result_files"]:
        print(f"invalid_result_files: {report['invalid_result_files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
