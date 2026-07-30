#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
source "$WSL_ENV/bin/activate"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
"$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py --offline >/dev/null
GLMOCR_MODEL_PATH="$(<.runtime/glmocr-model-path)"
GLMOCR_PERFORMANCE_MODE="${GLMOCR_PERFORMANCE_MODE:-throughput}"
GLMOCR_MM_PROCESSOR_CACHE_GB="${GLMOCR_MM_PROCESSOR_CACHE_GB:-1}"
echo "GLM-OCR runtime: revision=ca5d8b3e287e52589e37c28385d9655ee4372f9d context=${GLMOCR_MAX_MODEL_LEN:-32768} gpu_memory=${GLMOCR_GPU_MEMORY_UTILIZATION:-0.85} performance=$GLMOCR_PERFORMANCE_MODE mm_cache_gb=$GLMOCR_MM_PROCESSOR_CACHE_GB"
exec vllm serve "$GLMOCR_MODEL_PATH" \
  --host 127.0.0.1 \
  --port 8080 \
  --served-model-name glm-ocr \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
  --gpu-memory-utilization "${GLMOCR_GPU_MEMORY_UTILIZATION:-0.85}" \
  --performance-mode "$GLMOCR_PERFORMANCE_MODE" \
  --mm-processor-cache-gb "$GLMOCR_MM_PROCESSOR_CACHE_GB" \
  --skip-mm-profiling \
  --max-model-len "${GLMOCR_MAX_MODEL_LEN:-32768}"
