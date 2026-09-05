"""CyberGym adapter for the preinstalled OpenCode CLI."""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

import docker

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.base import PROMPT, finish_task, prepare_task, save_timing
from cybergym.task.types import TaskDifficulty

logger = logging.getLogger(__name__)
DEFAULT_IMAGE = "cybergym-opencode:claude-v1"
DEFAULT_MODEL = "deepseek-v4-flash"


def _api_config() -> tuple[str, str]:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for OpenCode")
    return key, os.getenv(
        "OPENCODE_BASE_URL",
        os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def run_agent(
    image: str,
    model: str,
    task_id: str,
    data_dir: Path,
    log_dir: Path,
    tmp_dir: Path,
    timeout: int,
    *,
    server: str,
    difficulty: TaskDifficulty = TaskDifficulty.level1,
    max_iter: int = 1000,
    remove_tmp: bool = True,
) -> str | None:
    del max_iter
    image = os.getenv("OPENCODE_IMAGE", image or DEFAULT_IMAGE)
    model = os.getenv("OPENCODE_MODEL") or DEFAULT_MODEL
    if "/" not in model:
        model = f"openai/{model}"
    api_key, base_url = _api_config()
    ctx, _ = prepare_task(
        task_id=task_id,
        data_dir=data_dir,
        tmp_dir=tmp_dir,
        log_root=log_dir,
        server=server,
        difficulty=difficulty,
        agent_name="opencode",
        model=model,
    )
    logs_dir = ctx.log_dir / "logs"
    console = ctx.log_dir / "console.log"
    start = time.time()
    status_code = 1
    container = None
    command = [
        "/usr/bin/timeout",
        "-k",
        "30s",
        str(timeout),
        "opencode",
        "run",
        "--model",
        model,
        "--format",
        "json",
        PROMPT,
    ]
    env = {
        "DEBUG": "1",
        "IS_SANDBOX": "1",
        "DEEPSEEK_API_KEY": api_key,
        "OPENAI_API_KEY": api_key,
        "OPENAI_BASE_URL": base_url,
        "OPENCODE_DISABLE_UPDATE_CHECK": "1",
    }
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        if os.getenv(name):
            env[name] = os.environ[name]
    try:
        client = docker.from_env()
        container = client.containers.run(
            image,
            command=command,
            entrypoint="",
            name=f"opencode-{ctx.agent_id}",
            environment=env,
            working_dir="/workspace",
            user="root",
            volumes={
                str(ctx.input_dir): {"bind": "/workspace", "mode": "rw"},
                str(logs_dir): {"bind": "/logs", "mode": "rw"},
            },
            detach=True,
        )
        with console.open("wb") as stream:
            for line in container.logs(stream=True, follow=True, stdout=True, stderr=True):
                stream.write(line)
                stream.flush()
        status_code = container.wait().get("StatusCode", 1)
    except Exception as exc:
        logger.exception("Container OpenCode harness failed: %s", exc)
        console.write_text(f"harness error: {exc}\n", encoding="utf-8")
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                logger.exception("Failed to remove OpenCode container")
        save_timing(ctx, start, status_code)
    if status_code != 0:
        if remove_tmp:
            import shutil

            shutil.rmtree(ctx.input_dir, ignore_errors=True)
        return None
    return finish_task(ctx, remove_tmp=remove_tmp)


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", "--image_name", dest="image", default=DEFAULT_IMAGE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--log_dir", type=Path, required=True)
    parser.add_argument("--tmp_dir", type=Path, required=True)
    parser.add_argument("--data_dir", type=Path, required=True)
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--max_iter", type=int, default=1000)
    parser.add_argument("--difficulty", default="level1")
    parser.add_argument("--remove_tmp", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    agent_id = run_agent(
        args.image, args.model, args.task_id, args.data_dir, args.log_dir, args.tmp_dir,
        args.timeout, server=args.server, difficulty=TaskDifficulty(args.difficulty),
        max_iter=args.max_iter, remove_tmp=args.remove_tmp,
    )
    return 0 if agent_id else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    raise SystemExit(main())
