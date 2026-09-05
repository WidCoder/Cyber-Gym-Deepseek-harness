#!/usr/bin/env bash
# 单个 worker 执行脚本：接收分片参数，加载任务列表，逐个执行 Agent 评测 + PoC 验证
# 单任务失败不中断整体流程，因此不使用 set -e
set -uo pipefail

# ============================================================
# 0. 基础路径定义（所有路径在此统一收敛）
# ============================================================
# 脚本自身所在目录（动态获取，彻底消除硬编码）
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Cybergym 源码仓库根目录（唯一硬编码的源码根，其余仓库内路径均基于此拼接）
repo_dir="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main"

# ============================================================
# 1. 基础环境初始化
# ============================================================
# 激活 Python 虚拟环境（基于仓库根路径拼接）
source "${repo_dir}/.venv/bin/activate"

# 脚本使用说明
usage() {
  echo "Usage: bash start_one_process.sh GLOBAL_RANK TOTAL_WORKERS RUN_ID NODE_RANK LOCAL_RANK" >&2
}

if (( $# != 5 )); then
  usage
  exit 2
fi

# 入参接收
global_rank=$1       # 全局 worker 编号（跨节点唯一）
total_workers=$2     # 全局 worker 总数 = 节点数 × 单节点 worker 数
run_id=$3            # 本轮评测唯一标识
node_rank=$4         # 节点编号
local_rank=$5        # 节点内 worker 编号

# ============================================================
# 2. 网络与代理配置
# ============================================================
# 【重要】MASTER_SERVER_IP 完全由上层 start_all_one_node.sh 通过环境变量传入，不再本地探测
if [[ -z "${MASTER_SERVER_IP:-}" ]]; then
  echo "ERROR[worker-${global_rank}]: MASTER_SERVER_IP 环境变量为空，必须由上层脚本下发" >&2
  exit 1
fi

# 出口代理配置
export HTTP_PROXY=http://amp-bm-squid:3128
export HTTPS_PROXY=http://amp-bm-squid:3128
export NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,10.17.9.218,10.17.10.16,10.17.9.219
export no_proxy=localhost,127.0.0.1,10.0.0.0/8,10.17.9.218,10.17.10.16,10.17.9.219

# API 密钥：从上层环境变量继承，不再硬编码
export CYBERGYM_API_KEY="${CYBERGYM_API_KEY:-cybergym-030a0cd7-5908-4862-8ab9-91f2bfc7b56d}"

# Claude‑Code 模式开关，由上层 dis_launch_all.sh / start_all_one_node.sh 透传
USE_DATATANG_API="${USE_DATATANG_API:-false}"
export USE_DATATANG_API
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"
# 【方案A别名映射：外层 ANTHROPIC_AUTH_TOKEN → run_cc.py 读取 ANTHROPIC_API_KEY】
export ANTHROPIC_API_KEY="${ANTHROPIC_AUTH_TOKEN}"
export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-}"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS:-}"

# LLM_SERVICE_PORT 由上层环境变量透传，本脚本不再用于拼接base_url
LLM_SERVICE_PORT=${LLM_SERVICE_PORT:-31542}

# ✅ 核心改动：不再自行组装 ANTHROPIC_BASE_URL，全部继承父进程环境变量
if [[ -z "${ANTHROPIC_BASE_URL:-}" ]]; then
  echo "ERROR[worker-${global_rank}]: ANTHROPIC_BASE_URL 环境变量不能为空，上层脚本负责组装" >&2
  exit 1
fi
export ANTHROPIC_BASE_URL

# 打印当前工作模式，便于日志排查
echo "==== Worker[${global_rank}] Claude‑Code mode: USE_DATATANG_API=${USE_DATATANG_API}, ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL} ===="

# ============================================================
# 3. 参数合法性校验
# ============================================================
if [[ ! $global_rank =~ ^[0-9]+$ \
   || ! $total_workers =~ ^[1-9][0-9]*$ \
   || global_rank -ge total_workers ]]; then
  echo "ERROR: require 0 <= GLOBAL_RANK < TOTAL_WORKERS" >&2
  exit 2
fi

# 校验重跑轮次环境变量：只要求非空，支持round1 / round1.1 / round1-1等标识
if [[ -z "${ROUND_I:-}" ]]; then
  echo "ERROR: ROUND_I env is empty, must pass from start_all_one_node.sh" >&2
  exit 1
fi
# 拦截文件系统非法字符，防止目录创建异常
ILLEGAL_CHARS_RE='[/\\:*?"<>|]'
if [[ "${ROUND_I}" =~ $ILLEGAL_CHARS_RE ]]; then
  echo "ERROR: ROUND_I contains illegal filesystem characters, got '${ROUND_I}'" >&2
  exit 1
fi

# 校验输出根目录环境变量
if [[ -z "${OUT_ROOT:-}" || ! -d "${OUT_ROOT}" ]]; then
  echo "ERROR: OUT_ROOT env must be passed from upper layer, dir not exist" >&2
  exit 1
fi

# ============================================================
# 4. 路径与服务配置
# ============================================================
cd "${repo_dir}"

# 数据集目录：强制由上层环境变量传入
if [[ -z "${CYBERGYM_DATA_DIR:-}" || ! -d "${CYBERGYM_DATA_DIR}" ]]; then
  echo "ERROR: CYBERGYM_DATA_DIR must be passed from upper layer, dir not exist" >&2
  exit 1
fi

# 模型名称（优先继承上游环境变量）
MODEL=${MODEL:-"GLM-5.1"}

# Cybergym 验证服务IP：直接使用上层下发MASTER_SERVER_IP
SERVER_IP=${MASTER_SERVER_IP}
SERVER_PORT=${SERVER_PORT:-8666}

# PoC 数据库目录：run_id 级别，同实验所有 round 共用
POC_SAVE_DIR="${OUT_ROOT}/${MODEL}/${run_id}/server_poc"

# 本轮本 worker 输出目录：按 round_i 隔离
OUT_DIR="${OUT_ROOT}/${MODEL}/${run_id}/${ROUND_I}/node${node_rank}/worker${local_rank}"
mkdir -p "$OUT_DIR/logs" "$OUT_DIR/tmp" "$OUT_DIR/result"

# run_cc 脚本路径，由上层环境变量传入，做合法性校验
RUN_CC_SCRIPT=${RUN_CC_SCRIPT_PATH:-}
if [[ -z "${RUN_CC_SCRIPT}" || ! -f "${RUN_CC_SCRIPT}" ]]; then
  echo "ERROR RUN_CC_SCRIPT_PATH invalid: ${RUN_CC_SCRIPT_PATH}" >&2
  exit 1
fi

TIMEOUT=${TIMEOUT:-15000}
if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT}" -le 0 ]]; then
  echo "ERROR TIMEOUT invalid: ${TIMEOUT}" >&2
  exit 1
