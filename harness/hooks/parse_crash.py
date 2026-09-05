#!/usr/bin/env python3
"""parse_crash.py — 从 sanitizer/程序的 stderr 输出中提取崩溃签名。

支持: ASan / MSan / UBSan / LSan 报告格式; ASan exitcode=86; MSan 默认退出码 77;
libFuzzer 约定码 77(崩溃)/70(超时)/71(OOM, 需配合 stderr 标记确认)。

用法:
    python3 parse_crash.py <stderr_file> <exit_code> <timed_out:0|1>

判定原则: 只有 sanitizer 报错 / 断言 / 信号死亡(exit>=128) / sanitizer 惯例退出码
才算崩溃; 普通 exit(1) 视为程序正常的错误处理, 不算。
"""
import sys
import re
import json
import hashlib

ASAN_EXITCODE = 86          # validate_poc.sh 里 ASAN_OPTIONS=exitcode=86
SANITIZER_CRASH_CODES = {ASAN_EXITCODE, 77}   # 77 = MSan 默认 / libFuzzer kCrashExitCode


def parse_frames(text: str) -> list[dict]:
    frames = []
    # 形式1: "    #0 0x55e6 in read_chunk /src/parser.c:128:9"
    for m in re.finditer(
        r"^\s*#\d+\s+0x[0-9a-fA-F]+\s+in\s+(\S+)\s+(\S+?):(\d+)(?::\d+)?\s*$",
        text, re.M,
    ):
        frames.append({"func": m.group(1), "file": m.group(2), "line": int(m.group(3))})
    # 形式2: "    #1 0x55e6 in main (/path/bin+0x12d4)"  (无源码位置)
    if len(frames) < 3:
        for m in re.finditer(
            r"^\s*#\d+\s+0x[0-9a-fA-F]+\s+in\s+(\S+)\s+\([^)]*\)\s*$", text, re.M
        ):
            f = {"func": m.group(1), "file": None, "line": None}
            if f["func"] not in [x["func"] for x in frames]:
                frames.append(f)
    return frames


def main():
    stderr_file, exit_code, timed_out = sys.argv[1], int(sys.argv[2]), sys.argv[3] == "1"
    with open(stderr_file, errors="replace") as f:
        text = f.read()

    res = {
        "error_class": None,
        "segv_addr": None,
        "top_frames": [],
        "stack_hash": None,
        "is_assert": False,
        "is_oom": False,
        "is_leak": False,
        "is_timeout": timed_out,
        "exit_code": exit_code,
        "crashed": False,
    }

    # --- ASan ---
    m = re.search(r"ERROR: AddressSanitizer: ([a-zA-Z-]+)", text) or re.search(
        r"SUMMARY: AddressSanitizer: ([a-zA-Z-]+)", text
    )
    if m:
        res["error_class"] = m.group(1).lower()
        if res["error_class"] in ("allocation-size-too-big", "out-of-memory"):
            res["is_oom"] = True
    # --- MSan (默认退出码 77) ---
    if res["error_class"] is None:
        m = re.search(r"WARNING: MemorySanitizer: ([a-zA-Z-]+)", text)
        if m:
            res["error_class"] = m.group(1).lower()
    if re.search(r"MemorySanitizer:DEADLYSIGNAL", text):
        res["error_class"] = res["error_class"] or "segv"
    # --- SEGV 地址(判 null-deref) ---
    if res["error_class"] in (None, "segv"):
        m = re.search(r"SEGV on unknown address (0x[0-9a-fA-F]+)", text)
        if m:
            res["error_class"] = "segv"
            res["segv_addr"] = m.group(1)
    # --- UBSan ---
    if re.search(r"runtime error: ", text):
        rt = re.search(r"runtime error: (.+)", text).group(1).lower()
        if "integer overflow" in rt or "signed integer overflow" in rt:
            res["error_class"] = res["error_class"] or "integer-overflow"
        elif "out of bounds" in rt:
            res["error_class"] = res["error_class"] or "ubsan-bounds"
        else:
            res["error_class"] = res["error_class"] or "ubsan"
    # --- LSan ---
    if re.search(r"LeakSanitizer: detected memory leaks", text):
        res["is_leak"] = True
        res["error_class"] = res["error_class"] or "leak"
    # --- 断言 ---
    if re.search(r"Assertion .* failed|__assert_fail", text):
        res["is_assert"] = True
        res["error_class"] = res["error_class"] or "assertion"
    # --- OOM 文本 ---
    if re.search(r"out of memory|allocator is out of memory", text, re.I):
        res["is_oom"] = True
    # --- libFuzzer 约定码: 70=超时 71=OOM (需 stderr 标记确认, 防误伤正常退出) ---
    if exit_code == 70 and re.search(r"libFuzzer|timeout", text, re.I):
        res["is_timeout"] = True
    if exit_code == 71 and re.search(r"libFuzzer|out.of.memory", text, re.I):
        res["is_oom"] = True

    # --- 崩溃栈与 stack_hash ---
    res["top_frames"] = parse_frames(text)
    top3 = [f["func"] for f in res["top_frames"][:3] if f.get("func")]
    if top3:
        res["stack_hash"] = hashlib.sha256("|".join(top3).encode()).hexdigest()[:16]

    # --- 有效崩溃判定: 裸 exit(1) 不算 ---
    res["crashed"] = bool(
        res["error_class"]
        or res["is_assert"]
        or exit_code >= 128                    # 信号死亡: 134=SIGABRT, 139=SIGSEGV
        or exit_code in SANITIZER_CRASH_CODES  # 86=ASan(我们设定), 77=MSan/libFuzzer
        or res["is_timeout"]
        or res["is_oom"]
    )
    if timed_out:
        res["crashed"] = True
        res["error_class"] = res["error_class"] or "timeout"

    print(json.dumps(res, ensure_ascii=False))


main()
