#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
STREAMLIT_LOG="$RUNTIME_DIR/streamlit.log"
STREAMLIT_PID_FILE="$RUNTIME_DIR/streamlit.pid"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"
APP_DATA_DIR="${DOCPARSE_WSL_DATA:-$HOME/.local/share/grounded-docparse}"

mkdir -p "$RUNTIME_DIR"
cd "$PROJECT_ROOT"

BACKEND="${DOCPARSE_LOCAL_OCR_BACKEND:-}"
if [[ -z "$BACKEND" && -f "$WSL_ENV/.docparse-local-ocr-backend" ]]; then
  BACKEND="$(<"$WSL_ENV/.docparse-local-ocr-backend")"
fi
if [[ -z "$BACKEND" ]]; then
  if nvidia-smi >/dev/null 2>&1; then BACKEND="vllm"; else BACKEND="ollama"; fi
fi
if [[ "$BACKEND" != "vllm" && "$BACKEND" != "ollama" ]]; then
  echo "ERROR: Invalid OCR backend: $BACKEND" >&2
  exit 1
fi

if ! [[ -x "$WSL_ENV/bin/python" && -f "$WSL_ENV/.docparse-local-ocr-ready-$BACKEND" ]]; then
  echo "Installing locked $BACKEND OCR environment..."
  DOCPARSE_LOCAL_OCR_BACKEND="$BACKEND" bash scripts/wsl/setup-glmocr.sh
fi

export DOCPARSE_LOCAL_OCR_BACKEND="$BACKEND"
export HF_HOME="${HF_HOME:-$APP_DATA_DIR/huggingface}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
"$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py --offline --backend "$BACKEND" >/dev/null
GLMOCR_MODEL_PATH="$(<"$RUNTIME_DIR/glmocr-model-path")"
GLMOCR_RUNTIME_CONFIG="$RUNTIME_DIR/glmocr.yaml"
export DOCPARSE_GLMOCR_CONFIG_PATH="$GLMOCR_RUNTIME_CONFIG"

if [[ "$BACKEND" == "vllm" ]]; then
  OCR_PORT=8080
  OCR_LOG="$RUNTIME_DIR/vllm.log"
  OCR_PID_FILE="$RUNTIME_DIR/vllm.pid"
  OCR_COMMAND="vllm serve"
  OCR_READY_URL="http://127.0.0.1:8080/v1/models"
else
  OCR_PORT=11434
  OCR_LOG="$RUNTIME_DIR/ollama.log"
  OCR_PID_FILE="$RUNTIME_DIR/ollama.pid"
  OCR_COMMAND="ollama serve"
  OCR_READY_URL="http://127.0.0.1:11434/api/tags"
fi

pid_matches() {
  local pid_file="$1" expected="$2" pid
  [[ -f "$pid_file" ]] || return 1
  pid="$(<"$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
  [[ "$(awk '{print $3}' "/proc/$pid/stat")" != "Z" ]] || return 1
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
  tail -n 40 "$log_file" >&2 || true
  return 1
}

ocr_model_is_ready() {
  if [[ "$BACKEND" == "vllm" ]]; then
    curl --fail --silent "$OCR_READY_URL" | grep -q 'glm-ocr'
  else
    curl --fail --silent "$OCR_READY_URL" | grep -q 'glm-ocr:bf16'
  fi
}

ocr_inference_is_ready() { "$WSL_ENV/bin/python" scripts/wsl/check-glmocr-api.py; }

stop_managed() {
  local pid_file="$1" label="$2" pid
  pid="$(<"$pid_file")"
  kill "$pid"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    kill -0 "$pid" 2>/dev/null || { rm -f "$pid_file"; return 0; }
    sleep 1
  done
  echo "ERROR: Managed $label process $pid did not stop within 30 seconds." >&2
  return 1
}

