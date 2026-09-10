# GLM-5.3-Flash Deployment

This repository contains the evaluation scripts and the API capture proxy. It
does not contain Docker image archives, the CyberGym benchmark data, or the
external `cybergym` Python package. Those remain runtime prerequisites on the
server and are selected through environment variables.

## 1. Clone on the shared filesystem

```bash
cd /gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi
git clone https://github.com/WidCoder/Cyber-Gym-Deepseek-harness.git cybergym
cd cybergym
```

If the directory already exists:

```bash
git pull --ff-only origin main
```

## 2. Select the Python runtime

The scripts prefer `CYBERGYM_SOURCE_DIR` for the installed CyberGym package
and its virtualenv. Set it to the existing benchmark checkout on host 304:

```bash
export CYBERGYM_REPO_ROOT="$PWD"
export CYBERGYM_SOURCE_DIR=/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main
export CYBERGYM_PYTHON="$CYBERGYM_SOURCE_DIR/.venv/bin/python"
test -x "$CYBERGYM_PYTHON"
"$CYBERGYM_PYTHON" -c 'import cybergym, docker, httpx; print("RUNTIME_OK")'
"$CYBERGYM_PYTHON" -m pip install -r "$CYBERGYM_REPO_ROOT/capture_proxy/requirements.txt"
```

`CYBERGYM_SOURCE_DIR` may point at another checkout if that checkout contains
the `cybergym` package and the required dependencies.

## 3. Configure GLM and capture

The API key must be the raw value only. Do not include `Bearer`, quotes, a URL,
or a JSON object.

```bash
export HARNESS_TYPE=deepseek
export LLM_PROVIDER=glm
export LLM_API_KEY_ENV=GLM_API_KEY
export GLM_API_KEY=local-sglang
export MODEL=glm-5.3-flash
export LLM_MODEL=glm-5.3-flash
export DEEPSEEK_MODEL=glm-5.3-flash
export LLM_SERVICE_PORT=31542
export CAPTURE_PROXY_ENABLED=true
export CAPTURE_PROXY_SCRIPT="$CYBERGYM_REPO_ROOT/capture_proxy/proxy.py"
export CAPTURE_PROXY_PYTHON="$CYBERGYM_PYTHON"
export CAPTURE_PROXY_UPSTREAM_URL=http://10.17.5.80:31542
export CAPTURE_PROXY_PORT=31545
```

The upstream value intentionally has no `/v1`. The proxy appends the incoming
request path, so Harness traffic becomes
`http://10.17.5.80:31542/v1/chat/completions`.

Check the model service before evaluating:

```bash
curl -fsS -H "Authorization: Bearer ${GLM_API_KEY}" http://10.17.5.80:31542/v1/models
```

## 4. One-request capture test

Run this before a full evaluation:

```bash
CAPTURE_PROXY_UPSTREAM_URL=http://10.17.5.80:31542 LLM_MODEL=glm-5.3-flash "$CYBERGYM_REPO_ROOT/scripts/test_capture_proxy.sh"
```

Success ends with `SINGLE_OPENAI_CAPTURE_TEST=PASS`. It proves the proxy is
reachable, GLM returned an OpenAI SSE stream, `[DONE]` was received, and the
capture was persisted with `state=complete`.

## 5. Full distributed evaluation

Use a new experiment name for every run. The host list must be the actual
evaluation worker list; `glm53flash_ip.txt` is included as the current list.

```bash
export ROOT_DIR="$CYBERGYM_REPO_ROOT"
export HOST_FILE="$CYBERGYM_REPO_ROOT/glm_5_1_scripts/distribute_scripts/glm53flash_ip.txt"
export CYBERGYM_DATA_DIR="$CYBERGYM_SOURCE_DIR/cybergym_data/data"
export OUT_ROOT="$CYBERGYM_REPO_ROOT/output"
mkdir -p "$OUT_ROOT"

bash "$CYBERGYM_REPO_ROOT/glm_5_1_scripts/distribute_scripts/dis_launch_all.sh" \
  --root-dir "$CYBERGYM_REPO_ROOT" \
  --host-file "$HOST_FILE" \
  --harness deepseek \
  --exp "glm53-dsh-full-$(date +%Y%m%d-%H%M%S)" \
  --round-i 1 \
  --server-port 8668 \
  --capture-proxy-upstream-url http://10.17.5.80:31542
```

The launcher passes the raw key to each remote shell through SSH stdin, so the
remote account does not need `AcceptEnv=GLM_API_KEY`. It also uses the bundled
proxy and the explicit Python executable.

## 6. Verify the output

After a worker finishes, inspect one task:

```bash
find "$CYBERGYM_REPO_ROOT/output/glm-5.3-flash" -name result.json -print | tail -1
```

For the selected task directory:

```bash
python - "$TASK_DIR/result.json" <<'PY'
import json, sys
v = json.load(open(sys.argv[1], encoding="utf-8"))
print("execution:", v.get("execution"))
print("verification:", v.get("verification"))
print("api_capture:", v.get("api_capture"))
print("training:", v.get("training"))
PY
```

For a new run, a healthy task should have `execution.status=completed`,
`verification.status=verified` or `completed_not_verified`, and
`api_capture.complete_count > 0`. A task with `execution.status=failed` or
`verification.status=pending` did not finish the normal Harness flow. A
`partial_count > 0` means at least one captured response was interrupted and
must not be used as a complete training turn. The result's
`capture_manifest.json` links each request to the Harness logs and raw
request/response paths.

Count final exported records:

```bash
find "$CYBERGYM_REPO_ROOT/output/glm-5.3-flash" -name train.jsonl -type f -exec wc -l {} +
```

The worker-level exporter writes one record per complete API request. For one
multi-turn record per task, run the offline finalizer after the round:

```bash
RUN_DIR="${CYBERGYM_REPO_ROOT}/output/glm-5.3-flash/<experiment>/round1"
"${CYBERGYM_PYTHON}" "${CYBERGYM_REPO_ROOT}/scripts/export_task_trajectories.py" \
  --run-dir "${RUN_DIR}" \
  --output "${RUN_DIR}/task_trajectories.jsonl" \
  --report "${RUN_DIR}/task_trajectories.report.json" \
  --only-verified
```

The finalizer uses each task manifest as the boundary, validates complete 2xx
captures, preserves tool/reasoning messages, and joins later requests only
when their normalized history exactly extends the previous conversation. The
adjacent report explains skipped tasks. Use `--recover-terminal-sse`
only for legacy runs created before commit `95bd83b`.

For a one-command run summary:

```bash
"${CYBERGYM_PYTHON}" "${CYBERGYM_REPO_ROOT}/scripts/analyze_run.py" \
  --run-dir "${RUN_DIR}"
```
