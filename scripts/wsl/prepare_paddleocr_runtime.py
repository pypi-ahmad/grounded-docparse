"""Rewrite a PaddleX-generated PaddleOCR-VL pipeline YAML to point at this
project's persistent model cache and local vLLM server, optionally
downloading or validating the cached model/font assets first.

Reads `source` (PaddleX's generated config) and writes the rewritten config
to `target`; must not be used to bypass `validate_cached_assets` silently —
see the `--ensure-assets`/`--offline` note in `main` for when validation
actually runs.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

VLM_MODEL_NAME = "PaddleOCR-VL-1.6-0.9B"
VLM_CACHE_DIR = Path("official_models/PaddleOCR-VL-1.6")
LAYOUT_MODEL_NAME = "PP-DocLayoutV3"
LAYOUT_CACHE_DIR = Path("official_models/PP-DocLayoutV3")
FONT_FILE = Path("fonts/PingFang-SC-Regular.ttf")
REQUIRED_ASSET_FILES = (
    VLM_CACHE_DIR / "config.json",
    VLM_CACHE_DIR / "model.safetensors",
    VLM_CACHE_DIR / "tokenizer.json",
    LAYOUT_CACHE_DIR / "inference.json",
    LAYOUT_CACHE_DIR / "inference.pdiparams",
    FONT_FILE,
)


# Depth-first search through PaddleX's generated pipeline config, whose nesting
# shape is owned by PaddleX (not this project) and can vary by version — this
# doesn't assume a fixed structure, just that a dict keyed `name` exists somewhere.
def find_submodule(value, name):
    if isinstance(value, dict):
        candidate = value.get(name)
        if isinstance(candidate, dict):
            return candidate
        for child in value.values():
            found = find_submodule(child, name)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_submodule(child, name)
            if found is not None:
                return found
    return None


# PADDLE_PDX_CACHE_HOME is PaddleX's own environment variable, not this project's
# DOCPARSE_* convention — kept as-is so it stays interchangeable with PaddleX's own
# tooling and docs.
def paddle_cache_root() -> Path:
    return Path(
        os.environ.get("PADDLE_PDX_CACHE_HOME", Path.home() / ".paddlex")
    ).expanduser().resolve()


def validate_cached_assets(cache_root: Path) -> dict[str, Path]:
    cache_root = cache_root.expanduser().resolve()
    # Checks size, not just existence: an interrupted prior download can leave a
    # zero-byte placeholder file that is_file() alone would accept as present.
    missing = [
        path
        for relative_path in REQUIRED_ASSET_FILES
        if not (path := cache_root / relative_path).is_file()
        or path.stat().st_size == 0
    ]
    if missing:
        missing_names = ", ".join(str(path) for path in missing)
        raise RuntimeError(
            "PaddleOCR cache is incomplete. Missing: "
            f"{missing_names}. Run Setup-PaddleOCR-VL-1.6.cmd once while online "
            "to populate the cache."
        )
    return {
        "vlm_dir": cache_root / VLM_CACHE_DIR,
        "layout_dir": cache_root / LAYOUT_CACHE_DIR,
        "font_file": cache_root / FONT_FILE,
    }


def ensure_cached_assets(cache_root: Path) -> dict[str, Path]:
    try:
        return validate_cached_assets(cache_root)
    except RuntimeError:
        pass

    cache_root = cache_root.expanduser().resolve()
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_root)
    # Disables PaddleX's own model-source verification before triggering downloads.
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

    from paddlex.inference.utils.official_models import official_models
    from paddlex.utils.fonts import PINGFANG_FONT

    # Return values discarded deliberately: calling get_model_path()/.path is what
    # makes PaddleX download each asset if it's missing from cache_root. The actual
    # paths this function reports come from validate_cached_assets below, once
    # everything is confirmed present.
    official_models.get_model_path(VLM_MODEL_NAME)
    official_models.get_model_path(LAYOUT_MODEL_NAME)
    _ = PINGFANG_FONT.path
    return validate_cached_assets(cache_root)


def configure_pipeline(config, port, cache_root=None):
    cache_root = paddle_cache_root() if cache_root is None else Path(cache_root)
    # Fail closed if PaddleX generated a config this script doesn't recognize (wrong
    # or missing submodule, unexpected model_name) rather than silently pointing a
    # mismatched pipeline at this project's cache.
    layout = find_submodule(config, "LayoutDetection")
    if layout is None or layout.get("model_name") != LAYOUT_MODEL_NAME:
        raise RuntimeError("PaddleX v1.6 config must use PP-DocLayoutV3")
    layout["model_dir"] = str(cache_root / LAYOUT_CACHE_DIR)
    recognition = find_submodule(config, "VLRecognition")
    if recognition is None:
        raise RuntimeError("PaddleX config does not contain VLRecognition")
    recognition["model_name"] = VLM_MODEL_NAME
    recognition["model_dir"] = str(cache_root / VLM_CACHE_DIR)
    genai = recognition.setdefault("genai_config", {})
    genai["backend"] = "vllm-server"
    genai["server_url"] = f"http://127.0.0.1:{port}/v1"
    config["pipeline_name"] = "PaddleOCR-VL-1.6"
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    assets = parser.add_mutually_exclusive_group()
    assets.add_argument(
        "--ensure-assets",
        action="store_true",
        help="Download missing PaddleOCR runtime assets into the persistent cache.",
    )
    assets.add_argument(
        "--offline",
        action="store_true",
        help="Require all PaddleOCR runtime assets to exist in the local cache.",
    )
    args = parser.parse_args(sys.argv[1:])
    source, target = args.source, args.target
    config = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError("PaddleX generated an invalid pipeline configuration")
    # port is env-controlled and gets embedded verbatim into the generated YAML's
    # server_url below; validating it's digits-only within the valid port range
    # rejects malformed/unexpected values before they reach that string.
    port = os.environ.get("DOCPARSE_PADDLE_VLLM_PORT") or "8118"
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("DOCPARSE_PADDLE_VLLM_PORT must be between 1 and 65535")
    cache_root = paddle_cache_root()
    # Cache completeness is only checked when the caller opts into --ensure-assets or
    # --offline; with neither flag, configure_pipeline below proceeds on the
    # assumption that cache_root already has everything it needs.
    try:
        if args.ensure_assets:
            ensure_cached_assets(cache_root)
        elif args.offline:
            validate_cached_assets(cache_root)
    except RuntimeError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    configure_pipeline(config, port, cache_root)
    target.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
