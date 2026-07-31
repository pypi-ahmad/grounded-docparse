#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
mkdir -p .runtime
exec 9>.runtime/setup.lock
flock 9
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
APP_DATA_DIR="${DOCPARSE_WSL_DATA:-$HOME/.local/share/grounded-docparse}"
BACKEND="${DOCPARSE_LOCAL_OCR_BACKEND:-}"
if [[ -z "$BACKEND" ]]; then
  if nvidia-smi >/dev/null 2>&1; then
    BACKEND="vllm"
  else
    BACKEND="ollama"
  fi
fi
if [[ "$BACKEND" != "vllm" && "$BACKEND" != "ollama" ]]; then
  echo "ERROR: DOCPARSE_LOCAL_OCR_BACKEND must be vllm or ollama." >&2
  exit 1
fi
export HF_HOME="${HF_HOME:-$APP_DATA_DIR/huggingface}"
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
LOCK_HASH="$(sha256sum uv.lock | cut -d' ' -f1)"
LOCK_MARKER="$WSL_ENV/.docparse-lock-$BACKEND"
if [[ -f "$WSL_ENV/.docparse-local-ocr-ready-$BACKEND" && \
  -f "$LOCK_MARKER" && "$(<"$LOCK_MARKER")" == "$LOCK_HASH" ]]; then
  if [[ "$BACKEND" == "vllm" ]]; then
    "$WSL_ENV/bin/python" -c 'import glmocr, torch, transformers, vllm'
  else
    "$WSL_ENV/bin/python" -c 'import glmocr, torch, transformers'
    bash scripts/wsl/setup-ollama.sh
  fi
  if HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    "$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py \
      --offline --backend "$BACKEND" >/dev/null; then
    echo "Locked $BACKEND environment is already installed."
    exit 0
  fi
fi
if [[ "$BACKEND" == "vllm" ]]; then
  "$UV_BIN" sync --locked --extra local-ocr
  "$WSL_ENV/bin/python" -c 'import glmocr, torch, transformers, vllm'
else
  "$UV_BIN" sync --locked --extra local-ocr-cpu
  "$WSL_ENV/bin/python" -c 'import glmocr, torch, transformers'
  bash scripts/wsl/setup-ollama.sh
fi
echo "Downloading and pinning GLM-OCR model snapshots..."
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 \
  "$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py --backend "$BACKEND"
printf '%s\n' "$BACKEND" >"$WSL_ENV/.docparse-local-ocr-backend"
printf '%s\n' "$LOCK_HASH" >"$LOCK_MARKER"
touch "$WSL_ENV/.docparse-local-ocr-ready-$BACKEND"
