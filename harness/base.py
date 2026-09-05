"""Small shared task/lifecycle helpers for non-Claude harness adapters."""

from __future__ import annotations

import shutil
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

repo_dir = os.getenv("REPO_DIR")
if repo_dir and repo_dir not in sys.path:
    sys.path.insert(0, repo_dir)

from cybergym.task.gen_task import generate_task
from cybergym.task.types import TaskConfig, TaskDifficulty
from cybergym.utils import save_json

from harness.prompt import PROMPT


@dataclass
class TaskContext:
    agent_id: str
    input_dir: Path
    log_dir: Path


def prepare_task(
    *,
    task_id: str,
    data_dir: Path,
    tmp_dir: Path,
    log_root: Path,
    server: str,
    difficulty: TaskDifficulty,
    agent_name: str,
    model: str,
) -> tuple[TaskContext, object]:
    agent_id = uuid4().hex
    tmp_dir = tmp_dir.absolute()
    log_root = log_root.absolute()
    input_dir = tmp_dir / f"{task_id.replace(':', '_')}-{agent_id}"
    log_dir = log_root / input_dir.name
    input_dir.mkdir(parents=True, exist_ok=False)
    log_dir.mkdir(parents=True, exist_ok=False)
    (log_dir / "logs").mkdir()

    task = generate_task(
        TaskConfig(
            task_id=task_id,
            out_dir=input_dir,
            data_dir=data_dir,
            server=server,
            difficulty=difficulty,
            agent_id=agent_id,
        )
    )
    save_json(
        {
            "agent": f"{agent_name}:{model}",
            "task": task,
            "task_args": {
                "task_id": task_id,
                "data_dir": str(data_dir),
                "server": server,
                "difficulty": difficulty.value,
            },
        },
        log_dir / "args.json",
        indent=2,
    )
    return TaskContext(agent_id, input_dir, log_dir), task


def finish_task(ctx: TaskContext, *, remove_tmp: bool) -> str | None:
    console = ctx.log_dir / "console.log"
    logs = ctx.log_dir / "logs"
    valid = console.is_file() and console.stat().st_size > 0
    valid = valid or any(path.is_file() for path in logs.rglob("*"))
    if remove_tmp:
        shutil.rmtree(ctx.input_dir, ignore_errors=True)
    return ctx.agent_id if valid else None


def save_timing(ctx: TaskContext, start: float, status_code: int) -> None:
    end = time.time()
    save_json(
        {
            "start_time": start,
            "end_time": end,
            "time_cost_sec": round(end - start, 2),
            "status_code": status_code,
        },
        ctx.log_dir / "timing.json",
        indent=2,
    )
