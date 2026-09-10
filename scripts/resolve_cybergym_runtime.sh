#!/usr/bin/env bash

# Resolve a usable CyberGym checkout and Python interpreter on the current
# host. Shared-filesystem paths are configuration hints, not guarantees.
cybergym_resolve_runtime() {
  local candidate python_path module_root
  local requested_source="${CYBERGYM_SOURCE_DIR:-}"
  local requested_repo="${REPO_DIR:-}"
  local launcher_root="${CYBERGYM_REPO_ROOT:-${ROOT_DIR:-}}"
  local runtime_dir=""
  local runtime_python=""
  local -a source_candidates=()
  local -a python_candidates=()

  # Values can be inherited from a different host in a distributed run.
  # Validate each source/interpreter pair together before exporting it.
  source_candidates+=("${CYBERGYM_RUNTIME_DIR:-}" "${requested_source}" "${requested_repo}" "${launcher_root}")

  if [[ -n "${CYBERGYM_RUNTIME_PYTHON:-}" && -x "${CYBERGYM_RUNTIME_PYTHON}" ]]; then
    python_candidates+=("${CYBERGYM_RUNTIME_PYTHON}")
  fi
  if [[ -n "${CYBERGYM_PYTHON:-}" && -x "${CYBERGYM_PYTHON}" ]]; then
    python_candidates+=("${CYBERGYM_PYTHON}")
  fi
  candidate="$(command -v python3 || true)"
  [[ -n "${candidate}" ]] && python_candidates+=("${candidate}")
  candidate="$(command -v python || true)"
  [[ -n "${candidate}" ]] && python_candidates+=("${candidate}")

  for candidate in "${source_candidates[@]}"; do
    [[ -n "${candidate}" && -d "${candidate}/cybergym" ]] || continue
    candidate="$(cd -- "${candidate}" && pwd)"
    # Prefer the virtualenv belonging to this source tree, then test inherited
    # and system interpreters against this exact tree.
    local -a pair_candidates=("${candidate}/.venv/bin/python")
    pair_candidates+=("${python_candidates[@]}")
    for python_path in "${pair_candidates[@]}"; do
      [[ -x "${python_path}" ]] || continue
      if PYTHONPATH="${candidate}:${PYTHONPATH:-}" \
        "${python_path}" - "${candidate}" >/dev/null 2>&1 <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).resolve() / "cybergym"
module = pathlib.Path(__import__("cybergym").__file__).resolve()
try:
    module.relative_to(source)
except ValueError:
    raise SystemExit(1)
PY
      then
        runtime_dir="${candidate}"
        runtime_python="${python_path}"
        break 2
      fi
    done
  done

  # Last resort: use an installed CyberGym package and derive its source root.
  if [[ -z "${runtime_python}" ]]; then
    for python_path in "${python_candidates[@]}"; do
      [[ -x "${python_path}" ]] || continue
      module_root="$(${python_path} -c \
        'import pathlib, cybergym; print(pathlib.Path(cybergym.__file__).resolve().parent.parent)' \
        2>/dev/null || true)"
      if [[ -d "${module_root}/cybergym" ]]; then
        runtime_dir="$(cd -- "${module_root}" && pwd)"
        runtime_python="${python_path}"
        break
      fi
    done
  fi

  if [[ -z "${runtime_python}" ]]; then
    echo "ERROR: no Python interpreter can import cybergym on $(hostname)" >&2
    echo "       CYBERGYM_SOURCE_DIR=${requested_source:-<unset>}" >&2
    echo "       CYBERGYM_PYTHON=${CYBERGYM_PYTHON:-<unset>}" >&2
    return 1
  fi
  if [[ -z "${runtime_dir}" || ! -d "${runtime_dir}/cybergym" ]]; then
    echo "ERROR: resolved Python cannot identify a CyberGym source directory" >&2
    echo "       python=${runtime_python}" >&2
    return 1
  fi

  export CYBERGYM_RUNTIME_DIR="${runtime_dir}"
  export CYBERGYM_RUNTIME_PYTHON="${runtime_python}"
}
