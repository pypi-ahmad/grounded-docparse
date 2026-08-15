#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
PADDLE_ENV="${DOCPARSE_PADDLE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.paddle-venv}"

cd "$PROJECT_ROOT"
[[ -x "$WSL_ENV/bin/python" && -f uv.lock ]]
lock_hash="$(sha256sum uv.lock | cut -d' ' -f1)"
backend=ollama
if nvidia-smi >/dev/null 2>&1; then backend=vllm; fi
[[ -f "$WSL_ENV/.docparse-lock-$backend" && "$(<"$WSL_ENV/.docparse-lock-$backend")" == "$lock_hash" ]]
if [[ "$backend" == vllm ]]; then
  "$WSL_ENV/bin/python" -c 'import docling, glmocr, google.genai, langextract, pdf_inspector, streamlit, torch, transformers, vllm'
else
  "$WSL_ENV/bin/python" -c 'import docling, glmocr, google.genai, langextract, pdf_inspector, streamlit, torch, transformers'
fi
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  "$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py --offline --backend "$backend" >/dev/null

if [[ "$backend" != vllm ]]; then exit 0; fi

[[ -x "$PADDLE_ENV/bin/python" && -f paddle-runtime/uv.lock ]]
paddle_lock_hash="$(sha256sum paddle-runtime/uv.lock | cut -d' ' -f1)"
[[ -f "$PADDLE_ENV/.docparse-paddle-lock" && "$(<"$PADDLE_ENV/.docparse-paddle-lock")" == "$paddle_lock_hash" ]]
[[ -f .runtime/paddleocr-vl-base.yaml && -f .runtime/paddleocr-vl-1.6.yaml ]]
"$PADDLE_ENV/bin/python" -c 'import paddle, paddleocr, paddlex, vllm'
"$PADDLE_ENV/bin/python" scripts/wsl/prepare_paddleocr_runtime.py \
  .runtime/paddleocr-vl-base.yaml .runtime/paddleocr-vl-1.6.yaml --offline >/dev/null
