#!/bin/bash
set -euo pipefail

# ==============================================================================
# 评测与集群配置【全部在此修改】
# ==============================================================================

############################################################
#  ⚠️ 修改为自己目录地址
############################################################
# 所有脚本、输出文件都放在这个根目录下
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR="${ROOT_DIR:-$(cd -- "${SCRIPT_DIR}/../.." && pwd)}"

############################################################
#  ⚠️ 常用修改项 1 / 5
############################################################
# 被测模型名称，用于目录命名
MODEL="${MODEL:-jt35}"
# MODEL="glm-5.3-flash"
# USE_DATATANG_API【数据堂接口形式待开发未实验不可用，目前只支持本地服务调用形式】
#   false：原始模式，调用本机端口推理服务
#   true：Claude‑Code调用外部Anthropic网关，自动开启socks5h://10.17.9.218:1080

USE_DATATANG_API="false"
ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-${MODEL}}"
ANTHROPIC_BASE_URL="https://llmapi.datatang.com/v1/"
CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="1"
HARNESS_TYPE="${HARNESS_TYPE:-claude}"
DEEPSEEK_IMAGE="${DEEPSEEK_IMAGE:-cybergym-deepseek:claude-v1}"
OPENCODE_IMAGE="${OPENCODE_IMAGE:-cybergym-opencode:claude-v1}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-flash}"
OPENCODE_MODEL="${OPENCODE_MODEL:-}"
LLM_PROVIDER="${LLM_PROVIDER:-deepseek}"
LLM_API_KEY_ENV="${LLM_API_KEY_ENV:-}"
if [[ -z "${LLM_API_KEY_ENV}" ]]; then
    case "${LLM_PROVIDER}" in
        deepseek) LLM_API_KEY_ENV="DEEPSEEK_API_KEY" ;;
        glm) LLM_API_KEY_ENV="GLM_API_KEY" ;;
        gpt|openai|openai-compatible) LLM_API_KEY_ENV="OPENAI_API_KEY" ;;
        anthropic|claude) LLM_API_KEY_ENV="ANTHROPIC_API_KEY" ;;
        *) echo "[ERROR] unsupported LLM_PROVIDER=${LLM_PROVIDER}" >&2; exit 1 ;;
    esac
