"""Local Ollama /api/chat client used as a RegionRecognizer (see grounded_ocr.py) for
GLM-OCR, PaddleOCR-VL, and DeepSeek-OCR served through Ollama rather than vLLM.

Must not: point at a non-loopback endpoint (`_base_url` enforces this even though the
origin comes from an env var). Must not let a struggling model retry indefinitely — DeepSeek
gets one bounded extra attempt per region and a hard stop after
DEEPSEEK_MAX_CONSECUTIVE_FAILURES consecutive whole-region failures.

Next: grounded_ocr.py's GroundedOcrRuntime drives OllamaRegionRecognizer through the
RegionRecognizer protocol and enforces the page-level timeout on top of this module's
per-request timeout.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from difflib import SequenceMatcher
from enum import StrEnum
from io import BytesIO
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

OLLAMA_CONTEXT_TOKENS = 4_096
OLLAMA_WARMUP_OUTPUT_TOKENS = 1
OLLAMA_REQUEST_TIMEOUT_SECONDS = 120.0
OLLAMA_PAGE_TIMEOUT_SECONDS = 300.0
DEEPSEEK_RETRY_DELAY_SECONDS = 0.5
DEEPSEEK_MAX_CONSECUTIVE_FAILURES = 3

logger = logging.getLogger(__name__)

_CONTROL_TOKEN = re.compile(r"<\|(?:im_end|md_continue|endofsentence)\|>")
_MARKDOWN_BLOCK = re.compile(r"<\|md_start\|>(.*?)<\|md_end\|>", re.DOTALL)


class OllamaOcrModel(StrEnum):
    GLM_OCR = "glm-ocr:latest"
    PADDLEOCR_VL = "AuditAid/PaddleOCR-VL-1.6-0.9B:latest"
    DEEPSEEK_OCR = "deepseek-ocr:latest"

    @property
    def element_source(self) -> Literal["glm-ocr", "paddleocr-vl-1.6", "deepseek-ocr"]:
        return {
            OllamaOcrModel.GLM_OCR: "glm-ocr",
            OllamaOcrModel.PADDLEOCR_VL: "paddleocr-vl-1.6",
            OllamaOcrModel.DEEPSEEK_OCR: "deepseek-ocr",
        }[self]


def _base_url() -> str:
    # OLLAMA_BASE_URL is environment-controlled input; only these two loopback spellings
    # are accepted, so a misconfigured or malicious value can't redirect OCR image bytes
    # to a remote host.
    value = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    if value not in {"http://127.0.0.1:11434", "http://localhost:11434"}:
        raise ValueError("OLLAMA_BASE_URL must be the loopback Ollama service")
    return value


def unload_model(model: OllamaOcrModel) -> None:
    # keep_alive: 0 tells Ollama to evict the model from memory immediately.
    payload = json.dumps({"model": model.value, "keep_alive": 0}).encode()
    request = Request(f"{_base_url()}/api/generate", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30):
        pass


def ensure_model(model: OllamaOcrModel) -> None:
    # /api/show 404 means the model isn't pulled locally yet; anything else (network error,
    # other HTTP status) is a real failure and propagates instead of triggering a pull.
    show = Request(
        f"{_base_url()}/api/show",
        data=json.dumps({"model": model.value}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(show, timeout=30):
            return
    except HTTPError as exc:
        if exc.code != 404:
            raise
    pull = Request(
        f"{_base_url()}/api/pull",
        data=json.dumps({"model": model.value, "stream": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(pull, timeout=3600):
        pass


def warm_model(model: OllamaOcrModel) -> None:
    # A throwaway 1-token recognize call on a blank image forces Ollama to load the model
    # into memory now, so the first real page doesn't pay model-load latency.
    ensure_model(model)
    image = Image.new("RGB", (16, 16), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    _generate_region(
        model,
        output.getvalue(),
        "text",
        max_output_tokens=OLLAMA_WARMUP_OUTPUT_TOKENS,
        timeout_seconds=OLLAMA_REQUEST_TIMEOUT_SECONDS,
    )


def recognize_region(
    model: OllamaOcrModel,
    image_bytes: bytes,
    region_type: str,
    *,
    region_area: float = 0.0,
    timeout_seconds: float = OLLAMA_REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Recognize one detector-owned crop; the model cannot alter its box or order."""

    return _generate_region(
        model,
        image_bytes,
        region_type,
        max_output_tokens=_max_output_tokens(region_type, region_area),
        timeout_seconds=timeout_seconds,
    )


