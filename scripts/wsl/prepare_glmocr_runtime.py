#!/usr/bin/env python3
"""Resolve pinned model snapshots and materialize the offline GLM-OCR config."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

GLMOCR_REPO = "zai-org/GLM-OCR"
GLMOCR_REVISION = "ca5d8b3e287e52589e37c28385d9655ee4372f9d"
LAYOUT_REPO = "PaddlePaddle/PP-DocLayoutV3_safetensors"
LAYOUT_REVISION = "97d101e6db2642e162a1d05392d1b0231c91033e"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONFIG = PROJECT_ROOT / "config" / "glmocr.yaml"
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
RUNTIME_CONFIG = RUNTIME_DIR / "glmocr.yaml"
MODEL_PATH_FILE = RUNTIME_DIR / "glmocr-model-path"
MANIFEST_FILE = RUNTIME_DIR / "glmocr-models.json"
BACKENDS = ("vllm", "ollama")


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {name} must be an integer, got {raw!r}.") from exc
    if value < 1:
        raise SystemExit(f"ERROR: {name} must be at least 1, got {value}.")
    return value


def _resolve_snapshot(repo_id: str, revision: str, offline: bool) -> Path:
    from huggingface_hub import snapshot_download

    try:
        snapshot = Path(
            snapshot_download(
                repo_id=repo_id,
                revision=revision,
                local_files_only=offline,
            )
        ).resolve()
    except Exception as exc:
        mode = "cached offline" if offline else "download"
        raise SystemExit(
            f"ERROR: Unable to resolve {repo_id}@{revision} in {mode} mode. "
            "Run scripts/wsl/setup-glmocr.sh while online, then retry. "
            f"Upstream error: {type(exc).__name__}: {exc}"
        ) from exc
    if snapshot.name != revision:
        raise SystemExit(
            f"ERROR: {repo_id} resolved to {snapshot.name}, expected {revision}."
        )
    return snapshot


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _runtime_config(
    layout_path: Path,
    max_workers: int,
    *,
    backend: str = "vllm",
) -> dict[str, Any]:
    if backend not in BACKENDS:
        raise ValueError(f"Unsupported OCR backend: {backend}")
    config = yaml.safe_load(SOURCE_CONFIG.read_text(encoding="utf-8"))
    pipeline = config["pipeline"]
    pipeline["max_workers"] = max_workers
    pipeline["layout"]["model_dir"] = str(layout_path)
    if backend == "ollama":
        pipeline["layout"]["device"] = "cpu"
        pipeline["ocr_api"].update(
            {
                "api_port": 11434,
                "api_mode": "ollama_generate",
                "api_path": "/api/generate",
                "model": "glm-ocr:latest",
                "connect_timeout": 120,
                "request_timeout": 600,
                "connection_pool_size": 1,
            }
        )
    return config


def prepare(*, offline: bool, backend: str = "vllm") -> dict[str, str | int]:
    if backend not in BACKENDS:
        raise ValueError(f"Unsupported OCR backend: {backend}")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    layout_path = _resolve_snapshot(LAYOUT_REPO, LAYOUT_REVISION, offline)
    max_workers = _positive_int(
        "GLMOCR_SDK_MAX_WORKERS", 1 if backend == "ollama" else 16
    )
    glm_path = (
        _resolve_snapshot(GLMOCR_REPO, GLMOCR_REVISION, offline)
        if backend == "vllm"
        else None
    )

    config = _runtime_config(layout_path, max_workers, backend=backend)
    _atomic_write(RUNTIME_CONFIG, yaml.safe_dump(config, sort_keys=False))
    _atomic_write(
        MODEL_PATH_FILE,
        f"{glm_path}\n" if glm_path is not None else "glm-ocr:latest\n",
    )
    manifest: dict[str, str | int] = {
        "backend": backend,
        "glmocr_repo": GLMOCR_REPO,
        "glmocr_revision": GLMOCR_REVISION,
        "glmocr_path": str(glm_path) if glm_path is not None else "glm-ocr:latest",
        "layout_repo": LAYOUT_REPO,
        "layout_revision": LAYOUT_REVISION,
        "layout_path": str(layout_path),
        "sdk_max_workers": max_workers,
    }
    _atomic_write(MANIFEST_FILE, json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Resolve both exact revisions from the local Hugging Face cache only.",
    )
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default=os.environ.get("DOCPARSE_LOCAL_OCR_BACKEND", "vllm"),
    )
    args = parser.parse_args()
    manifest = prepare(offline=args.offline, backend=args.backend)
    print(
        "Prepared GLM-OCR "
        f"{manifest['glmocr_revision']} and PP-DocLayoutV3 "
        f"{manifest['layout_revision']} for {manifest['backend']} "
        f"(workers={manifest['sdk_max_workers']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
