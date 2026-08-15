#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
STREAMLIT_LOG="$RUNTIME_DIR/streamlit.log"
STREAMLIT_PID_FILE="$RUNTIME_DIR/streamlit.pid"
STREAMLIT_PORT=7137
START_ENGINE="${DOCPARSE_START_ENGINE:-paddleocr-vl-1.6}"
PADDLE_API_PORT="${DOCPARSE_PADDLE_API_PORT:-8119}"
export DOCPARSE_PADDLEOCR_SERVICE_URL="${DOCPARSE_PADDLEOCR_SERVICE_URL:-http://127.0.0.1:$PADDLE_API_PORT}"

mkdir -p "$RUNTIME_DIR"
cd "$PROJECT_ROOT"
exec 8>"$RUNTIME_DIR/launch.lock"
flock 8

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
  tail -n 40 "$log_file" >&2 || true
  return 1
}

stop_managed() {
  local pid_file="$1" label="$2" pid
  pid="$(<"$pid_file")"
  kill "$pid"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    process_is_running "$pid" || { rm -f "$pid_file"; return 0; }
    sleep 1
  done
  echo "ERROR: Managed $label process $pid did not stop within 30 seconds." >&2
  return 1
}

streamlit_engine() {
  local pid entry
  [[ -f "$STREAMLIT_PID_FILE" ]] || return 1
  pid="$(<"$STREAMLIT_PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/environ" ]] || return 1
  while IFS= read -r -d '' entry; do
    [[ "$entry" == DOCPARSE_OCR_ENGINE=* ]] && {
      printf '%s' "${entry#*=}"
      return 0
    }
  done <"/proc/$pid/environ"
  return 1
}

streamlit_source_fingerprint() {
  {
    printf '%s\0' \
      "$PROJECT_ROOT/streamlit_app.py" \
      "$PROJECT_ROOT/scripts/wsl/run-app.sh" \
      "$PROJECT_ROOT/.streamlit/config.toml" \
      "$PROJECT_ROOT/pyproject.toml" \
      "$PROJECT_ROOT/uv.lock"
    find "$PROJECT_ROOT/src/grounded_docparse" -type f -name '*.py' -print0
  } | sort -z | while IFS= read -r -d '' source_file; do
    sha256sum "$source_file"
  done | sha256sum | awk '{print $1}'
}

streamlit_uses_configured_port() {
  [[ -f "$STREAMLIT_PID_FILE" ]] || return 1
  local pid
  pid="$(<"$STREAMLIT_PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" | grep -Fq -- "--server.port $STREAMLIT_PORT"
}

if pid_matches "$STREAMLIT_PID_FILE" "streamlit run"; then
  CURRENT_ENGINE="$(streamlit_engine || true)"
  CURRENT_ENGINE="${CURRENT_ENGINE:-glm-ocr}"
  if [[ "$CURRENT_ENGINE" != "$START_ENGINE" ]] || ! streamlit_uses_configured_port; then
    echo "Stopping Streamlit before applying runtime configuration..."
    stop_managed "$STREAMLIT_PID_FILE" "Streamlit"
  fi
elif port_is_listening "$STREAMLIT_PORT"; then
  echo "ERROR: Port $STREAMLIT_PORT is occupied by an unmanaged process." >&2
  exit 1
fi

streamlit_environment_matches() {
  [[ -f "$STREAMLIT_PID_FILE" ]] || return 1
  local pid current_key="" current_base_url="" current_google_key="" current_engine=""
  local current_source_fingerprint="" entry
  pid="$(<"$STREAMLIT_PID_FILE")"
  [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/environ" ]] || return 1
  while IFS= read -r -d '' entry; do
    case "$entry" in
      OPENAI_API_KEY=*) current_key="${entry#*=}" ;;
      OPENAI_BASE_URL=*) current_base_url="${entry#*=}" ;;
      GOOGLE_API_KEY=*) current_google_key="${entry#*=}" ;;
      DOCPARSE_OCR_ENGINE=*) current_engine="${entry#*=}" ;;
      DOCPARSE_SOURCE_FINGERPRINT=*) current_source_fingerprint="${entry#*=}" ;;
    esac
  done <"/proc/$pid/environ"
  [[ "$current_key" == "${OPENAI_API_KEY-}" && \
    "$current_base_url" == "${OPENAI_BASE_URL-}" && \
    "$current_google_key" == "${GOOGLE_API_KEY-}" && \
    "$current_engine" == "$START_ENGINE" && \
    "$current_source_fingerprint" == "$(streamlit_source_fingerprint)" ]] && \
    streamlit_uses_configured_port
}

start_streamlit() {
  echo "Starting Streamlit..."
  local preload=false source_fingerprint
  [[ "$START_ENGINE" == "glm-ocr" ]] && preload=true
  source_fingerprint="$(streamlit_source_fingerprint)"
  DOCPARSE_MANAGE_OCR_SERVICES=true \
  DOCPARSE_OCR_ENGINE="$START_ENGINE" \
  DOCPARSE_PRELOAD_LOCAL_OCR="$preload" \
  DOCPARSE_SOURCE_FINGERPRINT="$source_fingerprint" \
    nohup bash scripts/wsl/run-app.sh --server.headless true --server.port "$STREAMLIT_PORT" 8>&- \
    >"$STREAMLIT_LOG" 2>&1 &
  echo "$!" >"$STREAMLIT_PID_FILE"
  wait_for_url "http://127.0.0.1:$STREAMLIT_PORT/_stcore/health" 90 "$STREAMLIT_LOG"
}

if curl --fail --silent "http://127.0.0.1:$STREAMLIT_PORT/_stcore/health" >/dev/null 2>&1; then
  if pid_matches "$STREAMLIT_PID_FILE" "streamlit run" && streamlit_environment_matches; then
    echo "Streamlit is already ready."
  elif pid_matches "$STREAMLIT_PID_FILE" "streamlit run"; then
    stop_managed "$STREAMLIT_PID_FILE" "Streamlit"
    start_streamlit
  else
    echo "ERROR: Port $STREAMLIT_PORT is occupied by an unmanaged process." >&2
    exit 1
  fi
elif pid_matches "$STREAMLIT_PID_FILE" "streamlit run"; then
  wait_for_url "http://127.0.0.1:$STREAMLIT_PORT/_stcore/health" 90 "$STREAMLIT_LOG"
elif port_is_listening "$STREAMLIT_PORT"; then
  echo "ERROR: Port $STREAMLIT_PORT is occupied by an unmanaged process." >&2
  exit 1
else
  start_streamlit
fi

echo "$START_ENGINE stack ready at http://localhost:$STREAMLIT_PORT"
