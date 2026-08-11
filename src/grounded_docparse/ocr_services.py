from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import OcrEngine
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