start_ocr() {
  echo "Starting GLM-OCR with $BACKEND..."
  if [[ "$BACKEND" == "vllm" ]]; then
    nohup bash scripts/wsl/serve-glmocr.sh >"$OCR_LOG" 2>&1 &
  else
    nohup bash scripts/wsl/serve-ollama.sh >"$OCR_LOG" 2>&1 &
  fi
  echo "$!" >"$OCR_PID_FILE"
  wait_for_url "$OCR_READY_URL" 450 "$OCR_LOG"
  ocr_model_is_ready || { echo "ERROR: $BACKEND does not expose GLM-OCR." >&2; return 1; }
  ocr_inference_is_ready
}

if ocr_model_is_ready; then
  if ocr_inference_is_ready; then
    echo "$BACKEND OCR is already ready."
  elif pid_matches "$OCR_PID_FILE" "$OCR_COMMAND"; then
    stop_managed "$OCR_PID_FILE" "$BACKEND"
    start_ocr
  else
    echo "ERROR: Unmanaged $BACKEND server failed inference validation." >&2
    exit 1
  fi
elif pid_matches "$OCR_PID_FILE" "$OCR_COMMAND"; then
  wait_for_url "$OCR_READY_URL" 450 "$OCR_LOG"
  ocr_model_is_ready && ocr_inference_is_ready || {
    stop_managed "$OCR_PID_FILE" "$BACKEND"
    start_ocr
  }
elif port_is_listening "$OCR_PORT"; then
  echo "ERROR: Port $OCR_PORT is occupied by an unmanaged process." >&2
  exit 1
else
  start_ocr
fi
echo "$BACKEND OCR is ready."

streamlit_environment_matches() {
  [[ -f "$STREAMLIT_PID_FILE" ]] || return 1
  local pid current_key="" current_base_url="" current_config="" current_backend="" entry
  pid="$(<"$STREAMLIT_PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/environ" ]] || return 1
  while IFS= read -r -d '' entry; do
    case "$entry" in
      OPENAI_API_KEY=*) current_key="${entry#*=}" ;;
      OPENAI_BASE_URL=*) current_base_url="${entry#*=}" ;;
      DOCPARSE_GLMOCR_CONFIG_PATH=*) current_config="${entry#*=}" ;;
      DOCPARSE_LOCAL_OCR_BACKEND=*) current_backend="${entry#*=}" ;;
    esac
  done <"/proc/$pid/environ"
  [[ "$current_key" == "${OPENAI_API_KEY-}" && \
    "$current_base_url" == "${OPENAI_BASE_URL-}" && \
    "$current_config" == "$GLMOCR_RUNTIME_CONFIG" && \
    "$current_backend" == "$BACKEND" ]]
}

start_streamlit() {
  echo "Starting Streamlit..."
  DOCPARSE_PRELOAD_LOCAL_OCR=true nohup bash scripts/wsl/run-app.sh \
    --server.headless true >"$STREAMLIT_LOG" 2>&1 &
  echo "$!" >"$STREAMLIT_PID_FILE"
  wait_for_url http://127.0.0.1:8501/_stcore/health 90 "$STREAMLIT_LOG"
}

if curl --fail --silent http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1; then
  if pid_matches "$STREAMLIT_PID_FILE" "streamlit run" && streamlit_environment_matches; then
    echo "Streamlit is already ready."
  elif pid_matches "$STREAMLIT_PID_FILE" "streamlit run"; then
    stop_managed "$STREAMLIT_PID_FILE" "Streamlit"
    start_streamlit
  else
    echo "ERROR: Port 8501 is occupied by an unmanaged process." >&2
    exit 1
  fi
elif pid_matches "$STREAMLIT_PID_FILE" "streamlit run"; then
  wait_for_url http://127.0.0.1:8501/_stcore/health 90 "$STREAMLIT_LOG"
elif port_is_listening 8501; then
  echo "ERROR: Port 8501 is occupied by an unmanaged process." >&2
  exit 1
else
  start_streamlit
fi

echo "GLM-OCR stack ready at http://localhost:8501"
