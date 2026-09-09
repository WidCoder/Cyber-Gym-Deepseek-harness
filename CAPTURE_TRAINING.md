# API Capture and Training Export

The harnesses can optionally use the external capture proxy at
`/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/hanxueming/cybergym/anthropic_full_capture_proxy`.
The proxy is disabled by default, so the existing Claude flow is unchanged.

When enabled, every API call is stored as one directory containing the raw
`request.json` and `response.json` (plus the raw body and SSE events). The
CyberGym repository then exports the completed calls to multi-turn JSONL.

## Enable capture

Set these variables before starting `start_all_one_node.sh`:

```bash
export CAPTURE_PROXY_ENABLED=true
export CAPTURE_PROXY_PORT=31545
export CAPTURE_PROXY_SCRIPT=/gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/hanxueming/cybergym/anthropic_full_capture_proxy/proxy.py
export CAPTURE_PROXY_PYTHON=/gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/.venv/bin/python
```

For an OpenAI-compatible GLM endpoint, the adapter is routed to:

```text
http://<node-ip>:31545/v1
```

The proxy forwards the original request path to the configured inference
service, so `/v1/chat/completions` remains intact.

## Per-task outputs

After verification, a task directory contains:

```text
result.json       # task metadata and vul/fix exit codes
trajectory.jsonl  # readable harness events
train.jsonl       # one or more multi-turn training samples
capture_manifest.json  # task log <-> capture request/response index
```

`capture_manifest.json` is the traceability record for later data synthesis. It
keeps the task and `agent_id`, the harness log directory, paths to
`args.json`, `timing.json`, `console.log`, `trajectory.jsonl`, and `result.json`,
and one entry per captured API call. Each entry points to the proxy-generated
`request.json`, `response.json`, optional `response.body`, and its `capture_id`.
The manifest stores paths and timing/state metadata only; it does not duplicate
request bodies or API credentials.

`train.jsonl` preserves the request `messages` and `tools`, then appends the
assistant response reconstructed from the captured normal or streaming API
response. HTTP headers are not exported, and API keys are redacted by the
proxy and never copied into training data.

Each training record also includes `metadata.capture_manifest`,
`metadata.task_log_dir`, and `metadata.harness_logs`, so a synthesized sample
can be traced back to the harness logs and its raw request/response pair.

Each JSONL record uses the common OpenAI-style shape:

```json
{
  "id": "arvo-glm-5.3-flash-main-cap_001",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "reasoning_content": "..."}
  ],
  "tools": [],
  "metadata": {
    "dataset": "arvo",
    "model": "glm-5.3-flash",
    "agent_kind": "main"
  }
}
```

`agent_kind` is one of `main`, `subagent`, or `compress`. It can be supplied
explicitly with `--agent-kind`, or through `CAPTURE_AGENT_KIND`. If neither is
provided, the exporter uses capture metadata and then conservative content
inference. The generated `id` combines dataset, model, agent kind, and capture
round, so records from one task remain individually addressable.

Anthropic message blocks and streaming events (`thinking`, `tool_use`, and
`tool_result`) are converted to the same OpenAI-style message representation.

A task can also be exported manually:

```bash
python scripts/export_training_data.py \
  --capture-dir /path/to/capture_logs \
  --output /path/to/train.jsonl \
  --result /path/to/result.json \
  --agent-kind main
```

The exporter accepts OpenAI-compatible Chat Completions and Anthropic
Messages response shapes. Incomplete or unparseable responses are skipped.

When capture is enabled by the distributed launcher, the proxy PID is saved as
`capture_logs/proxy.pid`. A watchdog removes the proxy after all workers in
the round have exited, so the configured port can be reused by the next round.
