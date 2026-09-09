#!/usr/bin/env bash
set -euo pipefail

# Load all required CyberGym images onto a host set.
# HOST_FILE may contain literal hosts or compact ranges such as:
#   SHLG-PSC-ZS3F1-SPOD-PM-OS07-CLUSTER-ZS-[5-9,11-13]

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HOST_FILE="${HOST_FILE:-${SCRIPT_DIR}/glm53flash_ip.txt}"

if [[ "${HOST_FILE}" != /* && ! -f "${HOST_FILE}" && -f "${SCRIPT_DIR}/${HOST_FILE}" ]]; then
    HOST_FILE="${SCRIPT_DIR}/${HOST_FILE}"
fi

if [[ ! -f "${HOST_FILE}" ]]; then
    echo "[ERROR] host file not found: ${HOST_FILE}" >&2
    exit 1
fi

# Expand one token and append the resulting hostnames to HOSTS.
expand_host_token() {
    local token="$1"
    local prefix="" ranges="" part start end node

    if [[ "${token}" =~ ^(.*)-\[([0-9,-]+)\]$ ]]; then
        prefix="${BASH_REMATCH[1]}"
        ranges="${BASH_REMATCH[2]}"
        IFS=',' read -r -a range_parts <<< "${ranges}"
        for part in "${range_parts[@]}"; do
            if [[ "${part}" =~ ^([0-9]+)-([0-9]+)$ ]]; then
                start="${BASH_REMATCH[1]}"
                end="${BASH_REMATCH[2]}"
                if (( 10#${start} > 10#${end} )); then
                    echo "[ERROR] descending host range is not supported: ${token}" >&2
                    return 1
                fi
                for ((node=10#${start}; node<=10#${end}; node++)); do
                    HOSTS+=("${prefix}-${node}")
                done
            elif [[ "${part}" =~ ^[0-9]+$ ]]; then
                HOSTS+=("${prefix}-${part}")
            else
                echo "[ERROR] invalid host range item '${part}' in '${token}'" >&2
                return 1
            fi
        done
    else
        HOSTS+=("${token}")
    fi
}

HOSTS=()
while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%%#*}"
    read -r -a host_tokens <<< "${line}"
    for token in "${host_tokens[@]}"; do
        [[ -n "${token}" ]] || continue
        expand_host_token "${token}"
    done
done < "${HOST_FILE}"

NUM_HOST=${#HOSTS[@]}
if [[ "${NUM_HOST}" -eq 0 ]]; then
    echo "[ERROR] host file has no valid hosts: ${HOST_FILE}" >&2
    exit 1
fi

# Defaults preserve the original two loads. Extra paths are configurable because
# harness tarballs may be stored in different shared-storage locations.
CLAUDE_IMAGE_TAR="${CLAUDE_IMAGE_TAR:-/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/image_build/claude-cybergym_v4.tar}"
CYBERGYM_IMAGE_TAR="${CYBERGYM_IMAGE_TAR:-/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/images_binary/cybergym_images.tar.gz}"
GLM_IMAGE_TAR="${GLM_IMAGE_TAR:-/gpfsprd/jt_kunlun/612452f3b5864290bf42efc45c6394ed/data/wangduqing/docker/sglang-glm5.3.tar}"
CODEX_IMAGE_TAR="${CODEX_IMAGE_TAR:-/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangxiaomeng/cybergym_wxm/test/cybergym_codex/harness/cybergym-codex-v3.tar}"
DEEPSEEK_IMAGE_TAR="${DEEPSEEK_IMAGE_TAR:-/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym/image_build/cybergym-deepseek_claude-v1.tar}"

IMAGE_LABELS=("Claude Code" "CyberGym" "GLM-5.3-Flash" "Codex" "DeepSeek Harness")
IMAGE_TARS=(
    "${CLAUDE_IMAGE_TAR}"
    "${CYBERGYM_IMAGE_TAR}"
    "${GLM_IMAGE_TAR}"
    "${CODEX_IMAGE_TAR}"
    "${DEEPSEEK_IMAGE_TAR}"
)

echo "Loading ${#IMAGE_TARS[@]} image archives onto ${NUM_HOST} hosts from ${HOST_FILE}"
echo "Hosts: ${HOSTS[*]}"
for i in "${!IMAGE_TARS[@]}"; do
    echo "  ${IMAGE_LABELS[${i}]}: ${IMAGE_TARS[${i}]}"
done

declare -a PIDS=()
declare -a PID_HOSTS=()
for host in "${HOSTS[@]}"; do
    echo ">> ${host}: loading image archives"
    remote_command='set -euo pipefail'
    for i in "${!IMAGE_TARS[@]}"; do
        printf -v quoted_label '%q' "${IMAGE_LABELS[${i}]}"
        printf -v quoted_tar '%q' "${IMAGE_TARS[${i}]}"
        remote_command+="; echo '[${host}] loading ${quoted_label}'; test -r ${quoted_tar}; docker load -i ${quoted_tar}"
    done
    ssh -n "${host}" "${remote_command}" &
    PIDS+=("$!")
    PID_HOSTS+=("${host}")
done

FAIL_COUNT=0
for i in "${!PIDS[@]}"; do
    if ! wait "${PIDS[${i}]}"; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "[WARN] host ${PID_HOSTS[${i}]} failed to load one or more image archives" >&2
    fi
done

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    echo "[ERROR] ${FAIL_COUNT}/${NUM_HOST} hosts failed image loading" >&2
    exit 1
fi

echo "All required Docker image archives loaded on ${NUM_HOST} hosts"
