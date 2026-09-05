#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 基础路径收敛
# ============================================================
# Cybergym 源码仓库根目录（仓库内路径统一基于此拼接）
repo_dir="${REPO_DIR:-/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main}"

# 激活 Python 虚拟环境
source "${repo_dir}/.venv/bin/activate"

# ============================================================
# 服务配置（优先从环境变量读取，由上层调度脚本传入）
# ============================================================
# 服务监听 IP：自动获取本机 10.17 段地址
SERVER_IP=$(
  ifconfig |
    awk '/inet / {print $2}' |
    grep '^10\.17\.' |
    head -n 1
)

if [[ -z "$SERVER_IP" ]]; then
  echo "ERROR: 没有找到 10.17 开头的本机 IP" >&2
  exit 1
fi

# 服务端口（继承上层环境变量，默认 8666）
PORT="${SERVER_PORT:-8666}"

# POC 数据库与日志目录（必须由上层传入，与 worker 脚本保持一致）
if [[ -z "${POC_SAVE_DIR:-}" ]]; then
  echo "ERROR: POC_SAVE_DIR env must be passed from start_all_one_node.sh" >&2
  exit 1
fi
mkdir -p "${POC_SAVE_DIR}"

# 验证服务二进制数据目录（保留默认值，支持环境变量覆盖）
CYBERGYM_SERVER_DATA_DIR="${CYBERGYM_SERVER_DATA_DIR:-/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/zhangyuyao/cybergym-server-data}"

# mask 映射文件路径（基于仓库根目录拼接）
MASK_MAP_PATH="${repo_dir}/mask_map.json"

# ============================================================
# 启动验证服务
# ============================================================
echo "Starting cybergym server on ${SERVER_IP}:${PORT}"
echo "DB path: ${POC_SAVE_DIR}/poc.db"
echo "Binary dir: ${CYBERGYM_SERVER_DATA_DIR}"
echo "Mask map: ${MASK_MAP_PATH}"

python3 -m cybergym.server \
    --host "${SERVER_IP}" \
    --port "${PORT}" \
    --mask_map_path "${MASK_MAP_PATH}" \
    --log_dir "${POC_SAVE_DIR}" \
    --db_path "${POC_SAVE_DIR}/poc.db" \
    --binary_dir "${CYBERGYM_SERVER_DATA_DIR}"