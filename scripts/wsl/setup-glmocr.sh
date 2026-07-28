#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p .runtime
exec 9>.runtime/setup.lock
flock 9
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"

UV_BIN="$(command -v uv || true)"
if [[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
fi
if [[ -z "$UV_BIN" ]]; then
  echo "ERROR: uv is not installed inside WSL." >&2
  exit 1
fi

"$UV_BIN" python install 3.12.10
if [[ ! -x "$WSL_ENV/bin/python" ]]; then
  mkdir -p "$(dirname "$WSL_ENV")"
  "$UV_BIN" venv --python 3.12.10 "$WSL_ENV"
fi
source "$WSL_ENV/bin/activate"
export UV_PROJECT_ENVIRONMENT="$WSL_ENV"
"$UV_BIN" sync --locked --extra local-ocr
"$WSL_ENV/bin/python" -c 'import glmocr, torch, transformers, vllm'
touch "$WSL_ENV/.docparse-local-ocr-ready"
