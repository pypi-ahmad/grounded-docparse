#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
source "$WSL_ENV/bin/activate"
exec vllm serve zai-org/GLM-OCR \
  --port 8080 \
  --served-model-name glm-ocr \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
  --gpu-memory-utilization "${GLMOCR_GPU_MEMORY_UTILIZATION:-0.75}" \
  --max-model-len "${GLMOCR_MAX_MODEL_LEN:-8192}"
