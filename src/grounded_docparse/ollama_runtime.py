from __future__ import annotations

import base64
import json
import os
from enum import StrEnum
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image


class OllamaOcrModel(StrEnum):
    GLM_OCR = "glm-ocr:latest"
    PADDLEOCR_VL = "AuditAid/PaddleOCR-VL-1.6-0.9B:latest"
    DEEPSEEK_OCR = "deepseek-ocr:latest"


def _base_url() -> str:
    value = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    if value not in {"http://127.0.0.1:11434", "http://localhost:11434"}:
        raise ValueError("OLLAMA_BASE_URL must be the loopback Ollama service")
    return value


def unload_model(model: OllamaOcrModel) -> None:
    payload = json.dumps({"model": model.value, "keep_alive": 0}).encode()
    request = Request(f"{_base_url()}/api/generate", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30):  # noqa: S310 - URL is restricted to loopback above
        pass


def ensure_model(model: OllamaOcrModel) -> None:
    show = Request(
        f"{_base_url()}/api/show",
        data=json.dumps({"model": model.value}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(show, timeout=30):  # noqa: S310 - loopback only
            return
    except HTTPError as exc:
        if exc.code != 404:
            raise
    pull = Request(
        f"{_base_url()}/api/pull",
        data=json.dumps({"model": model.value, "stream": False}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(pull, timeout=3600):  # noqa: S310 - loopback only
        pass


def warm_model(model: OllamaOcrModel) -> None:
    ensure_model(model)
    image = Image.new("RGB", (16, 16), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    recognize_region(model, output.getvalue(), "text")


def recognize_region(model: OllamaOcrModel, image_bytes: bytes, region_type: str) -> str:
    """Recognize one detector-owned crop; the model cannot alter its box or order."""

    payload = json.dumps(
        {
            "model": model.value,
            "prompt": region_prompt(model, region_type),
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
            "keep_alive": "10m",
        }
    ).encode()
    request = Request(f"{_base_url()}/api/generate", data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=900) as response:  # noqa: S310 - loopback only
        result = json.load(response)
    return str(result.get("response", "")).strip()


def region_prompt(model: OllamaOcrModel, region_type: str) -> str:
    kind = region_type.casefold()
    if model is OllamaOcrModel.PADDLEOCR_VL:
        return "OCR:"
    if model is OllamaOcrModel.GLM_OCR:
        if "table" in kind:
            return "Table Recognition:"
        if "formula" in kind:
            return "Formula Recognition:"
        if kind in {"figure", "image", "chart"}:
            return "Figure Recognition:"
        return "Text Recognition:"
    if kind in {"figure", "image", "chart"}:
        return "Parse the figure."
    if "table" in kind or "formula" in kind:
        return "<|grounding|>Convert the document to markdown."
    return "Free OCR."


class OllamaRegionRecognizer:
    def __init__(self, model: OllamaOcrModel) -> None:
        self.model = model
        self.name = f"ollama:{model.value}"

    def recognize(self, image_bytes: bytes, region_type: str) -> str:
        return recognize_region(self.model, image_bytes, region_type)
