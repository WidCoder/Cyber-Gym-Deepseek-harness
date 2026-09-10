#!/usr/bin/env bash

# Source this file before a single-node Anthropic/DSH smoke run.
# Override any variable before `source` when using a different host or port.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Usage: source $0" >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export CYBERGYM_REPO_ROOT="${CYBERGYM_REPO_ROOT:-$(cd -- "${script_dir}/.." && pwd)}"

export CYBERGYM_SOURCE_DIR="${CYBERGYM_SOURCE_DIR:-/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main}"
export IMAGE_TAR="${IMAGE_TAR:-/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym/image_build/cybergym-deepseek_claude-v1.tar}"
export CYBERGYM_FULL_DATA_DIR="${CYBERGYM_FULL_DATA_DIR:-/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/cybergym_data/data-heyu/cybergym/data}"

export DEEPSEEK_IMAGE="${DEEPSEEK_IMAGE:-cybergym-deepseek:claude-v1}"
export MASTER_SERVER_IP="${MASTER_SERVER_IP:-10.17.10.205}"
export LLM_SERVICE_PORT="${LLM_SERVICE_PORT:-31542}"
export SERVER_PORT="${SERVER_PORT:-18668}"

export MODEL="${MODEL:-glm-5.3-flash}"
export LLM_MODEL="${LLM_MODEL:-glm-5.3-flash}"
export DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-glm-5.3-flash}"
export GLM_API_KEY="${GLM_API_KEY:-EMPTY}"

export HARNESS_TYPE="deepseek"
export LLM_PROVIDER="anthropic"
export LLM_API_KEY_ENV="GLM_API_KEY"
export LLM_API_FORMAT="anthropic-messages"

export CAPTURE_PROXY_ENABLED="true"
export CAPTURE_PROXY_SCRIPT="${CAPTURE_PROXY_SCRIPT:-${CYBERGYM_REPO_ROOT}/capture_proxy/proxy.py}"
export CAPTURE_PROXY_UPSTREAM_URL="${CAPTURE_PROXY_UPSTREAM_URL:-http://10.17.5.80:31542}"
export CAPTURE_PROXY_PORT="${CAPTURE_PROXY_PORT:-31645}"
export CAPTURE_PROXY_TIMEOUT="${CAPTURE_PROXY_TIMEOUT:-300}"
export CAPTURE_PROXY_STARTUP_TIMEOUT="${CAPTURE_PROXY_STARTUP_TIMEOUT:-30}"

export CYBERGYM_DATA_DIR="${CYBERGYM_DATA_DIR:-${CYBERGYM_FULL_DATA_DIR}}"
export OUT_ROOT="${OUT_ROOT:-${CYBERGYM_REPO_ROOT}/output}"
export HOST_FILE="${HOST_FILE:-${CYBERGYM_REPO_ROOT}/glm_5_1_scripts/distribute_scripts/glm53flash_ip.txt}"
export PYTHONPATH="${CYBERGYM_REPO_ROOT}:${CYBERGYM_SOURCE_DIR}:${PYTHONPATH:-}"

runtime_helper="${CYBERGYM_REPO_ROOT}/scripts/resolve_cybergym_runtime.sh"
if [[ ! -f "${runtime_helper}" ]]; then
  echo "ERROR: runtime helper not found: ${runtime_helper}" >&2
  return 1
fi

source "${runtime_helper}"
if ! cybergym_resolve_runtime; then
  echo "ERROR: cannot resolve a CyberGym Python runtime; set CYBERGYM_SOURCE_DIR" >&2
  return 1
fi

export CYBERGYM_SOURCE_DIR="${CYBERGYM_RUNTIME_DIR}"
export CYBERGYM_PYTHON="${CYBERGYM_RUNTIME_PYTHON}"
export CAPTURE_PROXY_PYTHON="${CYBERGYM_PYTHON}"
export PYTHONPATH="${CYBERGYM_REPO_ROOT}:${CYBERGYM_SOURCE_DIR}:${PYTHONPATH:-}"
test -x "${CYBERGYM_PYTHON}"
test -f "${CAPTURE_PROXY_SCRIPT}"
test -d "${CYBERGYM_DATA_DIR}/arvo"

echo "GLM53_ANTHROPIC_ENV=READY"
echo "CYBERGYM_REPO_ROOT=${CYBERGYM_REPO_ROOT}"
echo "CYBERGYM_SOURCE_DIR=${CYBERGYM_SOURCE_DIR}"
echo "CYBERGYM_PYTHON=${CYBERGYM_PYTHON}"
echo "DEEPSEEK_IMAGE=${DEEPSEEK_IMAGE}"
echo "MASTER_SERVER_IP=${MASTER_SERVER_IP}"
echo "CAPTURE_PROXY_UPSTREAM_URL=${CAPTURE_PROXY_UPSTREAM_URL}"
echo "CAPTURE_PROXY_PORT=${CAPTURE_PROXY_PORT}"
echo "SERVER_PORT=${SERVER_PORT}"
echo "LLM_PROVIDER=${LLM_PROVIDER}"
echo "LLM_API_FORMAT=${LLM_API_FORMAT}"
echo "LLM_MODEL=${LLM_MODEL}"
