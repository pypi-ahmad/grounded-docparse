#!/usr/bin/env bash
set -euo pipefail

OLLAMA_VERSION="0.32.0"
OLLAMA_MODEL="glm-ocr:bf16"
APP_DATA_DIR="${DOCPARSE_WSL_DATA:-$HOME/.local/share/grounded-docparse}"
OLLAMA_ROOT="$APP_DATA_DIR/ollama"
OLLAMA_BIN="$OLLAMA_ROOT/bin/ollama"
BASE_SHA256="56362d7609dfa9e35aaebb7c9cab25605d8f0528ec3d5d585dc83d6642002bab"
ROCM_SHA256="f0fad39e184daab11d172a855580abd7338b2f049afa462435fee15d76b4e437"

download_and_extract() {
  local asset="$1" expected="$2" archive
  archive="$(mktemp --suffix=.tar.zst)"
  trap 'rm -f "${archive:-}"' RETURN
  curl --proto '=https' --tlsv1.2 -fL \
    "https://github.com/ollama/ollama/releases/download/v$OLLAMA_VERSION/$asset" \
    -o "$archive"
  printf '%s  %s\n' "$expected" "$archive" | sha256sum -c -
  tar --zstd -xf "$archive" -C "$OLLAMA_ROOT"
  rm -f "$archive"
  trap - RETURN
}

if ! command -v zstd >/dev/null 2>&1; then
  echo "ERROR: zstd is required to install Ollama." >&2
  exit 1
fi

if [[ ! -x "$OLLAMA_BIN" ]] || ! "$OLLAMA_BIN" --version 2>&1 | grep -Fq "$OLLAMA_VERSION"; then
  echo "Installing app-private Ollama $OLLAMA_VERSION..."
  if [[ -z "$APP_DATA_DIR" || "$APP_DATA_DIR" == "/" || "$OLLAMA_ROOT" != "$APP_DATA_DIR/ollama" ]]; then
    echo "ERROR: Refusing unsafe Ollama install path: $OLLAMA_ROOT" >&2
    exit 1
  fi
  rm -rf "$OLLAMA_ROOT"
  mkdir -p "$OLLAMA_ROOT"
  download_and_extract "ollama-linux-amd64.tar.zst" "$BASE_SHA256"
  if [[ "${DOCPARSE_AMD_GPU:-false}" == "true" ]]; then
    download_and_extract "ollama-linux-amd64-rocm.tar.zst" "$ROCM_SHA256"
  fi
fi

export OLLAMA_MODELS="${OLLAMA_MODELS:-$APP_DATA_DIR/ollama-models}"
export OLLAMA_HOST="127.0.0.1:11434"
export OLLAMA_CONTEXT_LENGTH="32768"
mkdir -p "$OLLAMA_MODELS"

if ! "$OLLAMA_BIN" list 2>/dev/null | grep -Fq "glm-ocr:bf16"; then
  echo "Downloading $OLLAMA_MODEL..."
  "$OLLAMA_BIN" serve >"$APP_DATA_DIR/ollama-setup.log" 2>&1 &
  server_pid=$!
  trap 'kill "$server_pid" 2>/dev/null || true' EXIT
  for _ in {1..60}; do
    curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
  curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null
  "$OLLAMA_BIN" pull "$OLLAMA_MODEL"
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
  trap - EXIT
fi
