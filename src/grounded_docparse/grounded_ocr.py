from __future__ import annotations

import base64
import json
import logging
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen

from PIL import Image

from .config import OcrEngine, ParserConfig, validate_loopback_origin
from .local_ocr import OcrPageResult, OcrRegion

LAYOUT_MODEL_ID = "PaddlePaddle/PP-DocLayoutV3_safetensors"
LAYOUT_MODEL_REVISION = "97d101e6db2642e162a1d05392d1b0231c91033e"
LAYOUT_THRESHOLD = 0.3
MAX_REGIONS_PER_PAGE = 256
_CONTROL_TOKEN = re.compile(r"<\|(?:im_end|md_continue|endofsentence)\|>")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LayoutRegion:
    index: int
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class OcrProgressEvent:
    image_path: Path
    stage: str
    current: int
    total: int
    message: str


class LayoutDetector(Protocol):
    def detect(self, image_path: Path) -> list[LayoutRegion]: ...


class RegionRecognizer(Protocol):
    name: str

    def recognize(
        self,
        image_bytes: bytes,
        region_type: str,
        *,
        region_area: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> str: ...


def clean_ocr_output(value: str) -> str:
    value = _CONTROL_TOKEN.sub("", value).strip()
    if value.startswith("```") and value.endswith("```"):
        value = re.sub(r"^```(?:markdown|md|html|text)?\s*", "", value, count=1)
        value = re.sub(r"\s*```$", "", value, count=1)
    return value.strip()


def region_prompt(region_type: str) -> str:
    kind = region_type.casefold()
    if "table" in kind:
        return "Table Recognition:"
    if "formula" in kind:
        return "Formula Recognition:"
    if kind in {"chart", "image", "figure", "seal"}:
        return "Figure Recognition:"
    return "Text Recognition:"


class GlmVllmRecognizer:
    name = "glm-ocr-vllm"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 900.0,
        opener=urlopen,
    ) -> None:
        self.base_url = validate_loopback_origin(base_url, name="glm_vllm_base_url")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def recognize(
        self,
        image_bytes: bytes,
        region_type: str,
        *,
        region_area: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> str:
        del region_area
        image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
        payload = {
            "model": "glm-ocr",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": region_prompt(region_type)},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0,
            "max_tokens": 8192,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener(
            request, timeout=timeout_seconds or self.timeout_seconds
        ) as response:
            result = json.load(response)
        choices = result.get("choices", [])
        content = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(content, str):
            raise RuntimeError(  # noqa: TRY004 - invalid provider response, not caller input
                "GLM-OCR vLLM returned no recognized text"
            )
        return clean_ocr_output(content)


def _overlap_over_smaller(first: LayoutRegion, second: LayoutRegion) -> float:
    left = max(first.bbox[0], second.bbox[0])
    top = max(first.bbox[1], second.bbox[1])
    right = min(first.bbox[2], second.bbox[2])
    bottom = min(first.bbox[3], second.bbox[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = (first.bbox[2] - first.bbox[0]) * (first.bbox[3] - first.bbox[1])
    second_area = (second.bbox[2] - second.bbox[0]) * (
        second.bbox[3] - second.bbox[1]
    )
    smaller = min(first_area, second_area)
    return intersection / smaller if smaller > 0 else 0.0


def deduplicate_regions(regions: list[LayoutRegion]) -> list[LayoutRegion]:
    """Remove near-identical detections without changing detector order."""

    output: list[LayoutRegion] = []
    for region in regions:
        duplicate = next(
            (
                position
                for position, existing in enumerate(output)
                if _overlap_over_smaller(region, existing) >= 0.9
            ),
            None,
        )
        if duplicate is None:
            output.append(region)
        elif region.confidence > output[duplicate].confidence:
            previous = output[duplicate]
            output[duplicate] = LayoutRegion(
                previous.index,
                region.label,
                region.confidence,
                region.bbox,
            )
    return output


class PPDocLayoutV3Detector:
    """Process-wide CPU PP-DocLayoutV3 detector backed by Transformers."""

    def __init__(
        self,
        *,
        threshold: float = LAYOUT_THRESHOLD,
        local_files_only: bool = True,
    ) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        self._torch = torch
        self._processor = AutoImageProcessor.from_pretrained(
            LAYOUT_MODEL_ID,
            revision=LAYOUT_MODEL_REVISION,
            local_files_only=local_files_only,
        )
        self._model = AutoModelForObjectDetection.from_pretrained(
            LAYOUT_MODEL_ID,
            revision=LAYOUT_MODEL_REVISION,
            local_files_only=local_files_only,
        ).to("cpu").eval()
        self._threshold = threshold
        self._lock = threading.Lock()

    def detect(self, image_path: Path) -> list[LayoutRegion]:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        width, height = image.size
        inputs = self._processor(images=[image], return_tensors="pt")
        with self._lock, self._torch.inference_mode():
            outputs = self._model(**inputs)
        result = self._processor.post_process_object_detection(
            outputs,
            threshold=self._threshold,
            target_sizes=self._torch.tensor([[height, width]]),
        )[0]
        labels = result["labels"].tolist()
        scores = result["scores"].tolist()
        boxes = result["boxes"].tolist()
        id_to_label = self._model.config.id2label
        regions = deduplicate_regions(
            [
                LayoutRegion(
                    index=index,
                    label=str(id_to_label.get(int(label), label)),
                    confidence=float(score),
                    bbox=(
                        max(0.0, min(1.0, float(box[0]) / width)),
                        max(0.0, min(1.0, float(box[1]) / height)),
                        max(0.0, min(1.0, float(box[2]) / width)),
                        max(0.0, min(1.0, float(box[3]) / height)),
                    ),
                )
                for index, (label, score, box) in enumerate(
                    zip(labels, scores, boxes, strict=True)
                )
                if box[2] > box[0] and box[3] > box[1]
            ]
        )
        if len(regions) > MAX_REGIONS_PER_PAGE:
            raise RuntimeError(
                f"PP-DocLayoutV3 returned {len(regions)} regions; "
                f"maximum is {MAX_REGIONS_PER_PAGE}"
            )
        return regions


@lru_cache(maxsize=4)
def get_layout_detector(
    threshold: float = LAYOUT_THRESHOLD,
) -> PPDocLayoutV3Detector:
    return PPDocLayoutV3Detector(threshold=threshold)


def _snapshot_layout_model(*, local_files_only: bool) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=LAYOUT_MODEL_ID,
        revision=LAYOUT_MODEL_REVISION,
        local_files_only=local_files_only,
    )


def ensure_layout_model() -> None:
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        _snapshot_layout_model(local_files_only=True)
    except LocalEntryNotFoundError:
        _snapshot_layout_model(local_files_only=False)


def crop_region(
    image: Image.Image,
    region: LayoutRegion,
    *,
    padding: float = 0.05,
) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = region.bbox
    region_width, region_height = right - left, bottom - top
    epsilon = 1e-9
    pixel_box = (
        max(0, math.floor((left - region_width * padding) * width + epsilon)),
        max(0, math.floor((top - region_height * padding) * height + epsilon)),
        min(width, math.ceil((right + region_width * padding) * width - epsilon)),
        min(height, math.ceil((bottom + region_height * padding) * height - epsilon)),
    )
    crop = image.crop(pixel_box)
    if (
        region.label.casefold() in {"aside_text", "vertical_text"}
        and crop.height > crop.width * 2
    ):
        crop = crop.rotate(-90, expand=True)
    return crop


def _crop_png(image: Image.Image, region: LayoutRegion) -> bytes:
    crop = crop_region(image, region)
    output = BytesIO()
    crop.save(output, format="PNG")
    return output.getvalue()


class GroundedOcrRuntime:
    def __init__(
        self,
        detector: LayoutDetector,
        recognizer: RegionRecognizer,
        *,
        page_timeout_seconds: float | None = None,
    ) -> None:
        self.detector = detector
        self.recognizer = recognizer
        self.page_timeout_seconds = page_timeout_seconds

    def parse(self, image_path: Path) -> list[OcrRegion]:
        return next(self.parse_many([image_path])).regions

    def parse_many(
        self,
        image_paths: list[Path],
        progress_callback: Callable[[OcrProgressEvent], None] | None = None,
    ):
        for image_path in image_paths:
            page_started = time.perf_counter()
            deadline = (
                page_started + self.page_timeout_seconds
                if self.page_timeout_seconds is not None
                else None
            )
            try:
                logger.info(
                    "PP-DocLayoutV3 detection started: image=%s revision=%s threshold=%.2f",
                    image_path.name,
                    LAYOUT_MODEL_REVISION,
                    getattr(self.detector, "_threshold", LAYOUT_THRESHOLD),
                )
                detected = self.detector.detect(image_path)
                logger.info(
                    "PP-DocLayoutV3 detection completed: image=%s regions=%d elapsed_ms=%.1f",
                    image_path.name,
                    len(detected),
                    (time.perf_counter() - page_started) * 1000,
                )
                if progress_callback is not None:
                    progress_callback(
                        OcrProgressEvent(
                            image_path,
                            "layout",
                            1,
                            1,
                            f"Detected {len(detected)} regions",
                        )
                    )
                with Image.open(image_path) as source:
                    image = source.convert("RGB")
                regions: list[OcrRegion] = []
                for position, item in enumerate(detected, start=1):
                    if deadline is not None:
                        remaining = deadline - time.perf_counter()
                        if remaining <= 0:
                            raise TimeoutError(
                                f"Ollama OCR page exceeded {self.page_timeout_seconds:g} seconds"
                            )
                    else:
                        remaining = None
                    if progress_callback is not None:
                        progress_callback(
                            OcrProgressEvent(
                                image_path,
                                "recognize",
                                position - 1,
                                len(detected),
                                f"Recognizing region {position}/{len(detected)} ({item.label})",
                            )
                        )
                    logger.info(
                        "OCR region started: image=%s region=%d/%d index=%d label=%s "
                        "confidence=%.4f box=%s",
                        image_path.name,
                        position,
                        len(detected),
                        item.index,
                        item.label,
                        item.confidence,
                        item.bbox,
                    )
                    region_started = time.perf_counter()
                    failed = False
                    try:
                        content = self.recognizer.recognize(
                            _crop_png(image, item),
                            item.label,
                            region_area=(item.bbox[2] - item.bbox[0])
                            * (item.bbox[3] - item.bbox[1]),
                            timeout_seconds=(
                                min(
                                    float(getattr(self.recognizer, "timeout_seconds", remaining)),
                                    remaining,
                                )
                                if remaining is not None
                                else None
                            ),
                        ).strip()
                        failed = not bool(content)
                    except Exception:
                        logger.exception(
                            "OCR region failed: image=%s region=%d/%d index=%d label=%s",
                            image_path.name,
                            position,
                            len(detected),
                            item.index,
                            item.label,
                        )
                        if getattr(self.recognizer, "fail_fast", False):
                            raise
                        content = ""
                        failed = True
                    logger.info(
                        "OCR region completed: image=%s region=%d/%d index=%d label=%s "
                        "elapsed_ms=%.1f output_characters=%d failed=%s",
                        image_path.name,
                        position,
                        len(detected),
                        item.index,
                        item.label,
                        (time.perf_counter() - region_started) * 1000,
                        len(content),
                        failed,
                    )
                    regions.append(
                        OcrRegion(
                            index=item.index,
                            label=item.label,
                            content=content,
                            bbox=item.bbox,
                            confidence=item.confidence,
                            recognition_attempted=True,
                            recognition_failed=failed,
                        )
                    )
                    if progress_callback is not None:
                        progress_callback(
                            OcrProgressEvent(
                                image_path,
                                "recognize",
                                position,
                                len(detected),
                                f"Recognized region {position}/{len(detected)} ({item.label})",
                            )
                        )
                yield OcrPageResult(image_path=image_path, regions=regions)
            except Exception as exc:
                logger.exception(
                    "Grounded OCR page failed: image=%s elapsed_ms=%.1f",
                    image_path.name,
                    (time.perf_counter() - page_started) * 1000,
                )
                yield OcrPageResult(
                    image_path=image_path,
                    regions=[],
                    error=f"{type(exc).__name__}: {exc}",
                )


@lru_cache(maxsize=8)
def _cached_grounded_runtime(
    engine: OcrEngine,
    glm_vllm_base_url: str,
    ollama_model: str,
    timeout_seconds: float,
    layout_threshold: float,
) -> GroundedOcrRuntime:
    detector = get_layout_detector(layout_threshold)
    if engine is OcrEngine.GLM_OCR:
        recognizer: RegionRecognizer = GlmVllmRecognizer(
            glm_vllm_base_url,
            timeout_seconds=timeout_seconds,
        )
    elif engine is OcrEngine.OLLAMA:
        from .ollama_runtime import (
            OLLAMA_PAGE_TIMEOUT_SECONDS,
            OllamaOcrModel,
            OllamaRegionRecognizer,
        )

        recognizer = OllamaRegionRecognizer(
            OllamaOcrModel(ollama_model),
            timeout_seconds=timeout_seconds,
        )
    else:
        raise ValueError(f"Grounded OCR does not support {engine.value}")
    return GroundedOcrRuntime(
        detector,
        recognizer,
        page_timeout_seconds=(
            OLLAMA_PAGE_TIMEOUT_SECONDS if engine is OcrEngine.OLLAMA else None
        ),
    )


def get_grounded_ocr_runtime(config: ParserConfig) -> GroundedOcrRuntime:
    return _cached_grounded_runtime(
        config.ocr_engine,
        config.glm_vllm_base_url,
        config.ollama_model,
        config.grounded_ocr_timeout_seconds,
        config.layout_detection_threshold,
    )
