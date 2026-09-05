#!/usr/bin/env bash
set -euo pipefail

# -------------------------- 初始化变量默认值 --------------------------
node_rank=""
num_nodes=""
processes_per_node=""
exp=""
model=""
port=""
run_cc_script_path=""
rerun_task_file=""
cybergym_data_dir=""
out_root=""
round_i=""
timeout=""

usage() {
  cat <<'EOF'
Usage: bash start_all_one_node.sh [OPTIONS]

单节点启动CyberGym验证服务 + 一组worker进程

Options:
    --node-rank INT              当前节点rank(从0开始) (必填)
    --num-nodes INT              集群总节点数 (必填)
    --processes-per-node INT     当前节点并发worker数量 (必填)
    --exp TEXT                   实验run_id (必填)
    --model TEXT                 模型名称 (必填)
    --port INT                   LLM服务端口 (必填)
    --run-cc-script-path FILE    run_cc.py完整路径 (必填)
    --cybergym-data-dir DIR      Cybergym评测数据集根目录 (必填)
    --out-root DIR               评测结果输出根目录 (必填)
    --round-i TEXT               重跑轮次标识，支持 1 / 1.1 / 1-1 (必填)              重跑轮次数字编号，例如 1 (必填)
    --rerun-task-file FILE       远端重跑任务文件，可选
    -h,--help                    帮助

Example:
bash start_all_one_node.sh \
  --node-rank 0 \
  --num-nodes 7 \
  --processes-per-node 8 \
  --exp glm51_eval_v9 \
  --model "GLM-5.1" \
  --port 31542 \
  --run-cc-script-path /xxx/run_cc_v9.py \
  --cybergym-data-dir /xxx/cybergym/data \
  --out-root /xxx/cybergym/output \
  --round-i 1
EOF
}

# -------------------------- 解析命名参数 --------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --node-rank)
      node_rank="$2"
      shift 2
      ;;
    --num-nodes)
      num_nodes="$2"
      shift 2
      ;;
    --processes-per-node)
      processes_per_node="$2"
      shift 2
      ;;
    --exp)
      exp="$2"
      shift 2
      ;;
    --model)
      model="$2"
      shift 2
      ;;
    --port)
      port="$2"
      shift 2
      ;;
    --run-cc-script-path)
      run_cc_script_path="$2"
      shift 2
      ;;
    --cybergym-data-dir)
      cybergym_data_dir="$2"
      shift 2
      ;;
    --out-root)
      out_root="$2"
      shift 2
      ;;
    --round-i)
      round_i="$2"
      shift 2
      ;;
    --timeout)
      timeout="$2"
      shift 2
      ;;
    --rerun-task-file)
      rerun_task_file="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# -------------------------- 必填参数校验 --------------------------
required=(node_rank num_nodes processes_per_node exp model port run_cc_script_path cybergym_data_dir out_root round_i)
for var in "${required[@]}"; do
  if [[ -z "${!var}" ]]; then
    echo "ERROR: missing required option --${var//_/-}" >&2
    usage >&2
    exit 2
  fi
done

# 数字校验（round_i改为字符串标识，不再做数字校验）
for v in node_rank num_nodes processes_per_node port; do
  val="${!v}"
  if [[ ! $val =~ ^[0-9]+$ ]]; then
    echo "ERROR: $v must be non‑negative integer, got '$val'" >&2
    exit 2
  fi
done


# round_i 是目录标识，拦截文件系统非法字符
ILLEGAL_CHARS_RE='[/\\:*?"<>|]'
if [[ "${round_i}" =~ $ILLEGAL_CHARS_RE ]]; then
  echo "ERROR: --round-i contains illegal filesystem chars, got '${round_i}'" >&2
  exit 2
fi

# 业务逻辑校验
if (( num_nodes == 0 || processes_per_node == 0 || node_rank >= num_nodes )); then
  echo "ERROR: require num_nodes>0, processes_per_node>0, 0<=node_rank<num_nodes" >&2
  exit 2
