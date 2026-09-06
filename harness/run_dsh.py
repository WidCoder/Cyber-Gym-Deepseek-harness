"""Container-side launcher for the preinstalled DeepSeek Harness CLI."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", required=True)
    parser.add_argument("--profile", default=os.getenv("DSH_PROFILE", "headless"))
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    args = parser.parse_args(argv)

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    # `--prompt-file` and `--timeout` belong to this wrapper. The headless DSH
    # profile accepts the task as positional text, while timeout is enforced
    # by the standard system timeout command.
    command = [
        "/usr/bin/timeout",
        "-k",
        "30s",
        str(args.timeout),
        os.getenv("DSH_BIN", "dsh"),
        "--patch",
        args.patch,
        "--profile",
        args.profile,
        prompt,
    ]
    try:
        completed = subprocess.run(command, cwd="/workspace", check=False)
    except OSError as exc:
        print(f"DeepSeek Harness could not be started: {exc}", file=sys.stderr)
        return 127
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
