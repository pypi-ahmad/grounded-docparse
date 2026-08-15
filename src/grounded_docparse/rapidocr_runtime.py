from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

from .docling_native import make_docling_rapidocr_converter
from .local_ocr import OcrPageResult, OcrRegion


class RapidOcrCropRuntime:
    def __init__(self, engine=None) -> None:
        if engine is None:
            from rapidocr import RapidOCR

            engine = RapidOCR()
        self.engine = engine

    def parse(self, image_path: Path) -> list[OcrRegion]:
        result = self.engine(image_path)
        texts = tuple(result.txts or ())
        scores = tuple(result.scores or ())
        boxes = result.boxes
        with Image.open(image_path) as image:
            width, height = image.size
        regions: list[OcrRegion] = []
        for index, text in enumerate(texts):
            content = str(text).strip()
            raw_box = boxes[index] if boxes is not None and index < len(boxes) else None
            if raw_box is None:
                polygon = ()
                bbox = (0.0, 0.0, 1.0, 1.0)
            else:
                polygon = tuple(
                    (float(point[0]) / width, float(point[1]) / height)
                    for point in raw_box
                )
                xs = [point[0] for point in polygon]
                ys = [point[1] for point in polygon]
                bbox = (min(xs), min(ys), max(xs), max(ys))
            regions.append(
                OcrRegion(
                    index=index,
                    label="text",
                    content=content,
                    bbox=bbox,
                    polygon=polygon,
                    confidence=float(scores[index]) if index < len(scores) else None,
                    recognition_attempted=True,
                    recognition_failed=not bool(content),
                )
            )
        return regions


class DoclingRapidOcrRuntime:
    def __init__(self, converter=None) -> None:
        self.converter = converter or make_docling_rapidocr_converter()

    @staticmethod
    def _bbox(value, size) -> tuple[float, float, float, float]:
        normalized = value.normalized(size).to_top_left_origin(1.0)
        return (
            round(min(float(normalized.l), float(normalized.r)), 8),
            round(min(float(normalized.t), float(normalized.b)), 8),
            round(max(float(normalized.l), float(normalized.r)), 8),
            round(max(float(normalized.t), float(normalized.b)), 8),
        )

    @classmethod
    def _confidence(cls, parsed_page, item_bbox, size) -> float | None:
        candidates = tuple(getattr(parsed_page, "textline_cells", ()) or ())
        if not candidates:
            candidates = tuple(getattr(parsed_page, "word_cells", ()) or ())
        weighted = 0.0
        weight = 0
        x0, y0, x1, y1 = item_bbox
        for cell in candidates:
            if not getattr(cell, "from_ocr", False):
                continue
            confidence = getattr(cell, "confidence", None)
            rect = getattr(cell, "rect", None)
            if confidence is None or rect is None:
                continue
            cell_bbox = cls._bbox(rect.to_bounding_box(), size)
            center_x = (cell_bbox[0] + cell_bbox[2]) / 2
            center_y = (cell_bbox[1] + cell_bbox[3]) / 2
            if not (x0 <= center_x <= x1 and y0 <= center_y <= y1):
                continue
            cell_weight = max(1, len(str(getattr(cell, "text", ""))))
            weighted += float(confidence) * cell_weight
            weight += cell_weight
        return round(weighted / weight, 8) if weight else None

    def parse_many(self, image_paths: list[Path]):
        for image_path in image_paths:
            try:
                conversion = self.converter.convert(image_path)
                document = conversion.document
                parsed_pages = tuple(getattr(conversion, "pages", ()) or ())
                regions: list[OcrRegion] = []
                for item, _level in document.iterate_items(with_groups=False):
                    provenance = tuple(getattr(item, "prov", ()) or ())
                    if not provenance:
                        continue
                    prov = provenance[0]
                    page = document.pages[prov.page_no]
                    bbox = self._bbox(prov.bbox, page.size)
                    label = str(getattr(getattr(item, "label", None), "value", "text"))
                    text = getattr(item, "text", None)
                    if label == "table" and hasattr(item, "export_to_html"):
                        content = item.export_to_html(document, add_caption=False)
                    else:
                        content = str(text or "").strip()
                    recognition_attempted = label == "table" or text is not None
                    parsed_page = (
                        getattr(parsed_pages[prov.page_no - 1], "parsed_page", None)
                        if 0 < prov.page_no <= len(parsed_pages)
                        else None
                    )
                    regions.append(
                        OcrRegion(
                            index=len(regions),
                            label=label,
                            content=content,
                            bbox=bbox,
                            confidence=(
                                self._confidence(parsed_page, bbox, page.size)
                                if parsed_page is not None
                                else None
                            ),
                            recognition_attempted=recognition_attempted,
                            recognition_failed=(
                                recognition_attempted and not bool(content)
                            ),
                        )
                    )
                yield OcrPageResult(image_path=image_path, regions=regions)
            except Exception as exc:  # noqa: BLE001 - isolate page-level OCR failures
                yield OcrPageResult(
                    image_path=image_path,
                    regions=[],
                    error=f"{type(exc).__name__}: {exc}",
                )


@lru_cache(maxsize=1)
def get_rapidocr_runtime() -> RapidOcrCropRuntime:
    return RapidOcrCropRuntime()


@lru_cache(maxsize=1)
def get_docling_rapidocr_runtime() -> DoclingRapidOcrRuntime:
    return DoclingRapidOcrRuntime()
