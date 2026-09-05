"""Single stable entry point for Claude, DeepSeek Harness, and OpenCode."""

from __future__ import annotations

import os
import sys


repo_dir = os.getenv("REPO_DIR")
if repo_dir and repo_dir not in sys.path:
    sys.path.insert(0, repo_dir)


def _selected_args(argv):
    args = list(sys.argv[1:] if argv is None else argv)
    for flag in ("--harness", "--harness-type"):
        if flag in args:
            index = args.index(flag)
            if index + 1 >= len(args):
                raise SystemExit(f"{flag} requires claude, deepseek, or opencode")
            os.environ["HARNESS_TYPE"] = args[index + 1]
            del args[index : index + 2]
            break
    return args


def main(argv=None) -> int:
    args = _selected_args(argv)
    if any(arg in {"-h", "--help"} for arg in args):
        print("usage: harness_selector.py [--harness claude|deepseek|opencode] <runner args>")
        return 0
    harness = os.getenv("HARNESS_TYPE", "claude").strip().lower()
    if harness == "claude":
        from harness.run_cc_v9 import main as runner
    elif harness in {"deepseek", "dsh"}:
        from harness.run_deepseek import main as runner
    elif harness == "opencode":
        from harness.run_opencode import main as runner
    else:
        raise SystemExit("HARNESS_TYPE must be claude, deepseek, or opencode")
    return runner(args)


if __name__ == "__main__":
    raise SystemExit(main())
