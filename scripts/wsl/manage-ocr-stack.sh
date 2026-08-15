#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
PADDLE_ENV="${DOCPARSE_PADDLE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.paddle-venv}"
APP_DATA_DIR="${DOCPARSE_WSL_DATA:-$HOME/.local/share/grounded-docparse}"
ACTIVE_FILE="$RUNTIME_DIR/active-ocr-engine"
PADDLE_VLLM_PORT="${DOCPARSE_PADDLE_VLLM_PORT:-8118}"
PADDLE_API_PORT="${DOCPARSE_PADDLE_API_PORT:-8119}"
PADDLE_CACHE_HOME="${PADDLE_PDX_CACHE_HOME:-$HOME/.paddlex}"
PADDLE_MODEL_DIR="$PADDLE_CACHE_HOME/official_models/PaddleOCR-VL-1.6"
PADDLE_FONT_FILE="$PADDLE_CACHE_HOME/fonts/PingFang-SC-Regular.ttf"

mkdir -p "$RUNTIME_DIR"
cd "$PROJECT_ROOT"
exec 9>"$RUNTIME_DIR/ocr-services.lock"
flock 9

action="${1:-ensure}"
engine="${2:-${DOCPARSE_START_ENGINE:-glm-ocr}}"
if [[ "$action" != "ensure" && "$action" != "stop" ]]; then
  echo "ERROR: Usage: manage-ocr-stack.sh ensure {glm-ocr|paddleocr-vl-1.6} | stop all" >&2
  exit 2
fi
if [[ "$action" == "ensure" && "$engine" != "glm-ocr" && "$engine" != "paddleocr-vl-1.6" ]]; then
  echo "ERROR: Unsupported OCR engine: $engine" >&2
  exit 2
fi
if [[ "$action" == "stop" && "$engine" != "all" ]]; then
  echo "ERROR: Usage: manage-ocr-stack.sh stop all" >&2
  exit 2
fi
for port in "$PADDLE_VLLM_PORT" "$PADDLE_API_PORT"; do
  if [[ ! "$port" =~ ^[0-9]+$ || "$port" -lt 1 || "$port" -gt 65535 ]]; then
    echo "ERROR: PaddleOCR ports must be integers between 1 and 65535." >&2
    exit 2
  fi
done
if [[ "$PADDLE_VLLM_PORT" == "$PADDLE_API_PORT" ]]; then
  echo "ERROR: PaddleOCR vLLM and API ports must be different." >&2
  exit 2
fi

