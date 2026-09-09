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

The raw capture is stored below `capture_logs/raw/completed/<capture_id>`.
`state.json` is `complete` for a successfully terminated stream and `partial`
for a transport error, client disconnect, or missing stream terminator.
