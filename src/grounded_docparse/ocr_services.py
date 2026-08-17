from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import AlternateOcrEngine, ExtractionEngine, OcrEngine, ParserConfig
from .local_ocr import clear_glmocr_runtimes
from .ollama_runtime import OllamaOcrModel, unload_model, warm_model

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_OCR_OPERATION_LOCK = threading.RLock()


@contextmanager
def ocr_operation() -> Iterator[None]:
    """Keep process-wide OCR parsing and engine lifecycle changes exclusive."""

    with _OCR_OPERATION_LOCK:
        yield


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

    if engine in {OcrEngine.OLLAMA, OcrEngine.RAPIDOCR} or os.getenv(
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


@contextmanager
def temporary_alternate_ocr_engine(
    config: ParserConfig,
    alternate: AlternateOcrEngine,
    *,
    vllm_switcher: Callable[[OcrEngine], None] = ensure_managed_ocr_engine,
) -> Iterator[None]:
    """Temporarily activate an alternate OCR runtime and restore the primary."""

    if alternate.matches_primary(config.ocr_engine, config.ollama_model):
        raise ValueError("alternate OCR engine must differ from the primary engine")
    if alternate is AlternateOcrEngine.RAPIDOCR:
        yield
        return

    primary_ollama = (
        OllamaOcrModel(config.ollama_model)
        if config.ocr_engine is OcrEngine.OLLAMA
        else None
    )
    alternate_ollama = (
        OllamaOcrModel(alternate.ollama_model)
        if alternate.ollama_model is not None
        else None
    )
    alternate_started = False
    try:
        if primary_ollama is not None:
            unload_model(primary_ollama)
        elif alternate_ollama is not None:
            stop_managed_vllm()

        if alternate.vllm_engine is not None:
            vllm_switcher(alternate.vllm_engine)
        elif alternate_ollama is not None:
            warm_model(alternate_ollama)
        alternate_started = True
        yield
    finally:
        cleanup_error: Exception | None = None
        if alternate_started and alternate_ollama is not None:
            try:
                unload_model(alternate_ollama)
            except Exception as exc:  # noqa: BLE001 - primary restoration has priority
                cleanup_error = exc
        try:
            if primary_ollama is not None:
                if alternate.vllm_engine is not None:
                    stop_managed_vllm()
                warm_model(primary_ollama)
            elif config.ocr_engine is OcrEngine.RAPIDOCR:
                if alternate.vllm_engine is not None:
                    stop_managed_vllm()
            else:
                vllm_switcher(config.ocr_engine)
        except Exception as exc:
            raise RuntimeError(f"Primary OCR restoration failed: {exc}") from exc
        if cleanup_error is not None:
            raise cleanup_error


def switch_extraction_engine(target: ExtractionEngine, previous: ExtractionEngine | None = None) -> None:
    """Apply an exclusive engine selection and restore the prior vLLM stack on failure."""

    with ocr_operation():
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
