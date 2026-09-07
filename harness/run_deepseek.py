from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import docker

# The worker starts this file by absolute path from the CyberGym repository.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.base import PROMPT, finish_task, prepare_task, save_timing
from harness.provider import resolve_llm_config
from harness.result import write_result
from cybergym.task.types import TaskDifficulty

logger = logging.getLogger(__name__)

DEFAULT_DEEPSEEK_IMAGE = "cybergym-deepseek:claude-v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DSH_PROFILE = "headless"


def _yaml_string(value: str) -> str:
    """Use JSON quoting, which is also valid YAML, for generated scalar values."""
    return json.dumps(value, ensure_ascii=True)


def _provider_config() -> tuple[str, str, str, str, str]:
    config = resolve_llm_config()
    return config.provider, config.api_key, config.base_url, config.api_format, config.api_key_env


def _build_dsh_patch(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_format: str,
    api_key_env: str,
    log_dir: str,
) -> str:
    route = "deepseek-official" if provider == "deepseek" else f"cybergym-{provider}"
    lines = [
        "# Generated for one CyberGym task; do not put secrets in this file.",
        "- id: agent-default-model",
        "  config:",
        f"    provider: {_yaml_string(route)}",
        f"    model: {_yaml_string(model)}",
        "- id: session-persistence-jsonl",
        "  config:",
        f"    root: {_yaml_string(log_dir + '/sessions')}",
    ]

    if provider == "deepseek":
        reasoning = os.getenv(
            "DSH_REASONING_EFFORT",
            os.getenv("LLM_REASONING_EFFORT", "high"),
        ).lower()
        if reasoning not in {"off", "low", "high", "max"}:
            raise RuntimeError(
                "DSH_REASONING_EFFORT must be one of off, low, high, max"
            )
        lines.extend(
            [
                "- id: llm-deepseek",
                "  config:",
                f"    apiKeyEnv: {_yaml_string(api_key_env)}",
                f"    baseURL: {_yaml_string(base_url)}",
                "    thinking: enabled",
                f"    reasoningEffort: {_yaml_string(reasoning)}",
            ]
        )
    else:
        lines.extend(
            [
                "- id: llm-pi-ai",
                "  config:",
                "    providers:",
                f"      cybergym-{provider}:",
                f"        apiKeyEnv: {_yaml_string(api_key_env)}",
                f"        api: {_yaml_string(api_format)}",
                f"        baseURL: {_yaml_string(base_url)}",
                "        models:",
                f"          - id: {_yaml_string(model)}",
                "        defaultContextWindow: 262144",
                "        defaultMaxTokens: 32768",
            ]
        )
    return "\n".join(lines) + "\n"


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
    del max_iter  # The official headless runner owns its loop termination policy.
    configured_image = os.getenv("DEEPSEEK_IMAGE")
    if configured_image:
        image = configured_image
    elif not image or image in {
        "claude-cybergym:v4",
        "claude-code:2.1.89",
        "claude-code-vim:latest",
    }:
        # The outer legacy worker may still pass the Claude image. Keep the
        # harness choice local so that orchestration scripts remain unchanged.
        image = DEFAULT_DEEPSEEK_IMAGE
    provider, api_key, base_url, api_format, api_key_env = _provider_config()
    dsh_profile = os.getenv("DSH_PROFILE", DEFAULT_DSH_PROFILE)
    model = os.getenv("LLM_MODEL") or (
        os.getenv("DEEPSEEK_MODEL") if provider == "deepseek" else None
    ) or model or DEFAULT_DEEPSEEK_MODEL

    ctx, _ = prepare_task(
        task_id=task_id,
        data_dir=data_dir,
        tmp_dir=tmp_dir,
        log_root=log_dir,
        server=server,
        difficulty=difficulty,
        agent_name="deepseek-dsh",
        model=model,
    )
    logs_dir = ctx.log_dir / "logs"
    console = ctx.log_dir / "console.log"
    prompt_file = logs_dir / "prompt.txt"
    patch_file = logs_dir / "dsh-runtime.patch.yml"
    inner_script = ROOT / "harness" / "run_dsh.py"
    prompt_file.write_text(PROMPT, encoding="utf-8")
    patch_file.write_text(
        _build_dsh_patch(
            provider=provider,
            model=model,
            base_url=base_url,
            api_format=api_format,
            api_key_env=api_key_env,
            log_dir="/logs",
        ),
        encoding="utf-8",
    )

    start = time.time()
    status_code = 1
    container = None
    container_env = {
        "DEBUG": "1",
        "IS_SANDBOX": "1",
        "DSH_PROFILE": dsh_profile,
        "DSH_TELEMETRY_DISABLED": "1",
        # Docker is already the task isolation boundary. Avoid an interactive
        # approval prompt inside the non-interactive CyberGym worker.
        "DSH_PERMISSION_MODE": "danger-full-access",
        "DSH_TOOLS_MODE": "native",
        "LLM_PROVIDER": provider,
        "LLM_API_FORMAT": api_format,
        api_key_env: api_key,
    }
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        if os.getenv(name):
            container_env[name] = os.environ[name]

    command = [
        "python3",
        "/opt/cybergym/run_dsh.py",
        "--profile",
        dsh_profile,
        "--patch",
        "/logs/dsh-runtime.patch.yml",
        "--prompt-file",
        "/logs/prompt.txt",
        "--timeout",
        str(timeout),
    ]

    try:
        if not inner_script.is_file():
            raise RuntimeError(f"container DSH runner not found: {inner_script}")

        client = docker.from_env()
        container = client.containers.run(
            image,
            command=command,
            entrypoint="",
            name=f"deepseek-dsh-{ctx.agent_id}",
            environment=container_env,
            working_dir="/workspace",
            user="root",
            volumes={
                str(ctx.input_dir): {"bind": "/workspace", "mode": "rw"},
                str(logs_dir): {"bind": "/logs", "mode": "rw"},
                str(inner_script): {
                    "bind": "/opt/cybergym/run_dsh.py",
                    "mode": "ro",
                },
            },
            detach=True,
        )
        with console.open("wb") as stream:
            for line in container.logs(stream=True, follow=True, stdout=True, stderr=True):
                stream.write(line)
                stream.flush()
        result = container.wait()
        status_code = result.get("StatusCode", 1)
    except Exception as exc:
        logger.exception("Container DSH harness failed: %s", exc)
        console.write_text(f"harness error: {exc}\n", encoding="utf-8")
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                logger.exception("Failed to remove DSH container")
        save_timing(ctx, start, status_code)
        try:
            write_result(
                ctx.log_dir,
                harness="deepseek",
                model=model,
                image=image,
                provider=provider,
                api_format=api_format,
                llm_base_url=base_url,
                cybergym_server=server,
                status_code=status_code,
            )
        except Exception:
            logger.exception("Failed to write structured task result")

    if status_code != 0:
        if remove_tmp:
            from shutil import rmtree

            rmtree(ctx.input_dir, ignore_errors=True)
        return None
    return finish_task(ctx, remove_tmp=remove_tmp)


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", "--image_name", dest="image", default=DEFAULT_DEEPSEEK_IMAGE)
    parser.add_argument("--model", default=DEFAULT_DEEPSEEK_MODEL)
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
        args.image,
        args.model,
        args.task_id,
        args.data_dir,
        args.log_dir,
        args.tmp_dir,
        args.timeout,
        server=args.server,
        difficulty=TaskDifficulty(args.difficulty),
        max_iter=args.max_iter,
        remove_tmp=args.remove_tmp,
    )
    return 0 if agent_id else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    raise SystemExit(main())

