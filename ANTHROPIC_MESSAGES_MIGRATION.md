# Anthropic Messages Compatibility

The bundled proxy is a transparent capture proxy. It forwards the incoming
path and body without translating protocols:

```text
Harness -> /v1/messages -> proxy -> upstream /v1/messages
Harness -> /v1/chat/completions -> proxy -> upstream /v1/chat/completions
```

The proxy does not convert Anthropic Messages into OpenAI Chat Completions or
the reverse. This is intentional: changing the request protocol online would
change the Harness behavior and can break tool calls, verification, or session
logs.

## Reference project comparison

`yida12345/anthropic_full_capture_proxy` is a strong reference for the
Anthropic-only case. It provides:

- one capture directory per request;
- raw request and response persistence;
- Anthropic SSE aggregation through `message_stop`;
- post-run association through Anthropic `message.id` and session JSONL;
- ShareGPT export and recovery tools.

The bundled implementation keeps those useful capture properties and adds the
CyberGym-specific behavior already required by this repository:

- OpenAI Chat Completions capture support for the current GLM endpoint;
- per-worker capture roots and proxy ports;
- `capture_manifest.json` linked to each CyberGym `result.json`;
- task-level offline trajectory aggregation;
- `trust_env=False` so cluster `HTTP_PROXY` settings do not reroute private
  GLM traffic;
- a single proxy process per worker.

Copying the reference repository over `capture_proxy/` would remove the
OpenAI-compatible path and would not solve protocol conversion. The current
repository is therefore the safer base for CyberGym.

## Verify the upstream before switching

On host 304, after activating the same Python environment used by the worker:

```bash
cd /gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/wangyingqi/cybergym
export CYBERGYM_REPO_ROOT="$PWD"
export CYBERGYM_SOURCE_DIR=/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main
export CYBERGYM_PYTHON="$CYBERGYM_SOURCE_DIR/.venv/bin/python"
source "$CYBERGYM_SOURCE_DIR/.venv/bin/activate"
export CAPTURE_PROXY_UPSTREAM_URL=http://10.17.5.80:31542
export LLM_MODEL=glm-5.3-flash
```

First verify the existing OpenAI endpoint remains healthy:

```bash
CAPTURE_PROXY_PYTHON="$CYBERGYM_PYTHON" \
  "$CYBERGYM_REPO_ROOT/scripts/test_capture_proxy.sh"
```

Then probe Anthropic Messages:

```bash
CAPTURE_PROXY_PYTHON="$CYBERGYM_PYTHON" \
  "$CYBERGYM_REPO_ROOT/scripts/test_capture_proxy_anthropic.sh"
```

Only this result authorizes Anthropic mode:

```text
SINGLE_ANTHROPIC_CAPTURE_TEST=PASS capture_id=... message_id=...
```

The test requires all of the following:

- HTTP 200 from `POST /v1/messages`;
- an Anthropic SSE response, not an OpenAI `choices` response;
- `message_start` with a message id;
- `message_stop` as the stream terminator;
- a persisted capture with `state=complete` and
  `protocol=anthropic-messages`.

The probe does not require the model to emit a text block. Reasoning-enabled
models can spend a small `max_tokens` budget entirely on `thinking`; that is a
valid Anthropic response and still proves the protocol and capture path.

If the result is 404, 405, 501, 502, or an OpenAI-shaped response, keep the
current GLM configuration:

```bash
export LLM_PROVIDER=glm
export LLM_API_KEY_ENV=GLM_API_KEY
export LLM_API_FORMAT=openai-completions
```

Do not set `LLM_API_FORMAT=anthropic-messages` in that case. A protocol adapter
would be a separate feature requiring explicit request and SSE response
conversion, including tools and usage fields; it is not part of this capture
proxy.

## Anthropic-mode evaluation

If the probe passes, configure the worker before launching a new experiment:

```bash
export LLM_PROVIDER=anthropic
export LLM_API_KEY_ENV=GLM_API_KEY
export LLM_API_FORMAT=anthropic-messages
export LLM_BASE_URL=http://10.17.5.80:31542/v1
export GLM_BASE_URL="$LLM_BASE_URL"
export CAPTURE_PROXY_ENABLED=true
export CAPTURE_PROXY_SCRIPT="$CYBERGYM_REPO_ROOT/capture_proxy/proxy.py"
export CAPTURE_PROXY_PYTHON="$CYBERGYM_PYTHON"
export CAPTURE_PROXY_UPSTREAM_URL=http://10.17.5.80:31542
```

With the proxy enabled, the worker changes `LLM_BASE_URL` to its own proxy
address and keeps the `/v1` suffix. For Anthropic mode the DSH adapter must
then issue `/v1/messages`; the upstream URL remains the base URL without
`/v1`.

After the run, do not infer success from capture count alone. Check:

```bash
"$CYBERGYM_PYTHON" "$CYBERGYM_REPO_ROOT/scripts/analyze_run.py" \
  --run-dir "$RUN_DIR"
```

Healthy task execution still requires `execution.status=completed`, and
verification must be `verified` or another explicitly expected terminal state.
Captures are training-data evidence only; they must not alter whether the
Harness reaches or completes verification.
