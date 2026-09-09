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

Expected capture conditions for a new run are `complete_count > 0` and
`partial_count = 0` for successful calls. Each task also keeps
`capture_manifest.json`, `trajectory.jsonl`, and `train.jsonl`; the manifest
links every capture to the Harness log files and raw request/response paths.

Count final exported records:

```bash
find "$CYBERGYM_REPO_ROOT/output/glm-5.3-flash" -name train.jsonl -type f -exec wc -l {} +
```

The current exporter writes one training record per complete API capture. It
preserves each request's complete message history and the reconstructed
assistant response; it does not merge all requests from one task into one
record.
