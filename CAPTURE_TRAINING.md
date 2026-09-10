# API Capture and Training Export

The capture proxy is bundled under `capture_proxy/` in this repository. The
proxy is disabled by default, so the existing Claude flow is unchanged.

Set `CYBERGYM_REPO_ROOT` to the clone directory before using the commands
below.

When enabled, every API call is stored as one directory containing the raw
`request.json` and `response.json` (plus the raw body and SSE events). The
CyberGym repository then exports the completed calls to multi-turn JSONL.

## Enable capture

Set these variables before starting `start_all_one_node.sh`:

```bash
export CAPTURE_PROXY_ENABLED=true
export CAPTURE_PROXY_PORT=31545
export CAPTURE_PROXY_SCRIPT="$CYBERGYM_REPO_ROOT/capture_proxy/proxy.py"
export CAPTURE_PROXY_PYTHON="${CYBERGYM_PYTHON:-$CYBERGYM_REPO_ROOT/.venv/bin/python}"
"${CYBERGYM_PYTHON:-python}" -m pip install -r "$CYBERGYM_REPO_ROOT/capture_proxy/requirements.txt"
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

The worker-level `train.jsonl` preserves one request's `messages` and `tools`,
then appends the assistant response reconstructed from the captured normal or
streaming API response. HTTP headers are not exported, and API keys are
redacted by the proxy and never copied into training data.

For one complete multi-turn sample per task, run the offline finalization step
after the round has ended:

```bash
python scripts/export_task_trajectories.py \
  --run-dir /path/to/output/glm-5.3-flash/<experiment>/round1 \
  --output /path/to/output/glm-5.3-flash/<experiment>/round1/task_trajectories.jsonl
```

This command uses each task's `capture_manifest.json` as the task boundary.
It requires every referenced capture to have `state=complete`, a 2xx response,
and no transport error. Consecutive requests are joined only when the next
request contains the previous normalized conversation as an exact prefix; a
real context reset starts a new segment instead of silently inventing history.
The adjacent `.report.json` records skipped tasks and shared capture IDs.

For data produced by the pre-`95bd83b` proxy, add
`--recover-terminal-sse` once. It only recovers legacy `state=partial` captures
whose clean 2xx raw body contains `data: [DONE]`; it does not recover 502s,
transport errors, or streams without a terminal marker.

The proxy and Harness remain online-transparent: capture and aggregation happen
after each task, so a failed export cannot change whether the Harness reaches
verification. Do not use `--allow-shared-captures` for a strict dataset unless
the report has been manually reviewed.

Use `scripts/analyze_run.py` to inspect a completed round. It reports result,
verification, proxy status codes, capture states, `[DONE]` markers, and
available trajectory/training files without printing request bodies or keys.

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

When capture is enabled by the distributed launcher, each worker owns an
independent proxy and capture root: `<worker-output>/capture_logs`, with port
`CAPTURE_PROXY_PORT + local_rank`. The worker removes its proxy on exit, so the
port can be reused by the next round. This per-worker ownership is required for
reliable task association when several workers run concurrently.
