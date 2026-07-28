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

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is not available inside WSL." >&2
  exit 1
fi

if ! [[ -x "$WSL_ENV/bin/python" && -f "$WSL_ENV/.docparse-local-ocr-ready" ]]; then
  echo "Installing the locked GLM-OCR environment (first run only)..."
  bash scripts/wsl/setup-glmocr.sh
fi

pid_matches() {
  local pid_file="$1"
  local expected="$2"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(<"$pid_file")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
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

if curl --fail --silent http://127.0.0.1:8080/v1/models | grep -q 'glm-ocr'; then
  echo "vLLM is already ready."
elif pid_matches "$VLLM_PID_FILE" "vllm serve"; then
  echo "vLLM is already starting; waiting for readiness..."
  wait_for_url http://127.0.0.1:8080/v1/models 450 "$VLLM_LOG"
elif port_is_listening 8080; then
  echo "ERROR: Port 8080 is occupied by a process not managed by this launcher." >&2
  exit 1
else
  echo "Starting vLLM..."
  nohup bash scripts/wsl/serve-glmocr.sh >"$VLLM_LOG" 2>&1 &
  echo "$!" >"$VLLM_PID_FILE"
  wait_for_url http://127.0.0.1:8080/v1/models 450 "$VLLM_LOG"
  curl --fail --silent http://127.0.0.1:8080/v1/models | grep -q 'glm-ocr' || {
    echo "ERROR: vLLM is healthy but does not expose the glm-ocr model." >&2
    exit 1
  }
  echo "vLLM is ready."
fi

if curl --fail --silent http://127.0.0.1:8501/_stcore/health >/dev/null 2>&1; then
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
