#!/usr/bin/env bash

# MASTER_SERVER_IP=$(
#   ifconfig |
#     awk '/inet / {print $2}' |
#     grep '^10\.17\.' |
#     head -n 1
# )

# 关闭所有进程
pkill -KILL -f 'start_one_process'

pkill -KILL -f 'anthropic_cache_proxy'

pkill -KILL -f 'anthropic_full_capture_proxy'
pkill -KILL -f 'capture_proxy/proxy.py'

# Prefer the per-round PID files so an older proxy implementation is also
# stopped when its command line does not contain the bundled path.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -d "${script_dir}/logs" ]]; then
  while IFS= read -r pid_file; do
    pid=$(<"${pid_file}")
    if [[ "${pid}" =~ ^[0-9]+$ ]]; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  done < <(find "${script_dir}/logs" -type f -path '*/capture_logs/proxy.pid' -print)
fi

# 关闭所有agent执行进程
pkill -KILL -f 'run_cc'

# 停止并删除所有评测容器
for image in \
  claude-cybergym:v4 \
  cybergym-deepseek:claude-v1 \
  cybergym-opencode:claude-v1; do
  docker ps -aq --filter "ancestor=${image}" | xargs -r docker rm -f
done

# 关闭评测服务
pkill -KILL -f 'cybergym.server'

echo "Stop Done!"
