from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import ExtractionEngine, OcrEngine
from .local_ocr import clear_glmocr_runtimes

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _manager_command(*arguments: str) -> tuple[list[str], dict[str, str]]:
    manager = PROJECT_ROOT / "scripts" / "wsl" / "manage-ocr-stack.sh"
    environment = os.environ.copy()
    if os.name != "nt":
        return ["bash", str(manager), *arguments], environment
    environment["DOCPARSE_WINDOWS_ROOT"] = str(PROJECT_ROOT)
    forwarded = [item for item in environment.get("WSLENV", "").split(":") if item]
    if "DOCPARSE_WINDOWS_ROOT/p" not in forwarded:
        forwarded.append("DOCPARSE_WINDOWS_ROOT/p")
    environment["WSLENV"] = ":".join(forwarded)
    distro = environment.get("DOCPARSE_WSL_DISTRO", "Ubuntu-24.04")
    argument_text = " ".join(arguments)
    command = (
        'cd "$DOCPARSE_WINDOWS_ROOT" && '
        f"bash scripts/wsl/manage-ocr-stack.sh {argument_text}"
    )
    return ["wsl.exe", "-d", distro, "--", "bash", "-lc", command], environment


def _run_manager(*arguments: str, timeout: float) -> None:
    command, environment = _manager_command(*arguments)
    subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ensure_managed_ocr_engine(engine: OcrEngine) -> None:
    """Activate one local OCR service when managed-service mode is enabled."""

    if engine is OcrEngine.OLLAMA or os.getenv(
        "DOCPARSE_MANAGE_OCR_SERVICES", "false"
    ).casefold() in {
        "0",
        "false",
        "no",
    }:
        return
    if engine is OcrEngine.PADDLEOCR_VL_1_6:
        clear_glmocr_runtimes()
    _run_manager("ensure", engine.value, timeout=1800)


def stop_managed_vllm() -> None:
    if os.getenv("DOCPARSE_MANAGE_OCR_SERVICES", "false").casefold() not in {"1", "true", "yes"}:
        return
    _run_manager("stop", "all", timeout=300)


def switch_extraction_engine(target: ExtractionEngine, previous: ExtractionEngine | None = None) -> None:
    """Apply an exclusive engine selection and restore the prior vLLM stack on failure."""

    target_ocr = target.vllm_ocr_engine
    try:
        if target_ocr is None:
            stop_managed_vllm()
        else:
            ensure_managed_ocr_engine(target_ocr)
    except Exception:
        previous_ocr = previous.vllm_ocr_engine if previous is not None else None
        if previous_ocr is not None:
            ensure_managed_ocr_engine(previous_ocr)
        raise
