from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GlmRegion:
    index: int
    label: str
    content: str
    bbox: tuple[float, float, float, float]
    polygon: tuple[tuple[float, float], ...] = ()
    confidence: float | None = None
    recognition_attempted: bool = False
    recognition_failed: bool = False


@dataclass(frozen=True, slots=True)
class GlmPageResult:
    image_path: Path
    regions: list[GlmRegion]
    error: str | None = None


def _objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, list):
        return [item for value_item in value for item in _objects(value_item)]
    if not isinstance(value, dict):
        return []
    found = (
        [value]
        if any(key in value for key in ("bbox_2d", "bbox", "coordinate"))
        else []
    )
    for child in value.values():
        if isinstance(child, (dict, list)):
            found.extend(_objects(child))
    return found


def _bbox(item: dict[str, Any]) -> tuple[float, float, float, float] | None:
    value = item.get("bbox_2d", item.get("bbox", item.get("coordinate")))
    if isinstance(value, dict):
        value = [value.get(key) for key in ("x0", "y0", "x1", "y1")]
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return tuple(float(part) for part in value[:4])  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _regions(result: Any) -> list[GlmRegion]:
    formatted = _objects(getattr(result, "json_result", result))
    raw = _objects(getattr(result, "raw_json_result", {}))
    raw_by_index = {
        int(item.get("index", index)): item for index, item in enumerate(raw)
    }
    output: list[GlmRegion] = []
    for position, item in enumerate(formatted):
        box = _bbox(item)
        if box is None:
            continue
        index = int(item.get("index", position))
        raw_item = raw_by_index.get(index, {})
        task_type = str(raw_item.get("task_type", item.get("task_type", ""))).casefold()
        recognition_attempted = bool(task_type) and task_type not in {"skip", "abandon"}
        recognition_failed = (
            recognition_attempted and raw_item.get("content", item.get("content")) is None
        )
        score = raw_item.get("score", raw_item.get("confidence"))
        polygon_value = raw_item.get("polygon", item.get("polygon", []))
        polygon = (
            tuple(
                (float(point[0]), float(point[1]))
                for point in polygon_value
                if isinstance(point, (list, tuple)) and len(point) >= 2
            )
            if isinstance(polygon_value, list)
            else ()
        )
        output.append(
            GlmRegion(
                index=index,
                label=str(item.get("native_label", item.get("label", "unknown"))),
                content=str(item.get("content", item.get("text", "")) or ""),
                bbox=box,
                polygon=polygon,
                confidence=float(score) if isinstance(score, (int, float)) else None,
                recognition_attempted=recognition_attempted,
                recognition_failed=recognition_failed,
            )
        )
    return sorted(output, key=lambda region: region.index)


class GlmOcrRuntime:
    """One process-wide, serialized GLM-OCR instance; model loading is expensive."""

    def __init__(self, config_path: str, layout_device: str) -> None:
        try:
            from glmocr import GlmOcr
        except ImportError as exc:
            raise RuntimeError(
                "glmocr is unavailable; run scripts/wsl/setup-glmocr.sh"
            ) from exc
        self._parser = GlmOcr(config_path=config_path, layout_device=layout_device)
        self._lock = threading.Lock()

    def parse(self, image_path: Path) -> list[GlmRegion]:
        with self._lock:
            return _regions(self._parser.parse(str(image_path)))

    def parse_many(self, image_paths: list[Path]):
        expected = {path.resolve(): path for path in image_paths}
        seen: set[Path] = set()
        with self._lock:
            try:
                results = self._parser.parse(
                    [str(path) for path in image_paths],
                    stream=True,
                    preserve_order=False,
                    save_layout_visualization=False,
                )
                for result in results:
                    originals = getattr(result, "original_images", ())
                    raw_path = originals[0] if originals else None
                    if raw_path is None:
                        continue
                    resolved = Path(str(raw_path).removeprefix("file://")).resolve()
                    if resolved not in expected or resolved in seen:
                        continue
                    seen.add(resolved)
                    error = getattr(result, "_error", None)
                    yield GlmPageResult(
                        image_path=expected[resolved],
                        regions=[] if error else _regions(result),
                        error=str(error) if error else None,
                    )
            except Exception as exc:  # noqa: BLE001 - SDK failures become page-level evidence
                message = f"{type(exc).__name__}: {exc}"
                for resolved, original in expected.items():
                    if resolved not in seen:
                        seen.add(resolved)
                        yield GlmPageResult(original, [], message)
                return
        for resolved, original in expected.items():
            if resolved not in seen:
                yield GlmPageResult(original, [], "GLM-OCR returned no result for page")


_instances: dict[tuple[str, str], GlmOcrRuntime] = {}
_instances_lock = threading.Lock()

GLM_FORM_RECOVERY_MAX_PIXELS = 4_014_080


def _form_recovery_config_path(config_path: str) -> Path:
    """Materialize a high-resolution variant without changing the primary config."""

    source = Path(config_path).resolve()
    content = source.read_text(encoding="utf-8")
    image_pattern = re.compile(r"(?m)^(\s*image_format:\s*)\S+(\s*)$")
    pixels_pattern = re.compile(r"(?m)^(\s*max_pixels:\s*)\d+(\s*)$")
    recovered, image_changes = image_pattern.subn(r"\g<1>PNG\g<2>", content, count=1)
    recovered, pixel_changes = pixels_pattern.subn(
        rf"\g<1>{GLM_FORM_RECOVERY_MAX_PIXELS}\g<2>", recovered, count=1
    )
    if image_changes != 1 or pixel_changes != 1:
        raise RuntimeError(
            "GLM-OCR config must contain one image_format and one max_pixels setting"
        )
    digest = hashlib.sha256(f"{source}\0{recovered}".encode()).hexdigest()[:16]
    target_dir = Path(tempfile.gettempdir()) / "grounded-docparse"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"glmocr-form-recovery-{digest}.yaml"
    if not target.exists() or target.read_text(encoding="utf-8") != recovered:
        temporary = target.with_suffix(".tmp")
        temporary.write_text(recovered, encoding="utf-8", newline="\n")
        temporary.replace(target)
    return target


def get_glmocr_runtime(config_path: str, layout_device: str) -> GlmOcrRuntime:
    key = (str(Path(config_path).resolve()), layout_device)
    with _instances_lock:
        if key not in _instances:
            _instances[key] = GlmOcrRuntime(*key)
        return _instances[key]


def get_glmocr_form_recovery_runtime(
    config_path: str, layout_device: str
) -> GlmOcrRuntime:
    return get_glmocr_runtime(
        str(_form_recovery_config_path(config_path)), layout_device
    )


def glmocr_version() -> str | None:
    try:
        return version("glmocr")
    except PackageNotFoundError:
        return None
