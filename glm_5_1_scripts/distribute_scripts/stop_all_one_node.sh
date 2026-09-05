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

# 关闭所有agent执行进程
pkill -KILL -f 'run_cc'

# # 停止所有相关容器
# docker ps -q --filter "ancestor=claude-cybergym:v4" | xargs -r docker stop
# 停止并删除所有评测容器
docker ps -aq --filter "ancestor=claude-cybergym:v4" | xargs -r docker rm -f

# 关闭评测服务
pkill -KILL -f 'cybergym.server'

echo "Stop Done!"
