#!/bin/bash
source /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/.venv/bin/activate
cd /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/
# source /gpfsprd/jt/1027010811d84e79a0765ebaaf5fc80f/cyber_security/images/cybergym-main/.venv/bin/activate

# # 添加以下内容：绕过HTTP/HTTPS代理

#export HTTP_PROXY=http://amp-bm-squid:3128      # 如果宿主机确实需要走代理出公网
#export HTTPS_PROXY=http://amp-bm-squid:3128
#export NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,10.17.9.218,10.17.10.16,10.17.9.219
#export no_proxy=localhost,127.0.0.1,10.0.0.0/8,10.17.9.218,10.17.10.16,10.17.9.219



#export CYBERGYM_API_KEY=cybergym-030a0cd7-5908-4862-8ab9-91f2bfc7b56d
export ANTHROPIC_API_KEY="sk-xxxxxx"
export ANTHROPIC_BASE_URL="http://10.17.10.67:31542/"

CYBERGYM_DATA_DIR=/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/cybergym_data/data-heyu/cybergym/data
MODEL=GLM-5.1
OUT_DIR=output/${MODEL}/$(date "+%Y%m%d_%H%M%S")
POC_LOG_DIR=poc_logs/${MODEL}/$(date "+%Y%m%d_%H%M%S")
mkdir -p "${POC_LOG_DIR}"

SERVER_IP=10.17.10.67
SERVER_PORT=8666

POC_SAVE_DIR=./server_poc # dir to save the pocs

# 获取所有可以执行的数据：task_id
task_ids=()
for n in arvo oss-fuzz; do
#for n in arvo; do
    for p in "${CYBERGYM_DATA_DIR}/$n"/*; do
        # ${p##*/} 相当于 basename，获取路径最后一部分
        task_ids+=("$n:${p##*/}")
        # 如arvo:20494、oss-fuzz:42538616
    done
done
total=${#task_ids[@]}
part=$1   # 第一个脚本用 0，第二个用 1，第三个用 2，第四个用 3
parts=$2

start=$(( part * total / parts ))
end=$(( (part + 1) * total / parts ))

task_ids=( "${task_ids[@]:start:end-start}" )

SUCCESS_NUM=0

# 打印一下，确认获取到的 ID 数量
echo "Total tasks found: ${#task_ids[@]}"
echo "Total tasks: ${task_ids[*]}"


for TASK_ID in "${task_ids[@]}"; do
    printf '*%.0s' {1..100}; echo ""
    echo "Processing: $TASK_ID"
    echo "start_accomplish: ${TASK_ID}_$(date '+%Y.%m.%d_%H:%M:%S')"

    # 跑模型
    python examples/agents/claudecode/run_cc.py \
        --image 'claude-code:2.1.89' \
        --model ${MODEL} \
        --log_dir ${OUT_DIR}/logs \
        --tmp_dir ${OUT_DIR}/tmp \
        --data_dir ${CYBERGYM_DATA_DIR} \
        --task_id ${TASK_ID} \
        --server "http://${SERVER_IP}:${SERVER_PORT}" \
        --timeout 36000 \
        --max_iter 150 \
        --difficulty level1
    
    # 验证一下结果
    # 获取 agent_id
    # 1. 先将 TASK_ID 中的冒号转换为下划线（与文件夹前缀匹配）
    prefix="${TASK_ID//:/_}"
    # 2. 使用通配符找到匹配的完整路径
    # ls -d 保证只列出目录名，head -n 1 防止有多个匹配项时出错
    full_path=$(ls -d "${OUT_DIR}/logs/${prefix}-"* 2>/dev/null | head -n 1)

    # 3. 提取 - 后面的字符串
    # ${full_path##*-} 的意思是：删除最后一个 "-" 及其左边的所有内容
    suffix="${full_path##*-}"

    echo "agent_id 是: ${suffix}"

    # 验证
    mkdir -p ${OUT_DIR}/result
    # 
    OUTPUT=$(python3 scripts/verify_agent_result.py \
        --server http://$SERVER_IP:$SERVER_PORT \
        --pocdb_path $POC_SAVE_DIR/poc.db \
        --agent_id ${suffix} | tee ${OUT_DIR}/result/${prefix}_${suffix}.log)
        # --agent_id ${suffix} | tee ${OUT_DIR}/result/$(date '+%Y-%m-%d_%H-%M-%S')_${prefix}_${suffix}.log)

    # 使用 grep -oP (Perl正则) 提取数值
    # \K 表示忽略匹配到的左侧部分，只返回后面的数字

    # 2. 检查输出中是否存在满足条件的行
    # -E 使用扩展正则
    # \b1\b 确保精确匹配数字 1，防止匹配到 11 或 100
    # grep -q 表示静默模式，只返回退出状态（找到为0，没找到为1）
    if echo "$OUTPUT" | grep "'vul_exit_code': 1\b" | grep -q "'fix_exit_code': 0\b"; then
        SUCCESS_NUM=$((SUCCESS_NUM + 1))
        echo ">>> 检测到符合条件的记录。SUCCESS_NUM 已增加至 $SUCCESS_NUM"
    else
        echo ">>> 未发现符合条件的记录（需 vul=1 且 fix=0）。"
    fi

    echo "start_accomplish: ${TASK_ID}_$(date '+%Y.%m.%d_%H:%M:%S')"
    # 关闭PoC, kill
    # ps -aux | grep cybergym.server | awk {'print $2'} | xargs kill -9
    # 3. 关闭当前 Server
    # echo "Killing Server (PID: $SERVER_PID)..."
    # if kill -0 "$SERVER_PID" 2>/dev/null; then
    #     kill -9 "$SERVER_PID"
    # fi

    # sleep 5

done

echo "全部数据都跑完啦，成功的数据有${SUCCESS_NUM}个"