fi
if [[ ! "${LLM_API_KEY_ENV}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "[ERROR] invalid LLM_API_KEY_ENV=${LLM_API_KEY_ENV}" >&2
    exit 1
fi
LLM_BASE_URL="${LLM_BASE_URL:-}"
GLM_BASE_URL="${GLM_BASE_URL:-}"
OPENAI_BASE_URL="${OPENAI_BASE_URL:-}"
OPENCODE_BASE_URL="${OPENCODE_BASE_URL:-}"
CAPTURE_PROXY_ENABLED="${CAPTURE_PROXY_ENABLED:-false}"
CAPTURE_PROXY_SCRIPT="${CAPTURE_PROXY_SCRIPT:-}"
CAPTURE_PROXY_PORT="${CAPTURE_PROXY_PORT:-31545}"
CAPTURE_PROXY_VENV="${CAPTURE_PROXY_VENV:-}"
CAPTURE_PROXY_PYTHON="${CAPTURE_PROXY_PYTHON:-}"
CAPTURE_PROXY_UPSTREAM_URL="${CAPTURE_PROXY_UPSTREAM_URL:-}"
CYBERGYM_PYTHON="${CYBERGYM_PYTHON:-}"
CYBERGYM_SOURCE_DIR="${CYBERGYM_SOURCE_DIR:-}"
LLM_API_FORMAT="${LLM_API_FORMAT:-}"
LLM_MODEL="${LLM_MODEL:-}"
HARNESS_MODEL="${HARNESS_MODEL:-}"
SERVER_PORT="${SERVER_PORT:-8666}"

############################################################
#  ⚠️ 常用修改项 2 / 5
############################################################
# 本地推理模式 USE_DATATANG_API=false 生效
LLM_SERVICE_PORT="${LLM_SERVICE_PORT:-31542}" # 推理API所使用的端口号
HOST_FILE="${HOST_FILE:-jt35_ip.txt}" # 用于起评测服务的IP HOST文件，一般也是推理实例的Master IP，一行一个IP
# HOST_FILE="glm53flash_ip.txt"
# EXP="glm-5.3-flash-eval-20260904-v9" # 实验ID，同一次评测所有节点必须一致 可以参考通过Model+Agent+Date的方式命名
# EXP="jt236b-eval-cyber-v0.0.7-step940-preserve-20260903-v9"
# EXP="jt236b-eval-cyber-v0.0.7-iter_0002350-preserve-20260904-v9"
EXP="jt35b-eval-cyber-v0.0.8-test"
# TIMEOUT=7200
TIMEOUT=15000
PER_NODE_PROCESS=8    # 每个评测节点IP同时解决多少道题目，也是该node下worker文件夹数量

############################################################
#  ⚠️ 常用修改项 3 / 5
############################################################
# 重测轮数 以及输出的存储路径命名，每次测试都需要修改，只需要改数字ROUND_NUM。Round2=rerun Round3=rerun2
ROUND_NUM=1 # TODO: 判断ROUND_TAG如果已存在，应该报错结束，以免出现忘记修改的情况
ROUND_TAG="round${ROUND_NUM}"

# 数据集路径（数据集独立，不归属ROOT_DIR，保持不变）
# 全量1507道题目路径
# CYBERGYM_DATA_DIR="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/cybergym_data/data-heyu/cybergym/data"
# 用于拉通测试的少量题目路径-2道题
CYBERGYM_DATA_DIR="${CYBERGYM_DATA_DIR:-}"

# ========== 全部基于ROOT_DIR拼接 ==========
# 远端脚本工作目录
REMOTE_WORK_DIR="${ROOT_DIR}/glm_5_1_scripts/distribute_scripts"
############################################################
#  ⚠️ 常用修改项 4 / 5
############################################################
# run_cc脚本路径
RUN_CC_SCRIPT_PATH="${ROOT_DIR}/harness_selector.py"

# 评测结果输出根目录
OUT_ROOT="${ROOT_DIR}/output"

############################################################
#  ⚠️ 常用修改项 5 / 5
############################################################
# 重跑任务列表
RERUN_TASK_LIST="" # 为空时，默认为全量1507道题，从CYBERGYM_DATA_DIR路径取。不为空时，相当于之前的rerun_list，代表此次需要评测的题目列表


# ==============================================================================
# 以下为起服务脚本，不改可不看
# ==============================================================================


usage() {
cat <<EOF
Usage: $0 [OPTIONS]

多节点CyberGym分布式调度脚本

Options:
    --capture-proxy-upstream-url URL  API capture proxy upstream LLM URL
    --exp TEXT              实验run_id
    --rerun-task-list FILE  共享存储上的重跑task列表文件
    --round-i TEXT          重跑轮次，如：1 / 2 / 3
    --host-file FILE        节点ip列表txt文件
    --root-dir DIR          顶层统一根目录
    --out-root DIR          评测结果输出根目录
    --cybergym-data-dir DIR 评测数据集根目录
    -h,--help               打印帮助
EOF
}

# ==============================================================================
# 参数解析
# ==============================================================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        --exp)
            EXP="$2"
            shift 2
            ;;
        --rerun-task-list)
            RERUN_TASK_LIST="$2"
            shift 2
            ;;
        --cybergym-data-dir)
            CYBERGYM_DATA_DIR="$2"
            shift 2
            ;;
        --out-root)
            OUT_ROOT="$2"
            shift 2
            ;;
        --round-i)
            RAW_ROUND="$2"
            shift 2
            ;;
        --host-file)
            HOST_FILE="$2"
            shift 2
            ;;
        --root-dir)
            ROOT_DIR="$2"
            REMOTE_WORK_DIR="${ROOT_DIR}/glm_5_1_scripts/distribute_scripts"
            RUN_CC_SCRIPT_PATH="${ROOT_DIR}/harness_selector.py"
            OUT_ROOT="${ROOT_DIR}/output"
            shift 2
            ;;
        --capture-proxy-upstream-url)
            CAPTURE_PROXY_UPSTREAM_URL="$2"
            shift 2
            ;;
        --harness)
            HARNESS_TYPE="$2"
            shift 2
            ;;
        --server-port)
            SERVER_PORT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[ERROR] Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "${CYBERGYM_DATA_DIR}" ]]; then
    CYBERGYM_DATA_DIR="${CYBERGYM_SOURCE_DIR:-${ROOT_DIR}}/cybergym_data/data"
