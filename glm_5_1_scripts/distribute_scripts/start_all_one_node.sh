#!/usr/bin/env bash
set -euo pipefail

# -------------------------- 鍒濆�嬪寲鍙橀噺榛樿�ゅ€� --------------------------
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

鍗曡妭鐐瑰惎鍔–yberGym楠岃瘉鏈嶅姟 + 涓€缁剋orker杩涚▼

Options:
    --node-rank INT              褰撳墠鑺傜偣rank(浠�0寮€濮�) (蹇呭～)
    --num-nodes INT              闆嗙兢鎬昏妭鐐规暟 (蹇呭～)
    --processes-per-node INT     褰撳墠鑺傜偣骞跺彂worker鏁伴噺 (蹇呭～)
    --exp TEXT                   瀹為獙run_id (蹇呭～)
    --model TEXT                 妯″瀷鍚嶇О (蹇呭～)
    --port INT                   LLM鏈嶅姟绔�鍙� (蹇呭～)
    --run-cc-script-path FILE    run_cc.py瀹屾暣璺�寰� (蹇呭～)
    --cybergym-data-dir DIR      Cybergym璇勬祴鏁版嵁闆嗘牴鐩�褰� (蹇呭～)
    --out-root DIR               璇勬祴缁撴灉杈撳嚭鏍圭洰褰� (蹇呭～)
    --round-i TEXT               閲嶈窇杞�娆℃爣璇嗭紝鏀�鎸� 1 / 1.1 / 1-1 (蹇呭～)              閲嶈窇杞�娆℃暟瀛楃紪鍙凤紝渚嬪�� 1 (蹇呭～)
    --rerun-task-file FILE       杩滅��閲嶈窇浠诲姟鏂囦欢锛屽彲閫�
    -h,--help                    甯�鍔�

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

# -------------------------- 瑙ｆ瀽鍛藉悕鍙傛暟 --------------------------
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

# -------------------------- 蹇呭～鍙傛暟鏍￠獙 --------------------------
required=(node_rank num_nodes processes_per_node exp model port run_cc_script_path cybergym_data_dir out_root round_i)
for var in "${required[@]}"; do
  if [[ -z "${!var}" ]]; then
    echo "ERROR: missing required option --${var//_/-}" >&2
    usage >&2
    exit 2
  fi
done

# 鏁板瓧鏍￠獙锛坮ound_i鏀逛负瀛楃�︿覆鏍囪瘑锛屼笉鍐嶅仛鏁板瓧鏍￠獙锛�
for v in node_rank num_nodes processes_per_node port; do
  val="${!v}"
  if [[ ! $val =~ ^[0-9]+$ ]]; then
    echo "ERROR: $v must be non鈥憂egative integer, got '$val'" >&2
    exit 2
  fi
done


# round_i 鏄�鐩�褰曟爣璇嗭紝鎷︽埅鏂囦欢绯荤粺闈炴硶瀛楃��
ILLEGAL_CHARS_RE='[/\\:*?"<>|]'
if [[ "${round_i}" =~ $ILLEGAL_CHARS_RE ]]; then
  echo "ERROR: --round-i contains illegal filesystem chars, got '${round_i}'" >&2
  exit 2
fi

# 涓氬姟閫昏緫鏍￠獙
if (( num_nodes == 0 || processes_per_node == 0 || node_rank >= num_nodes )); then
  echo "ERROR: require num_nodes>0, processes_per_node>0, 0<=node_rank<num_nodes" >&2
  exit 2
