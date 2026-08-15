from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import ExtractionEngine, OcrEngine
from .local_ocr import clear_glmocr_runtimes


def ensure_managed_ocr_engine(engine: OcrEngine) -> None:
    """Activate one local OCR service when managed-service mode is enabled."""

    if os.getenv("DOCPARSE_MANAGE_OCR_SERVICES", "false").casefold() in {
        "0",
        "false",
        "no",
    }:
        return
    if engine is OcrEngine.PADDLEOCR_VL_1_6:
        clear_glmocr_runtimes()
    script = Path("scripts/wsl/manage-ocr-stack.sh")
    subprocess.run(
        ["bash", str(script), "ensure", engine.value],
        check=True,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def stop_managed_vllm() -> None:
    if os.getenv("DOCPARSE_MANAGE_OCR_SERVICES", "false").casefold() not in {"1", "true", "yes"}:
        return
    script = Path("scripts/wsl/manage-ocr-stack.sh")
    subprocess.run(["bash", str(script), "stop"], check=True, capture_output=True, text=True, timeout=300)


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
