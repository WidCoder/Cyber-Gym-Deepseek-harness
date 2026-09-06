# GLM-5.3-Flash CyberGym 运行手册

本文假设 GLM-5.3-Flash 已由 SGLang 提供 OpenAI-compatible API：

```text
http://10.17.5.153:31542/v1
model = glm-5.3-flash
```

API key 只通过环境变量传递。`local-sglang` 仅是本机服务所需的占位值，不是写入代码的密钥。

## 能力边界

| Harness | GLM-5.3-Flash | 协议 |
|---|---:|---|
| DeepSeek Harness (`dsh`) | 支持 | OpenAI-compatible |
| OpenCode | 支持 | OpenAI-compatible |
| 原有 Claude Code | 保持原流程 | Anthropic Messages |

当前 GLM 服务只确认提供 `/v1/chat/completions`。因此不能把 OpenAI URL 直接填到 Claude Code 的 `ANTHROPIC_BASE_URL`；两者协议不同。Claude 默认流程没有改动。若要让 Claude Code 也调用 GLM，需要额外部署 Anthropic-to-OpenAI 协议网关，或让推理服务提供 `/v1/messages`，这不属于本适配器的默认路径。

## 统一环境变量

```bash
export CYBERGYM_REPO=/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym
export CYBERGYM_SRC=/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main
export CYBERGYM_DATA=$CYBERGYM_SRC/cybergym_data/data

export HARNESS_TYPE=deepseek       # deepseek 或 opencode
export LLM_PROVIDER=glm
export LLM_API_KEY_ENV=GLM_API_KEY
export GLM_API_KEY=local-sglang
export LLM_BASE_URL=http://10.17.5.153:31542/v1
export GLM_BASE_URL=$LLM_BASE_URL
export LLM_API_FORMAT=openai-completions
export LLM_MODEL=glm-5.3-flash
export DSH_PROFILE=agent-default-model
export DEEPSEEK_MODEL=glm-5.3-flash
export OPENCODE_MODEL=glm-5.3-flash
export DEEPSEEK_IMAGE=cybergym-deepseek:claude-v1
export OPENCODE_IMAGE=cybergym-opencode:claude-v1
```

先确认模型服务：

```bash
curl -fsS http://10.17.5.153:31542/v1/models
```

返回的 `id` 必须是 `glm-5.3-flash`。

## DeepSeek Harness：单任务

```bash
source "$CYBERGYM_SRC/.venv/bin/activate"
python "$CYBERGYM_REPO/scripts/run_tasks.py" \
  --harness deepseek \
  --task-id arvo:3569 \
  --image cybergym-deepseek:claude-v1 \
  --model glm-5.3-flash \
  --log-dir "$CYBERGYM_REPO/output/glm-5.3-flash/dsh-single/logs" \
  --tmp-dir "$CYBERGYM_REPO/output/glm-5.3-flash/dsh-single/tmp" \
  --data-dir "$CYBERGYM_DATA" \
  --server http://10.17.5.153:8667 \
  --timeout 1800
```

第二个样本只需改为 `--task-id arvo:10055`。

## OpenCode：单任务

```bash
source "$CYBERGYM_SRC/.venv/bin/activate"
python "$CYBERGYM_REPO/scripts/run_tasks.py" \
  --harness opencode \
  --task-id arvo:3569 \
  --image cybergym-opencode:claude-v1 \
  --model glm-5.3-flash \
  --log-dir "$CYBERGYM_REPO/output/glm-5.3-flash/opencode-single/logs" \
  --tmp-dir "$CYBERGYM_REPO/output/glm-5.3-flash/opencode-single/tmp" \
  --data-dir "$CYBERGYM_DATA" \
  --server http://10.17.5.153:8667 \
  --timeout 1800
```

OpenCode 适配器会为每个任务生成临时 `opencode.json`，注册 `openai/glm-5.3-flash` 和 `baseURL`，任务结束后删除；配置中不写入 API key。

