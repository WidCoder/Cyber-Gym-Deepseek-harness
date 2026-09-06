"""Container-side launcher for the preinstalled DeepSeek Harness CLI."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", required=True)
    parser.add_argument("--profile", default=os.getenv("DSH_PROFILE", "headless"))
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    args = parser.parse_args(argv)

    # Keep the CLI invocation in one tiny wrapper so the host adapter only
    # needs to mount this file. No package manager or network access is used.
    command = [
        os.getenv("DSH_BIN", "dsh"),
        "--profile",
        args.profile,
        "--patch",
        args.patch,
        "--prompt-file",
        args.prompt_file,
        "--timeout",
        str(args.timeout),
    ]
    try:
        completed = subprocess.run(command, cwd="/workspace", check=False)
    except OSError as exc:
        print(f"DeepSeek Harness could not be started: {exc}", file=sys.stderr)
        return 127
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
