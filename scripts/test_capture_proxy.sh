#!/usr/bin/env bash
set -euo pipefail

# Run one real OpenAI-compatible request through the bundled proxy and verify
# that the response ended with [DONE] and was persisted as a complete capture.
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
key="${GLM_API_KEY:-${OPENAI_API_KEY:-local-sglang}}"
if [[ -n "${CAPTURE_PROXY_TEST_DIR:-}" ]]; then
  capture_dir="${CAPTURE_PROXY_TEST_DIR}"
else
  capture_dir="$(mktemp -d "${TMPDIR:-/tmp}/cybergym-capture-test.XXXXXX")"
fi
mkdir -p "${capture_dir}"

if [[ ! -f "${repo_dir}/capture_proxy/proxy.py" ]]; then
  echo "ERROR: bundled proxy not found under ${repo_dir}/capture_proxy" >&2
  exit 1
fi

"${proxy_python}" -m py_compile "${repo_dir}/capture_proxy/capture_core.py" "${repo_dir}/capture_proxy/proxy.py"

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
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${port}/healthz" >"${capture_dir}/healthz.json"; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "${ready}" != true ]]; then
  echo "ERROR: proxy did not become ready; log=${capture_dir}/proxy.log" >&2
  exit 1
fi

curl -fsS -N \
  -H "Authorization: Bearer ${key}" \
  -H "Content-Type: application/json" \
  --data "$(printf '{\"model\":\"%s\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly OK\"}],\"stream\":true,\"max_tokens\":32}' "${model}")" \
  "http://127.0.0.1:${port}/v1/chat/completions" \
  >"${capture_dir}/chat-response.body"

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
    if request.get("body_json", {}).get("model") == model:
        matches.append(directory)

if len(matches) != 1:
    raise SystemExit(f"expected one model capture, found {len(matches)}")

directory = matches[0]
state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
response = json.loads((directory / "response.json").read_text(encoding="utf-8"))
body = (directory / "response.body").read_bytes()
assert state.get("state") == "complete", state
assert response.get("status_code") == 200, response
assert response.get("protocol") == "openai-chat-completions", response
assert response.get("stream_complete") is True, response
assert response.get("aggregation_complete") is True, response
assert response.get("transport_error") is None, response
assert response.get("client_disconnected") is False, response
assert b"[DONE]" in body, "OpenAI stream has no [DONE] marker"
print(f"SINGLE_OPENAI_CAPTURE_TEST=PASS capture_id={directory.name}")
PY

echo "capture_dir=${capture_dir}"
