"""CyberGym adapter for the preinstalled OpenCode CLI."""

from __future__ import annotations

import argparse
import json
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
from harness.provider import resolve_llm_config
from cybergym.task.types import TaskDifficulty

logger = logging.getLogger(__name__)
DEFAULT_IMAGE = "cybergym-opencode:claude-v1"
DEFAULT_MODEL = "deepseek-v4-flash"


def _write_opencode_config(path: Path, model: str, base_url: str) -> None:
    """Register an arbitrary OpenAI-compatible model without storing a secret."""
    provider, model_id = model.split("/", 1)
    config = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            provider: {
                "options": {"baseURL": base_url},
                "models": {model_id: {"name": model_id}},
            }
        },
    }
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


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
    config = resolve_llm_config()
    if config.provider == "anthropic":
        raise RuntimeError("OpenCode adapter requires an OpenAI-compatible API")
    model = os.getenv("OPENCODE_MODEL") or os.getenv("LLM_MODEL") or model or DEFAULT_MODEL
    if "/" not in model:
        model = f"{os.getenv('OPENCODE_PROVIDER', 'openai')}/{model}"
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
    opencode_config = ctx.log_dir / "opencode.json"
    _write_opencode_config(opencode_config, model, config.base_url)
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
        config.api_key_env: config.api_key,
        "OPENAI_API_KEY": config.api_key,
        "OPENAI_BASE_URL": config.base_url,
        "OPENCODE_BASE_URL": config.base_url,
        "LLM_PROVIDER": config.provider,
        "LLM_API_FORMAT": config.api_format,
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
                str(opencode_config): {
                    "bind": "/root/.config/opencode/opencode.json",
                    "mode": "ro",
                },
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
        opencode_config.unlink(missing_ok=True)
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
