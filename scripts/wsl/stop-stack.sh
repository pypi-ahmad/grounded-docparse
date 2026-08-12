#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.runtime"
STREAMLIT_PID_FILE="$RUNTIME_DIR/streamlit.pid"
DELAY_SECONDS="${1:-2}"

if [[ ! "$DELAY_SECONDS" =~ ^[0-9]+$ || "$DELAY_SECONDS" -gt 10 ]]; then
  echo "ERROR: Shutdown delay must be an integer from 0 to 10 seconds." >&2
  exit 2
fi

sleep "$DELAY_SECONDS"
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

streamlit_pid_matches() {
  local pid="$1"
  process_is_running "$pid" || return 1
  [[ "$(readlink -f "/proc/$pid/cwd")" == "$PROJECT_ROOT" ]] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" | grep -Fq "streamlit run streamlit_app.py"
}

stop_streamlit() {
  local pid
  [[ -f "$STREAMLIT_PID_FILE" ]] || return 0
  pid="$(<"$STREAMLIT_PID_FILE")"
  if ! streamlit_pid_matches "$pid"; then
    if process_is_running "$pid"; then
      echo "ERROR: Refusing to stop PID $pid because it is not this project's Streamlit process." >&2
      return 1
    fi
    rm -f "$STREAMLIT_PID_FILE"
    return 0
  fi
  kill "$pid"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    process_is_running "$pid" || { rm -f "$STREAMLIT_PID_FILE"; return 0; }
    sleep 1
  done
  echo "ERROR: Managed Streamlit process $pid did not stop within 30 seconds." >&2
  return 1
}

status=0
stop_streamlit || status=1
bash "$PROJECT_ROOT/scripts/wsl/manage-ocr-stack.sh" stop all || status=1
if [[ "$status" -eq 0 ]]; then
  echo "Grounded DocParse and all managed background services stopped."
else
  echo "ERROR: One or more managed services could not be stopped." >&2
fi
exit "$status"
