"""Run one task or a newline-delimited task list through the selected harness."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness_selector import main as run_harness


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=("claude", "deepseek", "opencode"), default=None)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--task-list", type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--tmp-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--max-iter", type=int, default=1000)
    parser.add_argument("--difficulty", default="level1")
    parser.add_argument("--remove-tmp", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    task_ids = list(args.task_id)
    if args.task_list:
        task_ids.extend(
            line.strip()
            for line in args.task_list.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not task_ids:
        raise SystemExit("provide --task-id or --task-list")
    if args.harness:
        os.environ["HARNESS_TYPE"] = args.harness
    failed = 0
    for task_id in task_ids:
        print(f"[CyberGym] starting harness={os.environ.get('HARNESS_TYPE', 'claude')} task={task_id}", flush=True)
        command = [
            "--image", args.image,
            "--model", args.model,
            "--log_dir", str(args.log_dir),
            "--tmp_dir", str(args.tmp_dir),
            "--data_dir", str(args.data_dir),
            "--task_id", task_id,
            "--server", args.server,
            "--timeout", str(args.timeout),
            "--max_iter", str(args.max_iter),
            "--difficulty", args.difficulty,
        ]
        command.append("--remove_tmp" if args.remove_tmp else "--no-remove_tmp")
        status = run_harness(command)
        print(f"[CyberGym] finished task={task_id} status={'ok' if status == 0 else 'failed'}", flush=True)
        if status != 0:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
