from __future__ import annotations

import base64
import json
import threading
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

from .config import validate_paddleocr_service_url
from .ingest import PageEvidence
from .local_ocr import OcrPageResult, OcrRegion


def _find_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        blocks = value.get("parsing_res_list")
        if isinstance(blocks, list):
            return [item for item in blocks if isinstance(item, dict)]
        for child in value.values():
            found = _find_blocks(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_blocks(child)
            if found:
                return found
    return []


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _bbox(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
    value = item.get("block_bbox", item.get("bbox"))
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x0, y0, x1, y1 = (float(part) for part in value[:4])
    except (TypeError, ValueError):
        return None
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _normalized_point(
    point: Any, width: float, height: float
) -> tuple[float, float] | None:
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, x / width)), max(0.0, min(1.0, y / height))


def paddle_regions(result: Any, *, width: float, height: float) -> list[OcrRegion]:
    width, height = max(width, 1.0), max(height, 1.0)
    output: list[OcrRegion] = []
    for position, item in enumerate(_find_blocks(result)):
        box = _bbox(item)
        if box is None:
            continue
        x0, y0, x1, y1 = box
        polygon_value = item.get("block_polygon", item.get("polygon", []))
        polygon = tuple(
            point
            for raw_point in polygon_value
            if (point := _normalized_point(raw_point, width, height)) is not None
        ) if isinstance(polygon_value, list) else ()
        order = item.get("block_order", item.get("block_id", position))
        try:
            index = int(order)
        except (TypeError, ValueError):
            index = position
        score = item.get("score", item.get("confidence"))
        output.append(
            OcrRegion(
                index=index,
                label=str(item.get("block_label", item.get("label", "unknown"))),
                content=str(
                    item.get("block_content", item.get("content", item.get("text", "")))
                    or ""
                ),
                bbox=(
                    max(0.0, min(1.0, x0 / width)),
                    max(0.0, min(1.0, y0 / height)),
                    max(0.0, min(1.0, x1 / width)),
                    max(0.0, min(1.0, y1 / height)),
                ),
                polygon=polygon,
                confidence=(
                    _number(score, 0.0) if isinstance(score, (int, float)) else None
                ),
                recognition_attempted=True,
            )
        )
    return sorted(output, key=lambda region: region.index)


class PaddleOcrRuntime:
    """Client for the official PaddleOCR-VL full document-parsing service."""

    def __init__(self, service_url: str, timeout_seconds: float = 900.0) -> None:
        self.service_url = validate_paddleocr_service_url(service_url)
        self.timeout_seconds = timeout_seconds
        self._prepared: dict[Path, OcrPageResult] = {}
        self._lock = threading.Lock()

    def _request_pages(
        self, payload: dict[str, Any], *, expected_count: int
    ) -> list[dict[str, Any]]:
        request = Request(
            f"{self.service_url}/layout-parsing",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"PaddleOCR-VL service request failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(body, dict) or body.get("errorCode", 0) != 0:
            message = (
                body.get("errorMsg", "invalid service response")
                if isinstance(body, dict)
                else "invalid service response"
            )
            raise RuntimeError(f"PaddleOCR-VL service failed: {message}")
        result = body.get("result")
        page_results = (
            result.get("layoutParsingResults") if isinstance(result, dict) else None
        )
        if not isinstance(page_results, list) or len(page_results) != expected_count:
            count = len(page_results) if isinstance(page_results, list) else 0
            raise RuntimeError(
                "PaddleOCR-VL returned an unexpected page count: "
                f"expected {expected_count}, received {count}"
            )
        if any(not isinstance(item, dict) for item in page_results):
            raise RuntimeError("PaddleOCR-VL returned an invalid page result")
        return page_results

    def parse_document(
        self, source_path: Path, pages: list[PageEvidence]
    ) -> list[OcrPageResult]:
        payload = {
            "file": base64.b64encode(source_path.read_bytes()).decode("ascii"),
            "fileType": 0 if source_path.suffix.casefold() == ".pdf" else 1,
            "useLayoutDetection": True,
            "layoutShapeMode": "auto",
            "formatBlockContent": True,
        }
        page_results = self._request_pages(payload, expected_count=len(pages))
        parsed = [
            OcrPageResult(
                page.image_path,
                paddle_regions(
                    page_result.get("prunedResult", page_result),
                    width=page.render_width_pixels,
                    height=page.render_height_pixels,
                ),
            )
            for page, page_result in zip(pages, page_results, strict=True)
        ]
        with self._lock:
            self._prepared = {item.image_path.resolve(): item for item in parsed}
        return parsed

    def parse_recovery_image(self, image_path: Path) -> OcrPageResult:
        """Parse one rendered page without replacing prepared first-pass results."""

        with Image.open(image_path) as image:
            width, height = image.size
        payload = {
            "file": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            "fileType": 1,
            "useLayoutDetection": True,
            "layoutShapeMode": "auto",
            "formatBlockContent": True,
            "temperature": 0.0,
            "topP": 1.0,
        }
        page_result = self._request_pages(payload, expected_count=1)[0]
        return OcrPageResult(
            image_path,
            paddle_regions(
                page_result.get("prunedResult", page_result),
                width=width,
                height=height,
            ),
        )

    def parse_many(self, image_paths: list[Path]):
        with self._lock:
            prepared = dict(self._prepared)
        for image_path in image_paths:
            result = prepared.get(image_path.resolve())
            if result is None:
                raise RuntimeError(
                    "PaddleOCR-VL document was not prepared before page analysis"
                )
            yield result

    def parse(self, image_path: Path) -> list[OcrRegion]:
        return next(self.parse_many([image_path])).regions


_instances: dict[tuple[str, float], PaddleOcrRuntime] = {}
_instances_lock = threading.Lock()


def get_paddleocr_runtime(
    service_url: str, timeout_seconds: float = 900.0
) -> PaddleOcrRuntime:
    key = (service_url.rstrip("/"), timeout_seconds)
    with _instances_lock:
        if key not in _instances:
            _instances[key] = PaddleOcrRuntime(*key)
        return _instances[key]