fi
if [[ ! $exp =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: --exp may only contain letters,digits,._-" >&2
  exit 2
fi

# run_cc鑴氭湰鏂囦欢瀛樺湪鏍￠獙
if [[ ! -f "${run_cc_script_path}" ]]; then
  echo "ERROR: run鈥慶c鈥憇cript鈥憄ath not found: ${run_cc_script_path}" >&2
  exit 2
fi

# 鏁版嵁闆嗙洰褰曞瓨鍦ㄦ牎楠�
if [[ ! -d "${cybergym_data_dir}" ]]; then
  echo "ERROR: cybergym data directory not found: ${cybergym_data_dir}" >&2
  exit 2
fi

# 杈撳嚭鏍圭洰褰曞瓨鍦ㄦ牎楠�
if [[ ! -d "${out_root}" ]]; then
  mkdir -p "${out_root}" || {
    echo "ERROR: cannot create output root directory: ${out_root}" >&2
    exit 2
  }
fi

# 濡傛灉浼犱簡rerun鈥憈ask鈥慺ile锛屾牎楠岃繙绔�鏂囦欢瀛樺湪
if [[ -n "${rerun_task_file}" ]]; then
  if [[ ! -f "${rerun_task_file}" ]]; then
    echo "ERROR: rerun鈥憈ask鈥慺ile not found on remote node: ${rerun_task_file}" >&2
    exit 2
  fi
fi

# 鍙橀噺鍒�鍚嶏紝鍏煎�瑰悗闈㈠師鏈変唬鐮�
run_id="${exp}"
workers_per_node="${processes_per_node}"
node_count="${num_nodes}"
llm_service_port="${port}"

# 鉁呮牳蹇冧慨澶嶏細杈撳叆鏁板瓧round_i锛岀敓鎴怰OUND_TAG=round1锛屽�煎嚭缁欎笅娓竪orker
ROUND_TAG="round${round_i}"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# 鏃ュ織涓嶱ID鐩�褰曟寜鍘熷�嬫暟瀛楄疆娆￠殧绂�
log_dir="$script_dir/logs/$run_id/${ROUND_TAG}/node${node_rank}"
pid_dir="$script_dir/pids/$run_id/${ROUND_TAG}/node${node_rank}"
mkdir -p "$log_dir" "$pid_dir"

# POC 鏁版嵁搴撶洰褰曪細run_id 绾у埆锛屽悓瀹為獙鎵€鏈� round 鍏辩敤
POC_SAVE_DIR="${out_root}/${model}/${run_id}/server_poc"
mkdir -p "${POC_SAVE_DIR}"

total_workers=$((node_count * workers_per_node))
capture_proxy_pid=""
declare -a worker_pids=()

# # -------------------------- 閮ㄧ讲鎷︽埅API璇锋眰鐨凱roxy寮€濮� --------------------------
# PROXY_PORT=${PROXY_PORT:-31545} # 31545 31542
# proxy_log_dir="$log_dir/capture_logs"
# mkdir -p "$proxy_log_dir"

# source /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/.venv/bin/activate
# nohup python "${CYBERGYM_REPO_ROOT}/capture_proxy/proxy.py" \
#   --listen-host 0.0.0.0 \
#   --listen-port $PROXY_PORT \
#   --upstream-url http://${MASTER_SERVER_IP}:${llm_service_port} \
#   --log-dir $proxy_log_dir \
#   --timeout-seconds 300 >> $proxy_log_dir/proxy_launch.log 2>&1 &
# llm_service_port="${PROXY_PORT}"
# LLM_SERVICE_PORT="${PROXY_PORT}"
# # -------------------------- 閮ㄧ讲鎷︽埅API璇锋眰鐨凱roxy缁撴潫 --------------------------

# -------------------------- 鉁呭叧閿�淇�澶嶅潡寮€濮� --------------------------
# MASTER_SERVER_IP 鐢遍《灞� dis_launch_all.sh 閫氳繃 ssh 鐜�澧冨彉閲忔敞鍏ワ紝鏈�鑴氭湰涓嶅啀璇诲彇浠讳綍鏈�鍦版枃浠�
if [[ -z "${MASTER_SERVER_IP:-}" ]]; then
    echo "[FATAL] MASTER_SERVER_IP 鐜�澧冨彉閲忎负绌猴紒椤跺眰璋冨害鑴氭湰娌℃湁涓嬪彂璇ュ彉閲�" >&2
    exit 1
fi
export MASTER_SERVER_IP
export SERVER_HOST="${SERVER_HOST:-${MASTER_SERVER_IP}}"
script_repo_root=$(cd -- "${script_dir}/../.." && pwd)
export CYBERGYM_REPO_ROOT="${CYBERGYM_REPO_ROOT:-${script_repo_root}}"
export CYBERGYM_SOURCE_DIR="${CYBERGYM_SOURCE_DIR:-${REPO_DIR:-}}"
export CYBERGYM_PYTHON="${CYBERGYM_PYTHON:-}"
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-}"

if [[ -n "${CAPTURE_PROXY_UPSTREAM_URL:-}" && ! "${CAPTURE_PROXY_UPSTREAM_URL}" =~ ^https?://([A-Za-z0-9._-]+|[0-9A-Fa-f:]+)(:[0-9]{1,5})?/?$ ]]; then
    echo "ERROR invalid CAPTURE_PROXY_UPSTREAM_URL: ${CAPTURE_PROXY_UPSTREAM_URL}" >&2
    exit 1
fi

# 鏈�鍦版帹鐞嗘ā寮忥細寮哄埗缁勮�呮�ｇ‘URL锛岃�嗙洊鑺傜偣鏃ц剰鐜�澧冩畫鐣欙紱缃戝叧妯″紡淇濈暀涓婂眰浼犲叆ANTHROPIC_BASE_URL
if [[ "${HARNESS_TYPE:-claude}" == "claude" && "${USE_DATATANG_API}" == "false" ]]; then
    export ANTHROPIC_BASE_URL="http://${MASTER_SERVER_IP}:${LLM_SERVICE_PORT}/"
fi
# -------------------------- 鉁呭叧閿�淇�澶嶅潡缁撴潫 --------------------------

if [[ "${CAPTURE_PROXY_ENABLED:-false}" == "true" ]]; then
  CAPTURE_PROXY_SCRIPT="${CAPTURE_PROXY_SCRIPT:-${CYBERGYM_REPO_ROOT}/capture_proxy/proxy.py}"
  CAPTURE_PROXY_PORT="${CAPTURE_PROXY_PORT:-31545}"
  # Always isolate captures by run/round/node. A stale CAPTURE_LOG_DIR from a
  # previous shell session would otherwise make new task results point at old
  # captures and can mix unrelated requests into one experiment.
  CAPTURE_LOG_DIR="${log_dir}/capture_logs"
  CAPTURE_PROXY_VENV="${CAPTURE_PROXY_VENV:-}"
  CAPTURE_PROXY_PYTHON="${CAPTURE_PROXY_PYTHON:-${CYBERGYM_PYTHON:-}}"
  proxy_runtime_root="${CYBERGYM_SOURCE_DIR:-${REPO_DIR:-}}"
  if [[ -z "${CAPTURE_PROXY_VENV}" && -n "${proxy_runtime_root}" && -f "${proxy_runtime_root}/.venv/bin/activate" ]]; then
    CAPTURE_PROXY_VENV="${proxy_runtime_root}/.venv"
  fi
  if [[ -z "${CAPTURE_PROXY_PYTHON}" && -n "${CAPTURE_PROXY_VENV}" ]]; then
    CAPTURE_PROXY_PYTHON="${CAPTURE_PROXY_VENV}/bin/python"
  fi
  if [[ -z "${CAPTURE_PROXY_PYTHON}" && -n "${proxy_runtime_root}" && -x "${proxy_runtime_root}/.venv/bin/python" ]]; then
    CAPTURE_PROXY_PYTHON="${proxy_runtime_root}/.venv/bin/python"
  fi
  if [[ -z "${CAPTURE_PROXY_PYTHON}" && -x "${CYBERGYM_REPO_ROOT}/.venv/bin/python" ]]; then
    CAPTURE_PROXY_PYTHON="${CYBERGYM_REPO_ROOT}/.venv/bin/python"
  fi
  if [[ -z "${CAPTURE_PROXY_PYTHON}" ]]; then
    CAPTURE_PROXY_PYTHON="$(command -v python3 || command -v python || true)"
  fi
  CAPTURE_PROXY_UPSTREAM_URL="${CAPTURE_PROXY_UPSTREAM_URL:-http://${MASTER_SERVER_IP}:${llm_service_port}}"
  mkdir -p "${CAPTURE_LOG_DIR}"
  if [[ ! -f "${CAPTURE_PROXY_SCRIPT}" ]]; then
    echo "ERROR capture proxy script not found: ${CAPTURE_PROXY_SCRIPT}" >&2
    exit 1
  fi
  if [[ ! -x "${CAPTURE_PROXY_PYTHON}" ]]; then
    echo "ERROR capture proxy Python not executable: ${CAPTURE_PROXY_PYTHON}" >&2
    exit 1
  fi
  if [[ -n "${CAPTURE_PROXY_VENV}" && -f "${CAPTURE_PROXY_VENV}/bin/activate" ]]; then
    source "${CAPTURE_PROXY_VENV}/bin/activate"
  fi
  echo "CAPTURE_PROXY_VENV=${VIRTUAL_ENV:-}"
  echo "CAPTURE_PROXY_PYTHON=${CAPTURE_PROXY_PYTHON}"
  "${CAPTURE_PROXY_PYTHON}" --version
  nohup "${CAPTURE_PROXY_PYTHON}" "${CAPTURE_PROXY_SCRIPT}" \
    --listen-host 0.0.0.0 \
    --listen-port "${CAPTURE_PROXY_PORT}" \
    --upstream-url "${CAPTURE_PROXY_UPSTREAM_URL}" \
    --log-dir "${CAPTURE_LOG_DIR}" \
    --timeout-seconds "${CAPTURE_PROXY_TIMEOUT:-300}" \
    > "${CAPTURE_LOG_DIR}/proxy_launch.log" 2>&1 &
  capture_proxy_pid=$!
  echo "${capture_proxy_pid}" > "${CAPTURE_LOG_DIR}/proxy.pid"
  echo "CAPTURE_PROXY_PID=${capture_proxy_pid}"
  echo "CAPTURE_PROXY_UPSTREAM_URL=${CAPTURE_PROXY_UPSTREAM_URL}"
  proxy_ready=false
  for _ in $(seq 1 "${CAPTURE_PROXY_STARTUP_TIMEOUT:-30}"); do
    if ! kill -0 "${capture_proxy_pid}" 2>/dev/null; then
      echo "ERROR capture proxy exited during startup; log=${CAPTURE_LOG_DIR}/proxy_launch.log" >&2
      tail -50 "${CAPTURE_LOG_DIR}/proxy_launch.log" >&2 || true
      exit 1
    fi
    if curl -fsS --max-time 2 "http://127.0.0.1:${CAPTURE_PROXY_PORT}/healthz" \
      > "${CAPTURE_LOG_DIR}/healthz.json" 2>/dev/null; then
      proxy_ready=true
      break
    fi
    sleep 1
  done
  if [[ "${proxy_ready}" != true ]]; then
    echo "ERROR capture proxy did not become ready on port ${CAPTURE_PROXY_PORT}; log=${CAPTURE_LOG_DIR}/proxy_launch.log" >&2
    tail -50 "${CAPTURE_LOG_DIR}/proxy_launch.log" >&2 || true
    kill "${capture_proxy_pid}" 2>/dev/null || true
    exit 1
  fi
  echo "CAPTURE_PROXY_READY=true"
  export CAPTURE_LOG_DIR
  CAPTURE_BASE_URL="http://${MASTER_SERVER_IP}:${CAPTURE_PROXY_PORT}"
  if [[ "${HARNESS_TYPE:-claude}" == "claude" ]]; then
    export ANTHROPIC_BASE_URL="${CAPTURE_BASE_URL}"
  else
    export LLM_BASE_URL="${CAPTURE_BASE_URL}/v1"
    export GLM_BASE_URL="${CAPTURE_BASE_URL}/v1"
    export OPENAI_BASE_URL="${CAPTURE_BASE_URL}/v1"
    export OPENCODE_BASE_URL="${CAPTURE_BASE_URL}/v1"
  fi
fi

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


# ========== 瀵煎嚭鐜�澧冨彉閲忕粰涓嬫父鑴氭湰 ==========
export MODEL="${model}"
export LLM_SERVICE_PORT="${llm_service_port}"
export RUN_CC_SCRIPT_PATH="${run_cc_script_path}"
export TIMEOUT="${timeout}"
export RERUN_TASK_FILE="${rerun_task_file:-}"
export CYBERGYM_DATA_DIR="${cybergym_data_dir}"
export OUT_ROOT="${out_root}"
export HARNESS_TYPE="${HARNESS_TYPE:-claude}"
export HARNESS_IMAGE="${HARNESS_IMAGE:-}"
export DEEPSEEK_IMAGE="${DEEPSEEK_IMAGE:-cybergym-deepseek:claude-v1}"
export OPENCODE_IMAGE="${OPENCODE_IMAGE:-cybergym-opencode:claude-v1}"
export DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"
export OPENCODE_MODEL="${OPENCODE_MODEL:-}"
export LLM_PROVIDER="${LLM_PROVIDER:-deepseek}"
export LLM_API_KEY_ENV="${LLM_API_KEY_ENV:-}"
if [[ -z "${LLM_API_KEY_ENV}" ]]; then
  case "${LLM_PROVIDER}" in
    deepseek) LLM_API_KEY_ENV="DEEPSEEK_API_KEY" ;;
    glm) LLM_API_KEY_ENV="GLM_API_KEY" ;;
    gpt|openai|openai-compatible) LLM_API_KEY_ENV="OPENAI_API_KEY" ;;
    anthropic|claude) LLM_API_KEY_ENV="ANTHROPIC_API_KEY" ;;
  esac
