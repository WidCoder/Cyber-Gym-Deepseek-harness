#!/usr/bin/env bash

# Source this file before the distributed Anthropic/DSH run.
# The cluster paths below intentionally match the existing project runbook.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Usage: source $0" >&2
  exit 2
fi

# These are the paths used by the production checkout on the cluster. Keep
# them explicit: the controller and every SSH-launched worker must agree.
export CYBERGYM_REPO_ROOT="/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym"
export CYBERGYM_SOURCE_DIR="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main"
export CYBERGYM_PYTHON="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/.venv/bin/python"
export IMAGE_TAR="/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym/image_build/cybergym-deepseek_claude-v1.tar"
export CYBERGYM_FULL_DATA_DIR="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/cybergym_data/data-heyu/cybergym/data"

export DEEPSEEK_IMAGE="cybergym-deepseek:claude-v1"
export MASTER_SERVER_IP="10.17.10.205"
export LLM_SERVICE_PORT="31542"
export SERVER_PORT="8668"

export MODEL="glm-5.3-flash"
export LLM_MODEL="glm-5.3-flash"
export DEEPSEEK_MODEL="glm-5.3-flash"
export GLM_API_KEY="${GLM_API_KEY:-EMPTY}"

export HARNESS_TYPE="deepseek"
export LLM_PROVIDER="anthropic"
export LLM_API_KEY_ENV="GLM_API_KEY"
export LLM_API_FORMAT="anthropic-messages"

export CAPTURE_PROXY_ENABLED="true"
export CAPTURE_PROXY_SCRIPT="/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym/capture_proxy/proxy.py"
export CAPTURE_PROXY_VENV="/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/.venv"
export CAPTURE_PROXY_UPSTREAM_URL="http://10.17.5.80:31542"
export CAPTURE_PROXY_PORT="31545"
export CAPTURE_PROXY_TIMEOUT="${CAPTURE_PROXY_TIMEOUT:-300}"
export CAPTURE_PROXY_STARTUP_TIMEOUT="${CAPTURE_PROXY_STARTUP_TIMEOUT:-30}"

export CYBERGYM_DATA_DIR="${CYBERGYM_FULL_DATA_DIR}"
export OUT_ROOT="/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym/output"
export HOST_FILE="/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym/glm_5_1_scripts/distribute_scripts/glm53flash_ip.txt"
export PYTHONPATH="${CYBERGYM_REPO_ROOT}:${CYBERGYM_SOURCE_DIR}:${PYTHONPATH:-}"

if [[ ! -d "${CYBERGYM_SOURCE_DIR}/cybergym" ]]; then
  echo "ERROR: CyberGym source directory not found: ${CYBERGYM_SOURCE_DIR}" >&2
  return 1
fi
if [[ ! -x "${CYBERGYM_PYTHON}" ]]; then
  echo "ERROR: CyberGym Python not executable: ${CYBERGYM_PYTHON}" >&2
  return 1
fi
if [[ ! -f "${CAPTURE_PROXY_VENV}/bin/activate" ]]; then
  echo "ERROR: capture proxy virtualenv not found: ${CAPTURE_PROXY_VENV}" >&2
  return 1
fi
export CAPTURE_PROXY_PYTHON="${CYBERGYM_PYTHON}"
if [[ ! -d "${CYBERGYM_REPO_ROOT}" ]]; then
  echo "ERROR: repository directory not found: ${CYBERGYM_REPO_ROOT}" >&2
  return 1
fi
if [[ ! -f "${CAPTURE_PROXY_SCRIPT}" ]]; then
  echo "ERROR: capture proxy script not found: ${CAPTURE_PROXY_SCRIPT}" >&2
  return 1
fi
if [[ ! -f "${HOST_FILE}" ]]; then
  echo "ERROR: host file not found: ${HOST_FILE}" >&2
  return 1
fi
if [[ ! -d "${CYBERGYM_DATA_DIR}/arvo" ]]; then
  echo "ERROR: CyberGym data directory not found: ${CYBERGYM_DATA_DIR}" >&2
  return 1
fi

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