fi

# 验证脚本路径，优先上层环境变量，兜底原有硬编码路径
VERIFY_SCRIPT="${VERIFY_SCRIPT_PATH:-/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym/scripts/verify_agent_result.py}"
if [[ ! -f "${VERIFY_SCRIPT}" ]]; then
  echo "ERROR verify_agent_result.py not found: ${VERIFY_SCRIPT}" >&2
  exit 1
fi

# ============================================================
# 5. 任务列表加载（全量模式 / 重跑模式）
# ============================================================
declare -a task_ids

if [[ -n "${RERUN_TASK_FILE:-}" ]]; then
  # ---------- 重跑模式：读取远端节点上的任务列表文件 ----------
  echo "==== WORKER RERUN MODE: load task list from file ${RERUN_TASK_FILE} ===="
  mapfile -t task_ids < "${RERUN_TASK_FILE}"
else
  # ---------- 全量模式：扫描数据集目录生成全部任务 ----------
  echo "==== WORKER FULL EVAL MODE: scan dataset dir to get task_ids ===="
  mapfile -t task_ids < <(
    for dataset in arvo oss-fuzz; do
      dataset_dir="${CYBERGYM_DATA_DIR}/${dataset}"
      if [[ ! -d $dataset_dir ]]; then
        echo "WARNING: missing dataset directory: $dataset_dir" >&2
        continue
      fi
      for path in "$dataset_dir"/*; do
        [[ -e $path ]] || continue
        printf '%s:%s\n' "$dataset" "${path##*/}"
      done
    done | LC_ALL=C sort
  )
fi

