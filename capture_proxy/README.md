# Bundled API Capture Proxy

This directory contains the capture proxy used by the DeepSeek Harness and
OpenCode evaluation flows. It is bundled here so a server only needs to clone
the CyberGym repository; the proxy is no longer required to live in a second
repository.

The proxy forwards the original request path to an upstream OpenAI-compatible
or Anthropic-compatible service and writes each request to an isolated capture
directory. OpenAI Chat Completions streams are marked `complete` only after
the `data: [DONE]` event is received. Anthropic streams retain their
`message_stop` completion behavior.

## Install

Use the same Python environment as the harness when possible:

```bash
python -m pip install -r capture_proxy/requirements.txt
```

The launcher accepts `CAPTURE_PROXY_PYTHON` when the environment is located
outside the repository.

## Run

```bash
python capture_proxy/proxy.py \
  --listen-host 0.0.0.0 \
  --listen-port 31545 \
  --upstream-url http://10.17.5.80:31542 \
  --log-dir /path/to/capture_logs \
  --timeout-seconds 300
```

The upstream URL is a base URL. Do not append `/v1`; the proxy keeps the
incoming path such as `/v1/chat/completions`.

Health check:

```bash
curl -fsS http://127.0.0.1:31545/healthz
```

To verify that the upstream really implements Anthropic Messages (rather than
only OpenAI Chat Completions), run the bundled end-to-end probe:

```bash
CAPTURE_PROXY_PYTHON="$CYBERGYM_PYTHON" \
CAPTURE_PROXY_UPSTREAM_URL=http://10.17.5.80:31542 \
LLM_MODEL=glm-5.3-flash \
scripts/test_capture_proxy_anthropic.sh
```

The probe requires HTTP 200 from `/v1/messages`, Anthropic SSE events ending
in `message_stop`, and a persisted `state=complete` capture. It accepts text,
thinking, and tool-use content blocks; a 404/405/501 or
an OpenAI `choices` response means the upstream is not Anthropic-compatible;
do not switch the Harness to `anthropic-messages` in that case.

The raw capture is stored below `capture_logs/raw/completed/<capture_id>`.
`state.json` is `complete` for a successfully terminated stream and `partial`
for a transport error, client disconnect, or missing stream terminator.

The proxy does not join multiple requests. Use the repository's offline
`scripts/export_task_trajectories.py` after a run to aggregate complete
request-level captures into task-level multi-turn JSONL.

The distributed launcher starts one proxy per worker. Its
`CAPTURE_PROXY_PORT` is the base port and the worker's local rank is added to
it; its capture root is the worker output directory. This prevents concurrent
workers from sharing time-windowed capture data.