fi
if [[ ! "${LLM_API_KEY_ENV}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "[ERROR] invalid LLM_API_KEY_ENV=${LLM_API_KEY_ENV}" >&2
  exit 1
fi
export LLM_API_KEY_ENV
export LLM_BASE_URL="${LLM_BASE_URL:-}"
export GLM_BASE_URL="${GLM_BASE_URL:-}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-}"
export OPENCODE_BASE_URL="${OPENCODE_BASE_URL:-}"
export CAPTURE_PROXY_ENABLED="${CAPTURE_PROXY_ENABLED:-false}"
export CAPTURE_PROXY_SCRIPT="${CAPTURE_PROXY_SCRIPT:-}"
export CAPTURE_PROXY_PORT="${CAPTURE_PROXY_PORT:-31545}"
export CAPTURE_PROXY_VENV="${CAPTURE_PROXY_VENV:-}"
export CAPTURE_PROXY_PYTHON="${CAPTURE_PROXY_PYTHON:-${CYBERGYM_PYTHON:-}}"
export CAPTURE_PROXY_UPSTREAM_URL="${CAPTURE_PROXY_UPSTREAM_URL:-}"
export CAPTURE_LOG_DIR="${CAPTURE_LOG_DIR:-}"
export LLM_API_FORMAT="${LLM_API_FORMAT:-}"
export LLM_MODEL="${LLM_MODEL:-}"
export HARNESS_MODEL="${HARNESS_MODEL:-}"
if [[ "${HARNESS_TYPE}" == "deepseek" ]]; then export HARNESS_IMAGE="${DEEPSEEK_IMAGE}"; fi
if [[ "${HARNESS_TYPE}" == "opencode" ]]; then export HARNESS_IMAGE="${OPENCODE_IMAGE}"; fi
# 鉁呬紶缁檚tart_one_process.sh蹇呴』鏄� round1 / round2锛屼笉鏄�瑁告暟瀛�
export ROUND_I="${ROUND_TAG}"

# Claude鈥慍ode 鐩稿叧鐜�澧冨彉閲忥紝浠庝笂灞俿sh缁ф壙閫忎紶缁欏瓙杩涚▼(binary_server + workers)
export USE_DATATANG_API="${USE_DATATANG_API:-false}"
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"
export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-}"
export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS:-}"