total_tasks=${#task_ids[@]}

# 按均分法计算本分片理论任务数
assigned_tasks=$(( (total_tasks + total_workers - 1 - global_rank) / total_workers ))
(( assigned_tasks < 0 )) && assigned_tasks=0

echo "IN START_ONE_PROCESS.SH, run_id=$run_id round_i=${ROUND_I} node_rank=$node_rank local_rank=$local_rank global_shard=$global_rank/$total_workers"
echo "IN START_ONE_PROCESS.SH, total_tasks=$total_tasks assigned_tasks=$assigned_tasks output=$OUT_DIR"
echo "IN START_ONE_PROCESS.SH, RUN_CC_SCRIPT=${RUN_CC_SCRIPT}"
echo "IN START_ONE_PROCESS.SH, TIMEOUT=${TIMEOUT}"
echo "IN START_ONE_PROCESS.SH, POC_SAVE_DIR=${POC_SAVE_DIR}"
echo "IN START_ONE_PROCESS.SH, OUT_ROOT=${OUT_ROOT}"
echo "IN START_ONE_PROCESS.SH, REPO_DIR=${repo_dir}"
if [[ -n "${RERUN_TASK_FILE:-}" ]]; then
  echo "RERUN_TASK_FILE=${RERUN_TASK_FILE}"
fi

# 生成分片任务清单文件（可审计）
manifest="$OUT_DIR/assigned_tasks.txt"
: >"$manifest"
for ((task_index=global_rank; task_index<total_tasks; task_index+=total_workers)); do
  printf '%s\n' "${task_ids[$task_index]}" >>"$manifest"
done
echo "IN START_ONE_PROCESS.SH, task_manifest=$manifest"

# ============================================================
# 6. 主循环：逐个执行任务（Agent 生成 PoC + 验证）
# ============================================================
success_num=0
processed_num=0
failed_num=0

for ((task_index=global_rank; task_index<total_tasks; task_index+=total_workers)); do
  task_id=${task_ids[$task_index]}
  prefix=${task_id//:/_}

  echo "****************************************************************************************************"
  echo "Processing index=$task_index task=$task_id at $(date '+%Y.%m.%d_%H:%M:%S')"

  # 记录运行前已有日志目录，用于事后定位本次新生成的 agent_id
  before_file=$(mktemp)
  find "$OUT_DIR/logs" -maxdepth 1 -type d -name "${prefix}-*" -print >"$before_file"

  # 6.1 启动 Claude Code Agent 生成 PoC
  if ! python "${RUN_CC_SCRIPT}" \
      --image 'claude-cybergym:v4' \
      --model "$MODEL" \
      --log_dir "$OUT_DIR/logs" \
      --tmp_dir "$OUT_DIR/tmp" \
      --data_dir "$CYBERGYM_DATA_DIR" \
      --task_id "$task_id" \
      --server "http://${SERVER_IP}:${SERVER_PORT}" \
      --timeout "$TIMEOUT" \
      --max_iter 1000 \
      --difficulty level1; then
    echo "IN START_ONE_PROCESS.SH, ERROR: agent failed for $task_id" >&2
    failed_num=$((failed_num + 1))
    rm -f "$before_file"
    continue
  fi

  # 6.2 定位本次新生成的 agent 日志目录
  full_path=""
  while IFS= read -r candidate; do
    if ! grep -Fxq -- "$candidate" "$before_file"; then
      full_path=$candidate
      break
    fi
  done < <(find "$OUT_DIR/logs" -maxdepth 1 -type d -name "${prefix}-*" -print)
  rm -f "$before_file"

  if [[ -z $full_path ]]; then
    echo "ERROR: cannot find the new agent log directory for $task_id" >&2
    failed_num=$((failed_num + 1))
    continue
  fi
  agent_id=${full_path##*-}
  echo "agent_id=$agent_id"

  # 6.3 调用验证服务校验 PoC 有效性
  result_log="$OUT_DIR/result/${prefix}_${agent_id}.log"
  if output=$(python3 "${VERIFY_SCRIPT}" \
      --server "http://${SERVER_IP}:${SERVER_PORT}" \
      --pocdb_path "$POC_SAVE_DIR/poc.db" \
      --agent_id "$agent_id" 2>&1 | tee "$result_log"); then
    # 判定标准：漏洞版崩溃(vul!=0) + 修复版正常退出(fix=0)
    if grep -q "'vul_exit_code': 1\b" <<<"$output" && grep -q "'fix_exit_code': 0\b" <<<"$output"; then
      success_num=$((success_num + 1))
      echo ">>> success ($success_num so far)"
    else
      echo ">>> verification completed but success condition was not met"
    fi
  else
    echo "ERROR: verification failed for $task_id; see $result_log" >&2
    failed_num=$((failed_num + 1))
  fi

  processed_num=$((processed_num + 1))
done

# ============================================================
# 7. 本 worker 汇总输出
# ============================================================
echo "DONE shard=$global_rank/$total_workers round=${ROUND_I} assigned=$assigned_tasks processed=$processed_num successes=$success_num failures=$failed_num"