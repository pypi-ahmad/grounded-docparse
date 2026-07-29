#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p .runtime
exec 9>.runtime/setup.lock
flock 9
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
UV_VERSION="0.11.32"
UV_INSTALLER_SHA256="43aff33a967fe40e8c17949d8c85c65bc43f3b5c94742393c957f56ab5ba80f4"

UV_BIN="$(command -v uv || true)"
if [[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
fi
if [[ -z "$UV_BIN" ]]; then
  echo "uv not found inside WSL; installing version $UV_VERSION..."
  UV_INSTALLER="$(mktemp)"
  trap 'rm -f "$UV_INSTALLER"' EXIT
  curl --proto '=https' --tlsv1.2 -LsSf \
    "https://astral.sh/uv/$UV_VERSION/install.sh" \
    -o "$UV_INSTALLER"
  printf '%s  %s\n' "$UV_INSTALLER_SHA256" "$UV_INSTALLER" | sha256sum -c -
  sh "$UV_INSTALLER"
  UV_BIN="$HOME/.local/bin/uv"
fi
if [[ ! -x "$UV_BIN" ]]; then
  echo "ERROR: uv install failed inside WSL." >&2
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
echo "Downloading and pinning GLM-OCR model snapshots..."
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 \
  "$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py
touch "$WSL_ENV/.docparse-local-ocr-ready"
