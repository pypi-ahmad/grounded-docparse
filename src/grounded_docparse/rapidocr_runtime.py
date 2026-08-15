from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

from .local_ocr import OcrRegion


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


@lru_cache(maxsize=1)
def get_rapidocr_runtime() -> RapidOcrCropRuntime:
    return RapidOcrCropRuntime()
