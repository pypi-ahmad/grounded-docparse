#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
source "$WSL_ENV/bin/activate"
APP_DATA_DIR="${DOCPARSE_WSL_DATA:-$HOME/.local/share/grounded-docparse}"
BACKEND="${DOCPARSE_LOCAL_OCR_BACKEND:-$(<"$WSL_ENV/.docparse-local-ocr-backend")}"
export HF_HOME="${HF_HOME:-$APP_DATA_DIR/huggingface}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
"$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py --offline --backend "$BACKEND" >/dev/null
export DOCPARSE_LOCAL_OCR_ENABLED=true
export DOCPARSE_LOCAL_OCR_BACKEND="$BACKEND"
export DOCPARSE_GLMOCR_CONFIG_PATH="$PROJECT_ROOT/.runtime/glmocr.yaml"
if [[ "$BACKEND" == "ollama" ]]; then
  export DOCPARSE_GLMOCR_LAYOUT_DEVICE="cpu"
else
  export DOCPARSE_GLMOCR_LAYOUT_DEVICE="${DOCPARSE_GLMOCR_LAYOUT_DEVICE:-cuda:0}"
fi
export DOCPARSE_PRELOAD_LOCAL_OCR="${DOCPARSE_PRELOAD_LOCAL_OCR:-true}"
echo "PP-DocLayoutV3 runtime: revision=97d101e6db2642e162a1d05392d1b0231c91033e device=$DOCPARSE_GLMOCR_LAYOUT_DEVICE workers=${GLMOCR_SDK_MAX_WORKERS:-16}"
exec streamlit run streamlit_app.py "$@" --server.address=127.0.0.1
