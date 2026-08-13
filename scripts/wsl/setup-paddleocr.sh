#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
PADDLE_ENV="${DOCPARSE_PADDLE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.paddle-venv}"
PADDLE_CACHE_HOME="${PADDLE_PDX_CACHE_HOME:-$HOME/.paddlex}"
PADDLE_PROJECT="$PROJECT_ROOT/paddle-runtime"
cd "$PROJECT_ROOT"
mkdir -p "$RUNTIME_DIR" "$(dirname "$PADDLE_ENV")"
export PADDLE_PDX_CACHE_HOME="$PADDLE_CACHE_HOME"
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
exec 8>"$RUNTIME_DIR/setup-paddle.lock"
flock 8

if [[ ! -f "$PADDLE_PROJECT/pyproject.toml" || ! -f "$PADDLE_PROJECT/uv.lock" ]]; then
  echo "ERROR: Paddle runtime files are missing. Restore the complete application installation." >&2
  exit 1
fi

UV_BIN="$(command -v uv || true)"
[[ -n "$UV_BIN" ]] || UV_BIN="$HOME/.local/bin/uv"
if [[ ! -x "$UV_BIN" ]]; then
  echo "ERROR: uv is unavailable in WSL. Run Setup-GLM-OCR.cmd first." >&2
  exit 1
fi
if [[ ! -x "$PADDLE_ENV/bin/python" ]]; then
  "$UV_BIN" python install 3.12.10
  "$UV_BIN" venv --python 3.12.10 "$PADDLE_ENV"
fi
export UV_PROJECT_ENVIRONMENT="$PADDLE_ENV"
LOCK_HASH="$(sha256sum "$PADDLE_PROJECT/uv.lock" | cut -d' ' -f1)"
LOCK_MARKER="$PADDLE_ENV/.docparse-paddle-lock"
BASE_CONFIG="$RUNTIME_DIR/paddleocr-vl-base.yaml"
TARGET_CONFIG="$RUNTIME_DIR/paddleocr-vl-1.6.yaml"
if [[ -f "$PADDLE_ENV/.docparse-paddle-ready" && \
  -f "$LOCK_MARKER" && "$(<"$LOCK_MARKER")" == "$LOCK_HASH" && \
  -f "$BASE_CONFIG" && -f "$TARGET_CONFIG" ]] && \
  grep -q '^pipeline_name: PaddleOCR-VL-1.6$' "$BASE_CONFIG"; then
  "$PADDLE_ENV/bin/python" -c 'import paddle, paddleocr, paddlex, vllm'
  if "$PADDLE_ENV/bin/python" scripts/wsl/prepare_paddleocr_runtime.py \
    "$BASE_CONFIG" "$TARGET_CONFIG" --offline; then
    echo "Locked PaddleOCR-VL-1.6 environment and assets are already cached."
    exit 0
  fi
  echo "PaddleOCR cache is incomplete; restoring missing assets..."
fi
"$UV_BIN" sync --project "$PADDLE_PROJECT" --locked
"$PADDLE_ENV/bin/python" -c 'import paddle, paddleocr, paddlex, vllm'

if [[ ! -f "$BASE_CONFIG" ]] || \
  ! grep -q '^pipeline_name: PaddleOCR-VL-1.6$' "$BASE_CONFIG"; then
  rm -f -- "$BASE_CONFIG"
  "$PADDLE_ENV/bin/paddlex" --get_pipeline_config PaddleOCR-VL-1.6 --save_path "$BASE_CONFIG"
fi
"$PADDLE_ENV/bin/python" scripts/wsl/prepare_paddleocr_runtime.py \
  "$BASE_CONFIG" "$TARGET_CONFIG" --ensure-assets
printf '%s\n' "$LOCK_HASH" >"$LOCK_MARKER"
touch "$PADDLE_ENV/.docparse-paddle-ready"