# 鎵撳嵃褰撳墠Claude鈥慍ode杩愯�屾ā寮忥紝渚夸簬鏃ュ織鎺掓煡
if [[ "${USE_DATATANG_API}" == "true" ]]; then
    echo "INFO(node${node_rank}): Claude鈥慍ode external gateway mode, base_url=${ANTHROPIC_BASE_URL}, model=${ANTHROPIC_MODEL}"
else
    echo "INFO(node${node_rank}): Claude鈥慍ode local service mode, base_url=${ANTHROPIC_BASE_URL}, port=${LLM_SERVICE_PORT}"
fi


# 缁欓獙璇佹湇鍔′笓鐢ㄧ殑鐜�澧冨彉閲�
export POC_SAVE_DIR
export SERVER_PORT="${SERVER_PORT:-8666}"
export REPO_DIR="${CYBERGYM_SOURCE_DIR:-${REPO_DIR:-/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main}}"

# 鍚�鍔ㄨ瘎娴媠erver
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
  worker_pids+=("${pid}")
  echo "$pid" >"$pid_file"
  echo "started local_rank=$local_rank global_shard=$global_rank/$total_workers pid=$pid log=$log_file"
done

# Keep the optional capture proxy alive for this round, then clean it up so a
# later round can reuse the same port. The proxy is deliberately independent
# from the legacy Claude path and is only watched when capture is enabled.
if [[ -n "${capture_proxy_pid}" ]]; then
  (
    while :; do
      workers_alive=false
      for worker_pid in "${worker_pids[@]}"; do
        if kill -0 "${worker_pid}" 2>/dev/null; then
          workers_alive=true
          break
        fi
      done
      if [[ "${workers_alive}" != true ]]; then
        kill "${capture_proxy_pid}" 2>/dev/null || true
        rm -f "${CAPTURE_LOG_DIR}/proxy.pid"
        exit 0
      fi
      sleep 5
    done
  ) >> "${CAPTURE_LOG_DIR}/proxy_watchdog.log" 2>&1 &
  echo "$!" > "${CAPTURE_LOG_DIR}/proxy_watchdog.pid"
fi