fi
if [[ ! $exp =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: --exp may only contain letters,digits,._-" >&2
  exit 2
fi

# run_cc脚本文件存在校验
if [[ ! -f "${run_cc_script_path}" ]]; then
  echo "ERROR: run‑cc‑script‑path not found: ${run_cc_script_path}" >&2
  exit 2
fi

# 数据集目录存在校验
if [[ ! -d "${cybergym_data_dir}" ]]; then
  echo "ERROR: cybergym data directory not found: ${cybergym_data_dir}" >&2
  exit 2
fi

# 输出根目录存在校验
if [[ ! -d "${out_root}" ]]; then
  echo "ERROR: output root directory not found: ${out_root}" >&2
  exit 2
fi

# 如果传了rerun‑task‑file，校验远端文件存在
if [[ -n "${rerun_task_file}" ]]; then
  if [[ ! -f "${rerun_task_file}" ]]; then
    echo "ERROR: rerun‑task‑file not found on remote node: ${rerun_task_file}" >&2
    exit 2
  fi
fi

# 变量别名，兼容后面原有代码
run_id="${exp}"
workers_per_node="${processes_per_node}"
node_count="${num_nodes}"
llm_service_port="${port}"

# ✅核心修复：输入数字round_i，生成ROUND_TAG=round1，导出给下游worker
ROUND_TAG="round${round_i}"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# 日志与PID目录按原始数字轮次隔离
log_dir="$script_dir/logs/$run_id/${ROUND_TAG}/node${node_rank}"
pid_dir="$script_dir/pids/$run_id/${ROUND_TAG}/node${node_rank}"
mkdir -p "$log_dir" "$pid_dir"

# POC 数据库目录：run_id 级别，同实验所有 round 共用
POC_SAVE_DIR="${out_root}/${model}/${run_id}/server_poc"
mkdir -p "${POC_SAVE_DIR}"

total_workers=$((node_count * workers_per_node))

# # -------------------------- 部署拦截API请求的Proxy开始 --------------------------
# PROXY_PORT=${PROXY_PORT:-31545} # 31545 31542
# proxy_log_dir="$log_dir/capture_logs"
# mkdir -p "$proxy_log_dir"

# source /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/.venv/bin/activate
# nohup python /gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/hanxueming/cybergym/anthropic_full_capture_proxy/proxy.py \
#   --listen-host 0.0.0.0 \
#   --listen-port $PROXY_PORT \
#   --upstream-url http://${MASTER_SERVER_IP}:${llm_service_port} \
#   --log-dir $proxy_log_dir \
#   --timeout-seconds 300 >> $proxy_log_dir/proxy_launch.log 2>&1 &
# llm_service_port="${PROXY_PORT}"
# LLM_SERVICE_PORT="${PROXY_PORT}"
# # -------------------------- 部署拦截API请求的Proxy结束 --------------------------

# -------------------------- ✅关键修复块开始 --------------------------
# MASTER_SERVER_IP 由顶层 dis_launch_all.sh 通过 ssh 环境变量注入，本脚本不再读取任何本地文件
if [[ -z "${MASTER_SERVER_IP:-}" ]]; then
    echo "[FATAL] MASTER_SERVER_IP 环境变量为空！顶层调度脚本没有下发该变量" >&2
    exit 1
fi
export MASTER_SERVER_IP

# 本地推理模式：强制组装正确URL，覆盖节点旧脏环境残留；网关模式保留上层传入ANTHROPIC_BASE_URL
if [[ "${USE_DATATANG_API}" == "false" ]]; then
    export ANTHROPIC_BASE_URL="http://${MASTER_SERVER_IP}:${LLM_SERVICE_PORT}/"
fi
# -------------------------- ✅关键修复块结束 --------------------------

echo "run_id=$run_id round_i(tag)=$round_i ROUND_TAG(env)=$ROUND_TAG node=$node_rank/$node_count local_workers=$workers_per_node global_workers=$total_workers"
echo "MODEL=${model} LLM_SERVICE_PORT=${llm_service_port}"
echo "RUN_CC_SCRIPT=${run_cc_script_path}"
echo "TIMEOUT=${timeout}"
echo "CYBERGYM_DATA_DIR=${cybergym_data_dir}"
echo "OUT_ROOT=${out_root}"
echo "POC_SAVE_DIR=${POC_SAVE_DIR}"
if [[ -n "${rerun_task_file}" ]];then
  echo "==== NODE ${node_rank}: RERUN MODE ACTIVATED, remote_task_file=${rerun_task_file} ===="
fi


# ========== 导出环境变量给下游脚本 ==========
export MODEL="${model}"
export LLM_SERVICE_PORT="${llm_service_port}"
export RUN_CC_SCRIPT_PATH="${run_cc_script_path}"
export TIMEOUT="${timeout}"
export RERUN_TASK_FILE="${rerun_task_file:-}"
export CYBERGYM_DATA_DIR="${cybergym_data_dir}"
export OUT_ROOT="${out_root}"
# ✅传给start_one_process.sh必须是 round1 / round2，不是裸数字
export ROUND_I="${ROUND_TAG}"

# Claude‑Code 相关环境变量，从上层ssh继承透传给子进程(binary_server + workers)
export USE_DATATANG_API="${USE_DATATANG_API:-false}"
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"
export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-}"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS:-}"


# 打印当前Claude‑Code运行模式，便于日志排查
if [[ "${USE_DATATANG_API}" == "true" ]]; then
    echo "INFO(node${node_rank}): Claude‑Code external gateway mode, base_url=${ANTHROPIC_BASE_URL}, model=${ANTHROPIC_MODEL}"
else
    echo "INFO(node${node_rank}): Claude‑Code local service mode, base_url=${ANTHROPIC_BASE_URL}, port=${LLM_SERVICE_PORT}"
fi


# 给验证服务专用的环境变量
export POC_SAVE_DIR
export SERVER_PORT=8666
export REPO_DIR="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main"

# 启动评测server
mkdir -p poc_server_logs
nohup "${script_dir}/binary_server.sh" >> "poc_server_logs/${run_id}_round${round_i}_poc_server.log" 2>&1 &

for ((local_rank=0; local_rank < workers_per_node; local_rank++)); do
  global_rank=$((node_rank * workers_per_node + local_rank))
  log_file="$log_dir/worker${local_rank}_shard${global_rank}.log"
  pid_file="$pid_dir/worker${local_rank}.pid"

  if [[ -f $pid_file ]]; then
    old_pid=$(<"$pid_file")
    if [[ $old_pid =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
      echo "ERROR: worker $local_rank is already running with pid=$old_pid ($pid_file)" >&2
      exit 1
    fi
  fi

  nohup bash "$script_dir/start_one_process.sh" \
    "$global_rank" "$total_workers" "$run_id" "$node_rank" "$local_rank" \
    >"$log_file" 2>&1 &
  pid=$!
  echo "$pid" >"$pid_file"
  echo "started local_rank=$local_rank global_shard=$global_rank/$total_workers pid=$pid log=$log_file"
done