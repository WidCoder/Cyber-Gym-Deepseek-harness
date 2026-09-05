#!/bin/bash
# 并行在远端节点加载cybergym所需docker镜像包
# IP列表读取 llm_master.txt，去除空白、注释

HOST_FILE="glm53flash_ip.txt"
# HOST_FILE="jt236_ip.txt"

# 读取host文件，过滤注释、空行
if [[ ! -f "${HOST_FILE}" ]]; then
    echo "[ERROR] host文件不存在: ${HOST_FILE}" >&2
    exit 1
fi

mapfile -t HOSTS < <(sed 's/#.*//' "${HOST_FILE}" | sed '/^\s*$/d')

NUM_HOST=${#HOSTS[@]}
if [[ "${NUM_HOST}" -eq 0 ]]; then
    echo "[ERROR] llm_master.txt 没有读到有效IP" >&2
    exit 1
fi

echo "将要在 ${NUM_HOST} 个节点加载镜像：${HOSTS[*]}"

declare -a PIDS=()
for h in "${HOSTS[@]}"; do
    echo ">> 节点 ${h} 开始加载镜像"
    ssh -n "$h" "
        docker load -i /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/image_build/claude-cybergym_v4.tar;
        docker load -i /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/images_binary/cybergym_images.tar.gz
    " &
    PIDS+=("$!")
done

# 等待全部ssh后台任务完成
FAIL_COUNT=0
for pid in "${PIDS[@]}"; do
    if ! wait "$pid"; then
        ((FAIL_COUNT++))
        echo "[WARN] pid $pid 对应节点镜像加载失败" >&2
    fi
done

if [[ ${FAIL_COUNT} -gt 0 ]]; then
    echo "[ERROR] 共计 ${FAIL_COUNT} 个节点镜像加载失败！" >&2
    exit 1
fi

echo "✅ 所有节点docker镜像加载完成"