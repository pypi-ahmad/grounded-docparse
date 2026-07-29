#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
VLLM_LOG="$RUNTIME_DIR/vllm.log"
STREAMLIT_LOG="$RUNTIME_DIR/streamlit.log"
VLLM_PID_FILE="$RUNTIME_DIR/vllm.pid"
STREAMLIT_PID_FILE="$RUNTIME_DIR/streamlit.pid"

mkdir -p "$RUNTIME_DIR"
cd "$PROJECT_ROOT"
WSL_ENV="${DOCPARSE_WSL_ENV:-$HOME/.local/share/grounded-docparse/.venv}"

if ! [[ -x "$WSL_ENV/bin/python" && -f "$WSL_ENV/.docparse-local-ocr-ready" ]]; then
  echo "Installing the locked GLM-OCR environment (first run only)..."
  bash scripts/wsl/setup-glmocr.sh
fi

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
"$WSL_ENV/bin/python" scripts/wsl/prepare_glmocr_runtime.py --offline >/dev/null
GLMOCR_MODEL_PATH="$(<"$RUNTIME_DIR/glmocr-model-path")"
GLMOCR_RUNTIME_CONFIG="$RUNTIME_DIR/glmocr.yaml"
export DOCPARSE_GLMOCR_CONFIG_PATH="$GLMOCR_RUNTIME_CONFIG"

pid_matches() {
  local pid_file="$1"
  local expected="$2"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(<"$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
  [[ "$(awk '{print $3}' "/proc/$pid/stat")" != "Z" ]] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" | grep -Fq "$expected"
}

port_is_listening() {
  local port="$1"
  ss -ltnH "sport = :$port" | grep -q .
}

wait_for_url() {
  local url="$1"
  local attempts="$2"
  local log_file="$3"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: Timed out waiting for $url" >&2
  echo "Last log lines from $log_file:" >&2
  tail -n 40 "$log_file" >&2 || true
  return 1
}

glm_model_is_ready() {
  curl --fail --silent http://127.0.0.1:8080/v1/models | grep -q 'glm-ocr'
}

glm_inference_is_ready() {
  "$WSL_ENV/bin/python" scripts/wsl/check-glmocr-api.py
}

streamlit_environment_matches() {
  [[ -f "$STREAMLIT_PID_FILE" ]] || return 1
  local pid current_key="" current_base_url="" current_config="" entry
  pid="$(<"$STREAMLIT_PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/environ" ]] || return 1
  while IFS= read -r -d '' entry; do
    case "$entry" in
      OPENAI_API_KEY=*) current_key="${entry#*=}" ;;
      OPENAI_BASE_URL=*) current_base_url="${entry#*=}" ;;
      DOCPARSE_GLMOCR_CONFIG_PATH=*) current_config="${entry#*=}" ;;
    esac
  done <"/proc/$pid/environ"
  [[ "$current_key" == "${OPENAI_API_KEY-}" && \
    "$current_base_url" == "${OPENAI_BASE_URL-}" && \
    "$current_config" == "$GLMOCR_RUNTIME_CONFIG" ]]
}

stop_managed_vllm() {
  local pid
  pid="$(<"$VLLM_PID_FILE")"
  kill "$pid"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    kill -0 "$pid" 2>/dev/null || {
      rm -f "$VLLM_PID_FILE"
      return 0
    }
    sleep 1
  done
  echo "ERROR: Managed vLLM process $pid did not stop within 30 seconds." >&2
  return 1
}

stop_managed_streamlit() {
  local pid
  pid="$(<"$STREAMLIT_PID_FILE")"
  kill "$pid"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    kill -0 "$pid" 2>/dev/null || {
      rm -f "$STREAMLIT_PID_FILE"
      return 0
    }
    sleep 1
  done
  echo "ERROR: Managed Streamlit process $pid did not stop within 30 seconds." >&2
  return 1
}

start_vllm() {
  echo "Starting vLLM..."
  nohup bash scripts/wsl/serve-glmocr.sh >"$VLLM_LOG" 2>&1 &
  echo "$!" >"$VLLM_PID_FILE"
  wait_for_url http://127.0.0.1:8080/v1/models 450 "$VLLM_LOG"
  glm_model_is_ready || {
    echo "ERROR: vLLM is healthy but does not expose the glm-ocr model." >&2
    return 1
  }
  glm_inference_is_ready
}

if glm_model_is_ready && pid_matches "$VLLM_PID_FILE" "vllm serve" && \
  ! pid_matches "$VLLM_PID_FILE" "$GLMOCR_MODEL_PATH"; then
  echo "Managed vLLM uses a stale or unpinned model path; restarting it..."
  stop_managed_vllm
  start_vllm
  echo "vLLM is ready."
elif glm_model_is_ready; then
  if glm_inference_is_ready; then
    echo "vLLM is already ready."
  elif pid_matches "$VLLM_PID_FILE" "vllm serve"; then
    echo "Managed vLLM failed inference validation; restarting it..."
    stop_managed_vllm
    start_vllm
    echo "vLLM is ready."
  else
    echo "ERROR: The unmanaged vLLM server on port 8080 failed inference validation." >&2
    exit 1
  fi
elif pid_matches "$VLLM_PID_FILE" "vllm serve"; then
  echo "vLLM is already starting; waiting for readiness..."
  wait_for_url http://127.0.0.1:8080/v1/models 450 "$VLLM_LOG"
  if glm_model_is_ready && glm_inference_is_ready; then
    echo "vLLM is ready."
  else
    echo "Managed vLLM failed inference validation; restarting it..."
    stop_managed_vllm
    start_vllm
    echo "vLLM is ready."
  fi
elif port_is_listening 8080; then
  echo "ERROR: Port 8080 is occupied by a process not managed by this launcher." >&2
  exit 1
else
  start_vllm
  echo "vLLM is ready."
fi

if curl --fail --silent http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1 && \
  pid_matches "$STREAMLIT_PID_FILE" "streamlit run" && \
  ! streamlit_environment_matches; then
  echo "Managed Streamlit environment changed; restarting it..."
  stop_managed_streamlit
  DOCPARSE_PRELOAD_LOCAL_OCR=true nohup bash scripts/wsl/run-app.sh \
    --server.headless true >"$STREAMLIT_LOG" 2>&1 &
  echo "$!" >"$STREAMLIT_PID_FILE"
  wait_for_url http://127.0.0.1:8501/_stcore/health 90 "$STREAMLIT_LOG"
  echo "Streamlit is ready."
elif curl --fail --silent http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1; then
  echo "Streamlit is already ready."
elif pid_matches "$STREAMLIT_PID_FILE" "streamlit run"; then
  echo "Streamlit is already starting; waiting for readiness..."
  wait_for_url http://127.0.0.1:8501/_stcore/health 90 "$STREAMLIT_LOG"
elif port_is_listening 8501; then
  echo "ERROR: Port 8501 is occupied by a process not managed by this launcher." >&2
  exit 1
else
  echo "Starting Streamlit and preloading PP-DocLayout..."
  DOCPARSE_PRELOAD_LOCAL_OCR=true nohup bash scripts/wsl/run-app.sh \
    --server.headless true >"$STREAMLIT_LOG" 2>&1 &
  echo "$!" >"$STREAMLIT_PID_FILE"
  wait_for_url http://127.0.0.1:8501/_stcore/health 90 "$STREAMLIT_LOG"
  echo "Streamlit is ready."
fi

echo "GLM-OCR stack ready at http://localhost:8501"
