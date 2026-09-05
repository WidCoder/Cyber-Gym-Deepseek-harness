#!/bin/bash
# 停止所有节点 cybergym 相关进程脚本
# 读取 llm_master.txt 获取节点IP列表，支持#注释、空行

# HOST_FILE="glm53flash_v10_ip.txt"
# HOST_FILE="glm53flash_ip.txt"
HOST_FILE="jt236_ip.txt"   

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hostfile)
            HOST_FILE="$2"
            shift 2
            ;;
        --hostfile=*)
            HOST_FILE="${1#*=}"
            shift
            ;;
        *)
            echo "[ERROR] 未知参数: $1" >&2
            exit 1
            ;;
    esac
done

if [[ ! -f "${HOST_FILE}" ]]; then
    echo "[ERROR] 文件不存在: ${HOST_FILE}" >&2
    exit 1
fi

if [[ ! -f "${HOST_FILE}" ]]; then
    echo "[ERROR] 文件不存在: ${HOST_FILE}" >&2
    exit 1
fi

# 读取IP，去除注释、空行
mapfile -t HOSTS < <(sed 's/#.*//' "${HOST_FILE}" | sed '/^\s*$/d')

NUM_HOST=${#HOSTS[@]}
if [[ "${NUM_HOST}" -eq 0 ]]; then
    echo "[ERROR] llm_master.txt 未读取到有效节点IP" >&2
    exit 1
fi

echo "将要停止 ${NUM_HOST} 个节点的评测进程：${HOSTS[*]}"

declare -a PIDS=()
for h in "${HOSTS[@]}"; do
    echo ">> 节点 ${h} 执行 stop_all_one_node.sh"
    ssh -n "$h" "
cd /gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym/glm_5_1_scripts/distribute_scripts && ./stop_all_one_node.sh
" &
    PIDS+=("$!")
done

FAIL_COUNT=0
for pid in "${PIDS[@]}"; do
    if ! wait "$pid"; then
        ((FAIL_COUNT++))
        echo "[WARN] pid ${pid} 节点停止脚本执行失败" >&2
    fi
done

if [[ ${FAIL_COUNT} -gt 0 ]]; then
    echo "[ERROR] ${FAIL_COUNT} 个节点 stop_all_one_node.sh 执行异常" >&2
    exit 1
fi

echo "✅ 全部节点停止脚本调用完成"