## 指定任务列表

```bash
printf '%s\n' arvo:3569 arvo:10055 > /tmp/glm_tasks.txt
python "$CYBERGYM_REPO/scripts/run_tasks.py" \
  --harness deepseek \
  --task-list /tmp/glm_tasks.txt \
  --image cybergym-deepseek:claude-v1 \
  --model glm-5.3-flash \
  --log-dir "$CYBERGYM_REPO/output/glm-5.3-flash/dsh-list/logs" \
  --tmp-dir "$CYBERGYM_REPO/output/glm-5.3-flash/dsh-list/tmp" \
  --data-dir "$CYBERGYM_DATA" \
  --server http://10.17.5.153:8667 \
  --timeout 1800
```

将 `--harness deepseek` 和输出目录替换为 `opencode` 即可测试 OpenCode 任务列表。

## 分布式全量评测

编辑个人仓库中的 `glm_5_1_scripts/distribute_scripts/dis_launch_all.sh`，至少设置：

```bash
MODEL="glm-5.3-flash"
HOST_FILE="glm53flash_ip.txt"
LLM_SERVICE_PORT=31542
HARNESS_TYPE="deepseek"       # 或 opencode
LLM_PROVIDER="glm"
LLM_API_KEY_ENV="GLM_API_KEY"
LLM_BASE_URL="http://10.17.5.153:31542/v1"
GLM_BASE_URL="$LLM_BASE_URL"
LLM_API_FORMAT="openai-completions"
LLM_MODEL="glm-5.3-flash"
DEEPSEEK_MODEL="glm-5.3-flash"
OPENCODE_MODEL="glm-5.3-flash"
SERVER_PORT=8667
```

在当前 shell 中提供占位 key：

```bash
export GLM_API_KEY=local-sglang
```

然后运行：

```bash
cd "$CYBERGYM_REPO"
bash glm_5_1_scripts/distribute_scripts/dis_launch_all.sh \
  --root-dir "$CYBERGYM_REPO" \
  --host-file glm53flash_ip.txt \
  --server-port 8667
```

全量模式会扫描 `$CYBERGYM_DATA/arvo` 和 `$CYBERGYM_DATA/oss-fuzz`。如只想跑两个样本，使用前面的 `scripts/run_tasks.py`；分布式脚本的 `RERUN_TASK_LIST` 也可以指定任务文件。

## 调用流程

```text
run_tasks.py / dis_launch_all.sh
        |
        v
harness_selector.py 读取 HARNESS_TYPE
        |
   +----+------------------+
   |                       |
deepseek                opencode
   |                       |
run_deepseek.py        run_opencode.py
   |                       |
生成 DSH patch          生成临时 opencode.json
   |                       |
Docker DeepSeek 镜像    Docker OpenCode 镜像
   |                       |
       http://10.17.5.153:31542/v1
                    |
             GLM SGLang 服务
                    |
  Agent 在 /workspace 生成 PoC 并调用 submit.sh
                    |
CyberGym 验证服务 http://10.17.5.153:8667
```

DeepSeek Harness 的 GLM 关键配置是 `cybergym-openai` provider、`openai-completions`、`baseURL` 和模型 ID；OpenCode 的关键配置是 `openai/glm-5.3-flash`。两条路径都会将任务工作目录挂载到 `/workspace`，再将日志写回个人仓库。

## 日志和排错

```bash
find "$CYBERGYM_REPO/output/glm-5.3-flash" -name console.log -o -name timing.json
docker logs --since 5m glm53
```

必须看到 GLM 服务的：

```text
POST /v1/chat/completions ... 200 OK
```

如果 OpenCode 报 `ProviderModelNotFoundError`，说明使用了旧代码或临时配置没有挂载，先确认 Git 提交 `8318004` 及其之后版本。若 DSH 报 provider/model 配置错误，检查 `logs/dsh-runtime.patch.yml`，其中不应出现 API key，只应出现 `apiKeyEnv`。
