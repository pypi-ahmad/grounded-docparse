#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
source "$WSL_ENV/bin/activate"
export DOCPARSE_LOCAL_OCR_ENABLED=true
export DOCPARSE_GLMOCR_CONFIG_PATH=config/glmocr.yaml
export DOCPARSE_GLMOCR_LAYOUT_DEVICE=cuda:0
export DOCPARSE_PRELOAD_LOCAL_OCR="${DOCPARSE_PRELOAD_LOCAL_OCR:-true}"
exec streamlit run streamlit_app.py "$@"