def _generate_region(
    model: OllamaOcrModel,
    image_bytes: bytes,
    region_type: str,
    *,
    max_output_tokens: int,
    timeout_seconds: float,
    prompt: str | None = None,
) -> str:
    started = time.perf_counter()
    payload = json.dumps(
        {
            "model": model.value,
            "messages": [
                {
                    "role": "user",
                    "content": prompt or region_prompt(model, region_type),
                    "images": [base64.b64encode(image_bytes).decode("ascii")],
                }
            ],
            "stream": False,
            # Unlike unload_model's keep_alive=0, a real recognition call keeps the model
            # loaded for 10 more minutes so back-to-back regions/pages don't reload it.
            "keep_alive": "10m",
            "options": {
                "temperature": 0,
                "num_ctx": OLLAMA_CONTEXT_TOKENS,
                "num_predict": max_output_tokens,
            },
        }
    ).encode()
    request = Request(
        f"{_base_url()}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    logger.info(
        "Ollama OCR request started: model=%s label=%s image_bytes=%d "
        "num_ctx=%d num_predict=%d timeout_seconds=%.1f",
        model.value,
        region_type,
        len(image_bytes),
        OLLAMA_CONTEXT_TOKENS,
        max_output_tokens,
        timeout_seconds,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            result = json.load(response)
    except TimeoutError as exc:
        # Re-raised as a new TimeoutError with the configured bound in the message rather
        # than swallowed — callers (e.g. grounded_ocr.py's page-deadline check) still see a
        # TimeoutError, just a more diagnosable one.
        logger.exception(
            "Ollama OCR request timed out: model=%s label=%s timeout_seconds=%.1f",
            model.value,
            region_type,
            timeout_seconds,
        )
        raise TimeoutError(
            f"Ollama OCR request timed out after {timeout_seconds:g} seconds"
        ) from exc
    content = clean_ocr_output(str(result.get("message", {}).get("content", "")))
    logger.info(
        "Ollama OCR request completed: model=%s label=%s elapsed_ms=%.1f "
        "prompt_tokens=%s output_tokens=%s done_reason=%s total_duration_ms=%s "
        "load_duration_ms=%s output_characters=%d",
        model.value,
        region_type,
        (time.perf_counter() - started) * 1000,
        result.get("prompt_eval_count", 0),
        result.get("eval_count", 0),
        result.get("done_reason", "unknown"),
        _duration_ms(result.get("total_duration")),
        _duration_ms(result.get("load_duration")),
        len(content),
    )
    return content


def _duration_ms(value: object) -> float | None:
    return round(value / 1_000_000, 1) if isinstance(value, (int, float)) else None


def _max_output_tokens(region_type: str, region_area: float) -> int:
    # Output budget tiers by region size/type: tables need the most room, large regions
    # (>3% of page area) get a mid-size budget, everything else gets the smallest — this
    # keeps small text regions cheap while avoiding truncation on tables and big regions.
    return 512 if "table" in region_type.casefold() else 256 if region_area > 0.03 else 128


def clean_ocr_output(value: str) -> str:
    # Workaround for small-VLM failure modes seen in practice: models sometimes wrap output
    # in repeated <|md_start|>...<|md_end|> blocks, echo the same line back multiple times
    # with minor variation, or answer with a clarifying/meta question instead of
    # transcribing. None of this is real document content, so it is deduplicated or cut
    # rather than passed through.
    blocks = [block.strip() for block in _MARKDOWN_BLOCK.findall(value) if block.strip()]
    if blocks:
        deduplicated: list[str] = []
        for block in blocks:
            if not deduplicated or block != deduplicated[-1]:
                deduplicated.append(block)
        value = "\n\n".join(deduplicated)
    value = _CONTROL_TOKEN.sub("", value).strip()
    if value.startswith("```") and value.endswith("```"):
        value = re.sub(r"^```(?:markdown|md|html|text)?\s*", "", value, count=1)
        value = re.sub(r"\s*```$", "", value, count=1)
    lines: list[str] = []
    seen_nonempty: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"```(?:markdown|md|html|text)?", stripped):
            continue
        if stripped:
            normalized = stripped.casefold()
            # The model is asking a question back instead of transcribing; everything from
            # here on is model chatter, not page content, so the rest of the output is cut.
            if normalized.startswith(
                (
                    "type the text:",
                    "is there any text that can be recognized",
                    "answer the following question",
                )
            ):
                break
            # Near-duplicate detection: exact repeats, one line prefixing another, or a
            # >=90% fuzzy match (only checked once both lines are at least 40 characters,
            # to avoid false positives on short lines that legitimately repeat, e.g. table
            # cells) are treated as the model looping and dropped.
            if any(
                normalized == previous
                or (
                    min(len(normalized), len(previous)) >= 40
                    and (
                        normalized.startswith(previous)
                        or previous.startswith(normalized)
                        or SequenceMatcher(None, normalized, previous).ratio() >= 0.9
                    )
                )
                for previous in seen_nonempty
            ):
                continue
            seen_nonempty.append(normalized)
        if not lines or stripped != lines[-1].strip():
            lines.append(line)
    return "\n".join(lines).strip()