fi

if [[ -z "${CAPTURE_PROXY_SCRIPT}" ]]; then
    CAPTURE_PROXY_SCRIPT="${ROOT_DIR}/capture_proxy/proxy.py"
fi
if [[ -z "${CAPTURE_PROXY_VENV}" && -f "${ROOT_DIR}/.venv/bin/activate" ]]; then
    CAPTURE_PROXY_VENV="${ROOT_DIR}/.venv"
fi
if [[ -z "${CAPTURE_PROXY_PYTHON}" && -n "${CAPTURE_PROXY_VENV}" ]]; then
    CAPTURE_PROXY_PYTHON="${CAPTURE_PROXY_VENV}/bin/python"
fi

if [[ "${HOST_FILE}" != /* && ! -f "${HOST_FILE}" && -f "${SCRIPT_DIR}/${HOST_FILE}" ]]; then
    HOST_FILE="${SCRIPT_DIR}/${HOST_FILE}"
fi

if [[ -n "${CAPTURE_PROXY_UPSTREAM_URL}" && ! "${CAPTURE_PROXY_UPSTREAM_URL}" =~ ^https?://([A-Za-z0-9._-]+|[0-9A-Fa-f:]+)(:[0-9]{1,5})?/?$ ]]; then
    echo "[ERROR] invalid --capture-proxy-upstream-url: ${CAPTURE_PROXY_UPSTREAM_URL}" >&2
    exit 1
fi

bash "${ROOT_DIR}/glm_5_1_scripts/distribute_scripts/dis_stop_all.sh" --hostfile "${HOST_FILE}"

if [[ "${HARNESS_TYPE}" != "claude" ]]; then
    if [[ -z "${!LLM_API_KEY_ENV:-}" ]]; then
        echo "[ERROR] ${LLM_API_KEY_ENV} must be exported for ${HARNESS_TYPE}" >&2
        exit 1
    fi
    export "${LLM_API_KEY_ENV}"
fi



# ---解析round参数：支持自定义标识字符串，支持 1 / 1.1 / 1-1 / round1 / round1.1 / round1-1，原样透传给远端start_all_one_node.sh---
if [[ -v RAW_ROUND && -n "${RAW_ROUND}" ]]; then
    if [[ "${RAW_ROUND}" =~ ^round(.*)$ ]]; then
        # 剥除round前缀，后面全部作为标识
        ROUND_NUM="${BASH_REMATCH[1]}"
    else
        ROUND_NUM="${RAW_ROUND}"
    fi

    # 拦截文件名非法字符，防止目录创建失败
    ILLEGAL_CHARS_RE='[/\\:*?"<>|]'
    if [[ "${ROUND_NUM}" =~ $ILLEGAL_CHARS_RE ]]; then
        echo "[ERROR] --round-i 包含非法字符( / \\ : * ? \" < > | )，不可用作目录标识，输入: ${RAW_ROUND}" >&2
        exit 1
    fi

    ROUND_TAG="round${ROUND_NUM}"
fi

# ==============================================================================
# 前置校验
# ==============================================================================
if [[ ! -d "${ROOT_DIR}" ]]; then
    echo "[ERROR] ROOT_DIR 根目录不存在：${ROOT_DIR}" >&2
    exit 1
fi

if [[ ! -f "${HOST_FILE}" ]]; then
    echo "[ERROR] host file not found: ${HOST_FILE}" >&2
    exit 1
fi
mapfile -t HOSTS < <(sed 's/#.*//' "${HOST_FILE}" | sed '/^\s*$/d')
NUM_NODES=${#HOSTS[@]}
if [[ "${NUM_NODES}" -eq 0 ]]; then
    echo "[ERROR] HOSTS节点列表为空，请检查host文件：${HOST_FILE}" >&2
    exit 1
fi
echo "Loaded ${NUM_NODES} hosts from ${HOST_FILE}: ${HOSTS[*]}"



if [[ "${HARNESS_TYPE}" == "claude" && "${USE_DATATANG_API}" == "true" ]]; then
    if [[ -z "${ANTHROPIC_BASE_URL}" || -z "${ANTHROPIC_AUTH_TOKEN}" ]]; then
        echo "[ERROR] USE_DATATANG_API=true 必须配置 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN" >&2
        exit 1
    fi
fi

# if [[ ! "${ROUND_NUM}" =~ ^[0-9]+$ ]]; then
#     echo "[ERROR] ROUND_NUM 必须为数字，got: ${ROUND_NUM}" >&2
#     exit 1
# fi

if [[ ! -d "${CYBERGYM_DATA_DIR}" ]]; then
    echo "[ERROR] cybergym data dir not found: ${CYBERGYM_DATA_DIR}" >&2
    exit 1
fi

mkdir -p "${OUT_ROOT}"

if [[ -n "${RERUN_TASK_LIST}" ]]; then
    if [[ ! -f "${RERUN_TASK_LIST}" ]]; then
        echo "[ERROR] rerun‑task‑list file not found on shared storage: ${RERUN_TASK_LIST}" >&2
        exit 1
    fi
    echo "========================================"
    echo "RERUN MODE ON"
    echo "EXP (run_id):    ${EXP}"
    echo "ROUND_TAG:       ${ROUND_TAG}"
    echo "ROUND_NUM:       ${ROUND_NUM}"
    echo "Task File:       ${RERUN_TASK_LIST}"
    echo "Data Dir:        ${CYBERGYM_DATA_DIR}"
    echo "Output Root:     ${OUT_ROOT}"
    echo "========================================"
fi

echo "ROOT_DIR=${ROOT_DIR}"
echo "REMOTE_WORK_DIR=${REMOTE_WORK_DIR}"
echo "RUN_CC_SCRIPT_PATH=${RUN_CC_SCRIPT_PATH}"
echo "DIR_MODEL_NAME=${MODEL}"
echo "API_MODEL_NAME=${ANTHROPIC_MODEL}"
if [[ "${USE_DATATANG_API}" == "true" ]]; then
    echo "MODE: USE_DATATANG_API=true (Claude‑Code外部网关) ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL}"
else
    echo "MODE: USE_DATATANG_API=false (原始本地端口模式) LLM_SERVICE_PORT=${LLM_SERVICE_PORT}"
fi
echo "Launching distributed evaluation across ${NUM_NODES} nodes, round=${ROUND_TAG} (num=${ROUND_NUM})..."
declare -a PIDS=()

# ==============================================================================
# 并发拉起各个节点
# 关键修复：传给 start_all_one_node.sh --round-i **纯数字 ROUND_NUM**，不要传 ROUND_TAG(round1)
# ==============================================================================
for node_rank in "${!HOSTS[@]}"; do
    host="${HOSTS[${node_rank}]}"
    echo ">> Submit node ${host} node_rank=${node_rank}"

    ssh -n -o BatchMode=yes "${host}" "mkdir -p '${REMOTE_WORK_DIR}'"

    # Pipe the API key through SSH stdin instead of embedding it in the remote
    # command or relying on the server's AcceptEnv configuration.
    printf '%s\n' "${!LLM_API_KEY_ENV:-}" | ssh -o BatchMode=yes "${host}" "
        IFS= read -r __CYBERGYM_LLM_KEY || true;
        if [[ '${HARNESS_TYPE}' != 'claude' ]]; then
            export ${LLM_API_KEY_ENV}=\"\${__CYBERGYM_LLM_KEY}\";
        fi;
        unset __CYBERGYM_LLM_KEY;
        export USE_DATATANG_API='${USE_DATATANG_API}';
        export ANTHROPIC_AUTH_TOKEN='${ANTHROPIC_AUTH_TOKEN}';
        export ANTHROPIC_MODEL='${ANTHROPIC_MODEL}';
        export ANTHROPIC_BASE_URL='${ANTHROPIC_BASE_URL}';
        export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS='${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS}';
        export ROOT_DIR='${ROOT_DIR}';
        export CYBERGYM_REPO_ROOT='${ROOT_DIR}';
        export CYBERGYM_PYTHON='${CYBERGYM_PYTHON}';
        export CYBERGYM_SOURCE_DIR='${CYBERGYM_SOURCE_DIR}';
        export MASTER_SERVER_IP='${host}';
        export LLM_SERVICE_PORT='${LLM_SERVICE_PORT}';
        export HARNESS_TYPE='${HARNESS_TYPE}';
        export DEEPSEEK_IMAGE='${DEEPSEEK_IMAGE}';
        export OPENCODE_IMAGE='${OPENCODE_IMAGE}';
        export DEEPSEEK_MODEL='${DEEPSEEK_MODEL}';
        export OPENCODE_MODEL='${OPENCODE_MODEL}';
        export LLM_PROVIDER='${LLM_PROVIDER}';
        export LLM_API_KEY_ENV='${LLM_API_KEY_ENV}';
        export LLM_BASE_URL='${LLM_BASE_URL}';
        export GLM_BASE_URL='${GLM_BASE_URL}';
        export OPENAI_BASE_URL='${OPENAI_BASE_URL}';
        export OPENCODE_BASE_URL='${OPENCODE_BASE_URL}';
        export CAPTURE_PROXY_ENABLED='${CAPTURE_PROXY_ENABLED}';
        export CAPTURE_PROXY_SCRIPT='${CAPTURE_PROXY_SCRIPT}';
        export CAPTURE_PROXY_PORT='${CAPTURE_PROXY_PORT}';
        export CAPTURE_PROXY_VENV='${CAPTURE_PROXY_VENV}';
        export CAPTURE_PROXY_PYTHON='${CAPTURE_PROXY_PYTHON}';
        export CAPTURE_PROXY_UPSTREAM_URL='${CAPTURE_PROXY_UPSTREAM_URL}';
        export LLM_API_FORMAT='${LLM_API_FORMAT}';
        export LLM_MODEL='${LLM_MODEL}';
        export HARNESS_MODEL='${HARNESS_MODEL}';
        export SERVER_PORT='${SERVER_PORT}';
        ${USE_DATATANG_API:+export ALL_PROXY=socks5h://10.17.9.218:1080;export all_proxy=socks5h://10.17.9.218:1080;}
        if [[ \"\${USE_DATATANG_API}\" == \"false\" ]]; then
            unset ALL_PROXY all_proxy;
        fi
        cd '${REMOTE_WORK_DIR}' && \
        ./start_all_one_node.sh \
            --node-rank ${node_rank} \
            --num-nodes ${NUM_NODES} \
            --processes-per-node ${PER_NODE_PROCESS} \
            --exp '${EXP}' \
            --model '${MODEL}' \
            --port ${LLM_SERVICE_PORT} \
            --run-cc-script-path '${RUN_CC_SCRIPT_PATH}' \
            --cybergym-data-dir '${CYBERGYM_DATA_DIR}' \
            --out-root '${OUT_ROOT}' \
            --round-i '${ROUND_NUM}' \
            --timeout '${TIMEOUT}' \
            ${RERUN_TASK_LIST:+--rerun-task-file '${RERUN_TASK_LIST}'}
    " &
    PIDS+=("$!")
    echo "   host ${host} background pid=$!"
done

echo
echo "Wait for all node ssh launch jobs..."
FAIL_COUNT=0
for pid in "${PIDS[@]}"; do
    if ! wait "${pid}"; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "[WARN] pid ${pid} corresponding node launch failed" >&2
    fi
done

echo
if [[ ${FAIL_COUNT} -gt 0 ]]; then
    echo "[ERROR] Total ${FAIL_COUNT} nodes failed to launch! EXP=${EXP}" >&2
    exit 1
fi

echo "========================================"
echo "✅ All node launch finished. EXP=${EXP} ROUND_TAG=${ROUND_TAG} ROUND_NUM=${ROUND_NUM}"
echo "========================================"

RUN_LOG_DIR=$OUT_ROOT/$MODEL/$EXP/$ROUND_TAG
mkdir -p "$RUN_LOG_DIR"
RECORD="$RUN_LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"

{
    echo "===== 运行时间: $(date '+%F %T') ====="
    echo "===== 执行主机: $(hostname) ====="
    echo "===== 命令行: $0 $@ ====="
    echo "===== 脚本内容 ====="
    cat "$0"
} > "$RECORD"
