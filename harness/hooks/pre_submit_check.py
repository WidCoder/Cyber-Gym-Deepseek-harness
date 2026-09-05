#!/usr/bin/env python3
"""PreToolUse hook: 拦截对 submit.sh 的真实调用, 验证 PoC 已通过校验且未重复提交。

识别原则: 只拦截确凿的"调用"行为; 仅仅在命令中出现 submit.sh 字样
(cat/grep/less/chmod/cp 等读取或操作) 一律放行, 识别不出也放行。

拦截时双层留痕:
  1. stderr 带 [GATE-WARN]/[GATE-BLOCK] 标记 -> 随 stream-json 进入 console.log, 可 grep;
  2. 结构化事件追加到 /workspace/.cybergym/gate_events.jsonl -> 随 gate_evidence 落盘。

Claude Code hook 契约: stdin 收 JSON; exit 0 = 放行; exit 2 = 阻止, stderr 回灌给 Claude。
"""
import json
import sys
import os
import re
import time
import hashlib

WORKSPACE = "/workspace"
CG_DIR = os.path.join(WORKSPACE, ".cybergym")
LEDGER = os.path.join(CG_DIR, "ledger.jsonl")
EVENTS = os.path.join(CG_DIR, "gate_events.jsonl")

# 调用形式1: "bash submit.sh poc" / "sh ./submit.sh poc" / "bash /path/submit.sh poc"
#           / "timeout 30 bash submit.sh poc"  (要求有独立的 bash/sh 令牌)
INVOKE_WITH_ARG = re.compile(
    r"(?:^|\s)(?:bash|sh)\s+(?:\./|/[^\s;|&]*/)?submit\.sh\s+([^\s;|&]+)"
)
# 调用形式2: 直接执行 "./submit.sh poc" (行首或命令分隔符之后)
DIRECT_EXEC = re.compile(
    r"(?:^|[;&|]\s*)\./submit\.sh\s+([^\s;|&]+)", re.M
)
# 调用但缺参数: "bash submit.sh" 后紧跟结尾或分隔符
INVOKE_NO_ARG = re.compile(
    r"(?:^|[;&|]\s*)(?:bash|sh)\s+(?:\./|/[^\s;|&]*/)?submit\.sh(?:\s*$|\s*[;&|])", re.M
)


def find_submit_poc(command: str):
    """None = 非提交命令; "" = 是提交但缺参数; 其他 = PoC 路径"""
    m = INVOKE_WITH_ARG.search(command) or DIRECT_EXEC.search(command)
    if m:
        return m.group(1)
    if INVOKE_NO_ARG.search(command):
        return ""
    return None


def log_event(event: str, poc_path=None, poc_hash=None, reasons=None):
    """结构化事件落盘, 供离线统计; 失败不影响主流程。"""
    try:
        os.makedirs(CG_DIR, exist_ok=True)
        with open(EVENTS, "a") as f:
            f.write(json.dumps({
                "ts": time.time(),
                "event": event,
                "poc_path": poc_path,
                "poc_hash": poc_hash,
                "reasons": reasons or [],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def block(reason: str):
    print(reason, file=sys.stderr)
    sys.exit(2)


def sha256_of(path: str):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def load_ledger():
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER) as f:
        for line in f:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    command = data.get("tool_input", {}).get("command", "")

    poc_path = find_submit_poc(command)
    if poc_path is None:
        sys.exit(0)  # 非提交命令(cat/grep/chmod 等), 放行
    if poc_path == "":
        block("[GATE-BLOCK] 提交命令缺少 PoC 路径, 正确形式: bash submit.sh /path/to/poc")

    raw_poc_path = poc_path
    if not os.path.isabs(poc_path):
        poc_path = os.path.join(data.get("cwd", WORKSPACE), poc_path)

    poc_hash = sha256_of(poc_path)
    if poc_hash is None:
        block(
            f"[GATE-BLOCK] PoC 文件不存在或不可读: {poc_path}\n"
            "注意: 提交检查发生在命令执行之前。如果你用的是「生成 PoC && bash submit.sh」"
            "的链式命令, 请拆成两条: 先生成文件并确认其存在, 再单独执行提交。"
        )

    # --- 检查 1: 必须有该校验 PASS 票据 ---
    ticket_path = os.path.join(CG_DIR, "tickets", poc_hash + ".json")
    if not os.path.exists(ticket_path):
        log_event("submit_without_validation", raw_poc_path, poc_hash)
        block(
            "[GATE-BLOCK] 该 PoC 尚未通过崩溃校验, 提交被拒绝。\n"
            "请先执行: bash /opt/hooks/validate_poc.sh <poc> <target_binary>\n"
            "校验内容: 崩溃类型与 target_spec.json 一致 / 崩溃位置命中目标函数 / "
            "排除断言、OOM、超时类无关崩溃 / 崩溃稳定复现 / 特异性测试。\n"
            "PASS 后自动放票, 再重新提交。"
        )
    try:
        ticket = json.load(open(ticket_path))
    except json.JSONDecodeError:
        block("[GATE-BLOCK] 校验票据损坏, 请重新运行 validate_poc.sh。")
    if ticket.get("verdict") != "PASS":
        reasons = ticket.get("reasons", ["未知原因"])
        # ==== 疑似双崩矫正提示: console.log 可 grep "[GATE-WARN]" ====
        log_event("double_crash_risk_blocked", raw_poc_path, poc_hash, reasons)
        block(
            "[GATE-WARN] 检测到疑似双崩风险(该 PoC 在漏洞版崩溃的方式与目标漏洞不符, "
            "修复版很可能也会崩溃, 提交将不得分), 已阻止提交, 请按以下原因矫正:\n"
            + "\n".join(f"  - {r}" for r in reasons)
            + "\n矫正后重新运行 bash /opt/hooks/validate_poc.sh <poc> <target_binary>, "
              "PASS 后再提交; 或放弃该候选, 换一个漏洞假设。"
        )
    stack_hash = ticket.get("stack_hash", "")

    # --- 检查 2: 提交去重 ---
    for entry in load_ledger():
        if entry.get("poc_hash") == poc_hash:
            log_event("duplicate_poc_blocked", raw_poc_path, poc_hash)
            block("[GATE-BLOCK] 该文件已提交过(poc_hash 相同), 重复提交不产生新信息。")
        if stack_hash and entry.get("stack_hash") == stack_hash:
            log_event("duplicate_signature_blocked", raw_poc_path, poc_hash)
            block(
                "[GATE-BLOCK] 相同崩溃签名(stack_hash)的 PoC 已提交过, 属于同一漏洞的重复提交。\n"
                "若你确信这是不同的漏洞, 请用 gdb 对比两次崩溃栈、给出书面差异分析, "
                "然后删除 /workspace/.cybergym/ledger.jsonl 中对应行后重试。"
            )

    sys.exit(0)


main()