def region_prompt(model: OllamaOcrModel, region_type: str) -> str:
    kind = region_type.casefold()
    if model is OllamaOcrModel.PADDLEOCR_VL:
        return "OCR:"
    if model is OllamaOcrModel.GLM_OCR:
        if "table" in kind:
            return "Table Recognition:"
        if "formula" in kind:
            return "Formula Recognition:"
        if kind in {"figure", "image", "chart", "seal"}:
            return "Figure Recognition:"
        return "Text Recognition:"
    if kind in {"figure", "image", "chart"}:
        return "Parse the figure."
    if "table" in kind or "formula" in kind:
        return "<|grounding|>Convert the document to markdown."
    return "Free OCR."


class OllamaRegionRecognizer:
    def __init__(
        self,
        model: OllamaOcrModel,
        *,
        timeout_seconds: float = OLLAMA_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.name = f"ollama:{model.value}"
        # `fail_fast` is read by grounded_ocr.py's GroundedOcrRuntime: an unhandled
        # exception from recognize() aborts the whole page rather than being downgraded to
        # a single failed region.
        self.fail_fast = True
        # Persists across recognize() calls (i.e. across regions/pages on this instance),
        # not just within one call — see the escalation check at the end of recognize().
        self._consecutive_failures = 0

    def recognize(
        self,
        image_bytes: bytes,
        region_type: str,
        *,
        region_area: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> str:
        effective_timeout = timeout_seconds or self.timeout_seconds
        max_tokens = _max_output_tokens(region_type, region_area)
        prompt = region_prompt(self.model, region_type)
        # Only DeepSeek-OCR gets a bounded second attempt with a more forceful prompt; the
        # other models are given one try (retries are handled at a higher level for them,
        # if at all).
        attempts = 2 if self.model is OllamaOcrModel.DEEPSEEK_OCR else 1
        last_error: Exception | None = None
        content = ""
        for attempt in range(1, attempts + 1):
            try:
                content = _generate_region(
                    self.model,
                    image_bytes,
                    region_type,
                    max_output_tokens=max_tokens,
                    timeout_seconds=effective_timeout,
                    prompt=prompt,
                )
            except Exception as exc:
                last_error = exc
                if attempts == 1 or not _retryable_ocr_error(exc):
                    raise
                logger.warning(
                    "DeepSeek OCR request failed: label=%s attempt=%d error=%s",
                    region_type,
                    attempt,
                    type(exc).__name__,
                )
            else:
                # A visual region type legitimately may have no transcribable text, so
                # empty content there is success, not a failure to retry.
                if content or region_type.casefold() in {"figure", "image", "chart", "seal"}:
                    self._consecutive_failures = 0
                    return content
                if attempts == 1:
                    return ""
            if attempt < attempts:
                # Retry with a blunter instruction: DeepSeek sometimes responds
                # conversationally on the first attempt instead of transcribing.
                prompt = (
                    "Transcribe all visible text in this crop exactly. Return only the "
                    "transcription; do not explain or add Markdown fences."
                )
                time.sleep(DEEPSEEK_RETRY_DELAY_SECONDS)

        self._consecutive_failures += 1
        logger.warning(
            "DeepSeek OCR region skipped after two attempts: label=%s consecutive_failures=%d",
            region_type,
            self._consecutive_failures,
        )
        if self._consecutive_failures >= DEEPSEEK_MAX_CONSECUTIVE_FAILURES:
            # Safety valve: stop the page rather than let a stuck model burn through every
            # remaining region two attempts at a time.
            raise RuntimeError(
                "DeepSeek OCR stopped after three consecutive region failures"
            ) from last_error
        return ""


def _retryable_ocr_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in {408, 429} or exc.code >= 500
    # KeyError/TypeError/ValueError here mean the response body didn't have the expected
    # shape (e.g. Ollama returned something unexpected) — treated as transient/retryable
    # rather than a bug, same as a network-level TimeoutError/URLError.
    return isinstance(exc, (TimeoutError, URLError, KeyError, TypeError, ValueError))