process_is_running() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
  [[ "$(awk '{print $3}' "/proc/$pid/stat")" != "Z" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

pid_matches() {
  local pid_file="$1" expected="$2" pid
  [[ -f "$pid_file" ]] || return 1
  pid="$(<"$pid_file")"
  process_is_running "$pid" || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" | grep -Fq "$expected"
}

port_is_listening() { ss -ltnH "sport = :$1" | grep -q .; }

wait_for_url() {
  local url="$1" attempts="$2" log_file="$3"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    curl --fail --silent "$url" >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "ERROR: Timed out waiting for $url" >&2
  tail -n 50 "$log_file" >&2 || true
  return 1
}

stop_managed() {
  local pid_file="$1" expected="$2" label="$3" pid
  [[ -f "$pid_file" ]] || return 0
  if ! pid_matches "$pid_file" "$expected"; then
    pid="$(<"$pid_file")"
    if process_is_running "$pid"; then
      echo "ERROR: Refusing to stop $label: PID $pid is not the managed command." >&2
      return 1
    fi
    rm -f "$pid_file"
    return 0
  fi
  pid="$(<"$pid_file")"
  kill "$pid"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    process_is_running "$pid" || { rm -f "$pid_file"; return 0; }
    sleep 1
  done
  echo "ERROR: Managed $label process $pid did not stop within 30 seconds." >&2
  return 1
}

glm_environment_current() {
  local backend="$1" lock_marker lock_hash
  lock_marker="$WSL_ENV/.docparse-lock-$backend"
  [[ -x "$WSL_ENV/bin/python" && \
    -f "$WSL_ENV/.docparse-local-ocr-ready-$backend" && \
    -f "$lock_marker" && -f "$PROJECT_ROOT/uv.lock" ]] || return 1
  lock_hash="$(sha256sum "$PROJECT_ROOT/uv.lock" | cut -d' ' -f1)"
  [[ "$(<"$lock_marker")" == "$lock_hash" ]]
}

stop_glm() {
  stop_managed "$RUNTIME_DIR/vllm.pid" "vllm serve" "GLM vLLM"
  for port in 8080; do
    if port_is_listening "$port"; then
      echo "ERROR: Port $port remains occupied by an unmanaged process." >&2
      return 1
    fi
  done
}

stop_paddle() {
  stop_managed "$RUNTIME_DIR/paddle-api.pid" "paddlex --serve" "PaddleX API"
  stop_managed "$RUNTIME_DIR/paddle-vllm.pid" "paddleocr genai_server" "Paddle vLLM"
  for port in "$PADDLE_VLLM_PORT" "$PADDLE_API_PORT"; do
    if port_is_listening "$port"; then
      echo "ERROR: Port $port remains occupied by an unmanaged process." >&2
      return 1
    fi
  done
}

ensure_glm() {
  local backend=vllm port=8080 log="$RUNTIME_DIR/vllm.log"
  local pid_file="$RUNTIME_DIR/vllm.pid" command="vllm serve"
  local ready_url="http://127.0.0.1:8080/v1/models"
  if ! nvidia-smi >/dev/null 2>&1; then
    echo "ERROR: GLM-OCR vLLM requires a supported NVIDIA GPU; select Local Ollama explicitly for CPU/local inference." >&2
    return 1
  fi
  stop_paddle || return 1
  if ! glm_environment_current "$backend"; then
    stop_glm || return 1
    echo "Installing locked $backend GLM-OCR environment..."
    DOCPARSE_LOCAL_OCR_BACKEND="$backend" bash scripts/wsl/setup-glmocr.sh || return 1
  fi
  export DOCPARSE_LOCAL_OCR_BACKEND="$backend"
  export HF_HOME="${HF_HOME:-$APP_DATA_DIR/huggingface}"
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  "$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py --offline --backend "$backend" >/dev/null || return 1
  if curl --fail --silent "$ready_url" | grep -q 'glm-ocr'; then
    "$WSL_ENV/bin/python" scripts/wsl/check-glmocr-api.py || return 1
    printf '%s\n' "glm-ocr" >"$ACTIVE_FILE"
    return 0
  fi
  if pid_matches "$pid_file" "$command"; then
    stop_managed "$pid_file" "$command" "$backend" || return 1
  elif port_is_listening "$port"; then
    echo "ERROR: Port $port is occupied by an unmanaged process." >&2
    return 1
  fi
  echo "Starting GLM-OCR with vLLM..."
  nohup bash scripts/wsl/serve-glmocr.sh 9>&- >"$log" 2>&1 &
  echo "$!" >"$pid_file"
  wait_for_url "$ready_url" 450 "$log" || return 1
  "$WSL_ENV/bin/python" scripts/wsl/check-glmocr-api.py || return 1
  printf '%s\n' "glm-ocr" >"$ACTIVE_FILE"
}

ensure_paddle() {
  local compute_cap cuda_version memory_mib
  if ! nvidia-smi >/dev/null 2>&1; then
    echo "ERROR: PaddleOCR-VL-1.6 requires the NVIDIA vLLM backend in this launcher." >&2
    return 1
  fi
  compute_cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -n 1 | tr -d ' ')"
  memory_mib="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n 1 | tr -d ' ')"
  cuda_version="$(nvidia-smi | sed -nE 's/.*CUDA (UMD )?Version: *([0-9.]+).*/\2/p' | head -n 1)"
  if [[ ! "$compute_cap" =~ ^[0-9]+\.[0-9]+$ || "${compute_cap%%.*}" -lt 8 ]]; then
    echo "ERROR: PaddleOCR vLLM requires NVIDIA compute capability 8.0 or newer." >&2
    return 1
  fi
  if [[ -z "$cuda_version" || "$(printf '%s\n' 12.6 "$cuda_version" | sort -V | head -n 1)" != "12.6" ]]; then
    echo "ERROR: PaddleOCR vLLM requires CUDA 12.6 or newer; driver reports ${cuda_version:-unknown}." >&2
    return 1
  fi
  if [[ ! "$memory_mib" =~ ^[0-9]+$ || "$memory_mib" -lt 7000 ]]; then
    echo "ERROR: PaddleOCR-VL-1.6 requires at least 7 GB total GPU memory." >&2
    return 1
  fi
  export PADDLE_PDX_CACHE_HOME="$PADDLE_CACHE_HOME"
  export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
  export HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0
  stop_glm || return 1
  if ! glm_environment_current vllm; then
    echo "Installing the main application and GLM-OCR environment..."
    DOCPARSE_LOCAL_OCR_BACKEND=vllm bash scripts/wsl/setup-glmocr.sh || return 1
  fi
  echo "Checking isolated PaddleOCR-VL-1.6 environment..."
  bash scripts/wsl/setup-paddleocr.sh || return 1
  export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  export PADDLE_PDX_LOCAL_FONT_FILE_PATH="$PADDLE_FONT_FILE"
  if ! curl --fail --silent "http://127.0.0.1:$PADDLE_VLLM_PORT/v1/models" | grep -q 'PaddleOCR-VL-1.6'; then
    if pid_matches "$RUNTIME_DIR/paddle-vllm.pid" "paddleocr genai_server"; then
      stop_managed "$RUNTIME_DIR/paddle-vllm.pid" "paddleocr genai_server" "Paddle vLLM" || return 1
    elif port_is_listening "$PADDLE_VLLM_PORT"; then
      echo "ERROR: Port $PADDLE_VLLM_PORT is occupied by an unmanaged process." >&2
      return 1
    fi
    echo "Starting PaddleOCR-VL-1.6 vLLM service..."
    nohup "$PADDLE_ENV/bin/paddleocr" genai_server \
      --model_name PaddleOCR-VL-1.6-0.9B \
      --model_dir "$PADDLE_MODEL_DIR" \
      --backend vllm \
      --host 127.0.0.1 \
      --port "$PADDLE_VLLM_PORT" \
      --backend_config "$PROJECT_ROOT/config/paddle-vllm.yaml" \
      9>&- \
      >"$RUNTIME_DIR/paddle-vllm.log" 2>&1 &
    echo "$!" >"$RUNTIME_DIR/paddle-vllm.pid"
    wait_for_url "http://127.0.0.1:$PADDLE_VLLM_PORT/health" 450 "$RUNTIME_DIR/paddle-vllm.log" || return 1
    curl --fail --silent "http://127.0.0.1:$PADDLE_VLLM_PORT/v1/models" | grep -q 'PaddleOCR-VL-1.6' || return 1
  fi
  if ! curl --fail --silent "http://127.0.0.1:$PADDLE_API_PORT/openapi.json" | grep -q '/layout-parsing'; then
    if pid_matches "$RUNTIME_DIR/paddle-api.pid" "paddlex --serve"; then
      stop_managed "$RUNTIME_DIR/paddle-api.pid" "paddlex --serve" "PaddleX API" || return 1
    elif port_is_listening "$PADDLE_API_PORT"; then
      echo "ERROR: Port $PADDLE_API_PORT is occupied by an unmanaged process." >&2
      return 1
    fi
    echo "Starting PaddleOCR-VL-1.6 full document parser..."
    nohup "$PADDLE_ENV/bin/paddlex" --serve \
      --pipeline "$RUNTIME_DIR/paddleocr-vl-1.6.yaml" \
      --device cpu --host 127.0.0.1 --port "$PADDLE_API_PORT" \
      9>&- \
      >"$RUNTIME_DIR/paddle-api.log" 2>&1 &
    echo "$!" >"$RUNTIME_DIR/paddle-api.pid"
    wait_for_url "http://127.0.0.1:$PADDLE_API_PORT/openapi.json" 300 "$RUNTIME_DIR/paddle-api.log" || return 1
  fi
  DOCPARSE_PADDLEOCR_SERVICE_URL="http://127.0.0.1:$PADDLE_API_PORT" \
    "$PADDLE_ENV/bin/python" scripts/wsl/check-paddleocr-api.py || return 1
  printf '%s\n' "paddleocr-vl-1.6" >"$ACTIVE_FILE"
}

if [[ "$action" == "stop" ]]; then
  status=0
  stop_glm || status=1
  stop_paddle || status=1
  rm -f "$ACTIVE_FILE"
  if [[ "$status" -eq 0 ]]; then
    echo "All managed OCR services stopped."
  fi
  exit "$status"
fi

previous=""
[[ -f "$ACTIVE_FILE" ]] && previous="$(<"$ACTIVE_FILE")"
if [[ -z "$previous" ]] && \
  curl --fail --silent http://127.0.0.1:8080/v1/models 2>/dev/null | grep -q 'glm-ocr'; then
  previous="glm-ocr"
elif [[ -z "$previous" ]] && \
  curl --fail --silent "http://127.0.0.1:$PADDLE_VLLM_PORT/v1/models" 2>/dev/null | grep -q 'PaddleOCR-VL-1.6'; then
  previous="paddleocr-vl-1.6"
fi
if [[ "$engine" == "glm-ocr" ]]; then
  ensure_target=ensure_glm
else
  ensure_target=ensure_paddle
fi
if "$ensure_target"; then
  echo "$engine OCR is ready."
  exit 0
fi

echo "ERROR: Failed to start $engine; cleaning partial services." >&2
if [[ "$engine" == "glm-ocr" ]]; then stop_glm || true; else stop_paddle || true; fi
if [[ -n "$previous" && "$previous" != "$engine" ]]; then
  echo "Restoring previous OCR engine: $previous" >&2
  if [[ "$previous" == "glm-ocr" ]]; then ensure_glm || true; else ensure_paddle || true; fi
fi
exit 1
