#!/usr/bin/env bash
set -euo pipefail

# Probe a real Anthropic Messages upstream through the bundled capture proxy.
# This test intentionally fails when the upstream only supports OpenAI chat.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "${script_dir}/.." && pwd)

proxy_python="${CAPTURE_PROXY_PYTHON:-}"
if [[ -z "${proxy_python}" ]]; then
  if [[ -x "${repo_dir}/.venv/bin/python" ]]; then
    proxy_python="${repo_dir}/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    proxy_python=$(command -v python3)
  else
    proxy_python=$(command -v python)
  fi
fi
if [[ -z "${proxy_python}" || ! -x "${proxy_python}" ]]; then
  echo "ERROR: no executable Python found; set CAPTURE_PROXY_PYTHON" >&2
  exit 1
fi

upstream_url="${CAPTURE_PROXY_UPSTREAM_URL:-http://10.17.5.80:31542}"
model="${LLM_MODEL:-glm-5.3-flash}"
port="${CAPTURE_PROXY_TEST_PORT:-31547}"
key="${GLM_API_KEY:-${ANTHROPIC_API_KEY:-local-sglang}}"
max_tokens="${ANTHROPIC_TEST_MAX_TOKENS:-128}"
if [[ ! "${max_tokens}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: ANTHROPIC_TEST_MAX_TOKENS must be a positive integer" >&2
  exit 1
fi
if [[ -n "${CAPTURE_PROXY_TEST_DIR:-}" ]]; then
  capture_dir="${CAPTURE_PROXY_TEST_DIR}"
else
  capture_dir="$(mktemp -d "${TMPDIR:-/tmp}/cybergym-anthropic-capture-test.XXXXXX")"
fi
mkdir -p "${capture_dir}"

if [[ ! -f "${repo_dir}/capture_proxy/proxy.py" ]]; then
  echo "ERROR: bundled proxy not found under ${repo_dir}/capture_proxy" >&2
  exit 1
fi

"${proxy_python}" -m py_compile "${repo_dir}/capture_proxy/capture_core.py" "${repo_dir}/capture_proxy/proxy.py"
if ! "${proxy_python}" -c 'import fastapi, httpx, uvicorn' >/dev/null 2>&1; then
  echo "ERROR: ${proxy_python} is missing proxy dependencies; install capture_proxy/requirements.txt" >&2
  exit 1
fi

"${proxy_python}" "${repo_dir}/capture_proxy/proxy.py" \
  --listen-host 127.0.0.1 \
  --listen-port "${port}" \
  --upstream-url "${upstream_url}" \
  --log-dir "${capture_dir}" \
  --timeout-seconds "${CAPTURE_PROXY_TIMEOUT:-300}" \
  >"${capture_dir}/proxy.log" 2>&1 &
proxy_pid=$!
cleanup() {
  kill "${proxy_pid}" 2>/dev/null || true
  wait "${proxy_pid}" 2>/dev/null || true
}
trap cleanup EXIT

ready=false
for _ in $(seq 1 "${CAPTURE_PROXY_STARTUP_TIMEOUT:-30}"); do
  if ! kill -0 "${proxy_pid}" 2>/dev/null; then
    echo "ERROR: proxy exited during startup" >&2
    cat "${capture_dir}/proxy.log" >&2 || true
    exit 1
  fi
  if curl -fsS --max-time 2 "http://127.0.0.1:${port}/healthz" \
      >"${capture_dir}/healthz.json" 2>/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "${ready}" != true ]]; then
  echo "ERROR: proxy did not become ready; log=${capture_dir}/proxy.log" >&2
  cat "${capture_dir}/proxy.log" >&2 || true
  exit 1
fi

request_body="${capture_dir}/request.json"
response_body="${capture_dir}/messages-response.body"
response_headers="${capture_dir}/messages-response.headers"
printf '%s\n' "{\"model\":\"${model}\",\"max_tokens\":${max_tokens},\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"Return exactly OK in the final answer.\"}]}],\"stream\":true}" >"${request_body}"

set +e
http_code=$(curl -sS -N --max-time "${CAPTURE_PROXY_REQUEST_TIMEOUT:-60}" \
  -D "${response_headers}" \
  -H "Authorization: Bearer ${key}" \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  --data-binary "@${request_body}" \
  -o "${response_body}" \
  -w '%{http_code}' \
  "http://127.0.0.1:${port}/v1/messages")
curl_rc=$?
set -e
if [[ "${curl_rc}" -ne 0 ]]; then
  echo "ERROR: Anthropic request failed curl_rc=${curl_rc}; capture_dir=${capture_dir}" >&2
  cat "${capture_dir}/proxy.log" >&2 || true
  exit 1
fi
if [[ "${http_code}" != 2* ]]; then
  echo "ERROR: upstream/proxy did not accept Anthropic Messages: HTTP ${http_code}" >&2
  cat "${response_body}" >&2 || true
  echo "capture_dir=${capture_dir}" >&2
  exit 1
fi

"${proxy_python}" - "${capture_dir}" "${model}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]) / "raw" / "completed"
model = sys.argv[2]
matches = []
for directory in sorted(root.iterdir() if root.is_dir() else []):
    if not directory.is_dir():
        continue
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    body = request.get("body_json")
    if isinstance(body, dict) and body.get("model") == model and request.get("path") == "/v1/messages":
        matches.append(directory)

if len(matches) != 1:
    raise SystemExit(f"expected one Anthropic capture, found {len(matches)}")

directory = matches[0]
state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
response = json.loads((directory / "response.json").read_text(encoding="utf-8"))
body = (directory / "response.body").read_bytes()
assert state.get("state") == "complete", state
assert response.get("status_code") == 200, response
assert response.get("protocol") == "anthropic-messages", response
assert response.get("aggregation_complete") is True, response
assert response.get("message_id"), response
assert b'"type":"message_stop"' in body or b'"type": "message_stop"' in body, "Anthropic stream has no message_stop"
message = response.get("message") or {}
content = message.get("content") or []
assert message.get("role") == "assistant", response
assert isinstance(content, list), response
block_types = [
    block.get("type")
    for block in content
    if isinstance(block, dict) and isinstance(block.get("type"), str)
]
print(f"SINGLE_ANTHROPIC_CAPTURE_TEST=PASS capture_id={directory.name} message_id={response['message_id']}")
print(f"anthropic_block_types={block_types} stop_reason={message.get('stop_reason')}")
PY

echo "capture_dir=${capture_dir}"
