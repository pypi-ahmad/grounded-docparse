#!/usr/bin/env bash
set -euo pipefail

APP_DATA_DIR="${DOCPARSE_WSL_DATA:-$HOME/.local/share/grounded-docparse}"
OLLAMA_BIN="$APP_DATA_DIR/ollama/bin/ollama"
if [[ ! -x "$OLLAMA_BIN" ]]; then
  echo "ERROR: App-private Ollama is missing; rerun setup." >&2
  exit 1
fi

export OLLAMA_MODELS="${OLLAMA_MODELS:-$APP_DATA_DIR/ollama-models}"
export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_CONTEXT_LENGTH="32768"
exec "$OLLAMA_BIN" serve
