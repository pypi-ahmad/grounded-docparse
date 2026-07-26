from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageOps, ImageSequence

from .models import BoundingBox

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass(slots=True)
class TextBlock:
    text: str
    bbox: BoundingBox
    source_bbox: BoundingBox
    font_size: float
    font: str


@dataclass(slots=True)
class PageEvidence:
    number: int
    width: float
    height: float
    dpi: int
    image_path: Path
    ocr_image_path: Path
    scanned: bool
    text_blocks: list[TextBlock] = field(default_factory=list)
    links: list[dict[str, object]] = field(default_factory=list)

    @property
    def digital_text(self) -> str:
        return "\n".join(block.text for block in self.text_blocks if block.text.strip())


@dataclass(slots=True)
class IngestedDocument:
    name: str
    sha256: str
    source_path: Path
    pages: list[PageEvidence]


def _normalized_bbox(
    bbox: tuple[float, float, float, float], width: float, height: float
) -> BoundingBox:
    x0, y0, x1, y1 = bbox
    return BoundingBox(
        x0=max(0, min(1, x0 / width)),
        y0=max(0, min(1, y0 / height)),
        x1=max(0, min(1, x1 / width)),
        y1=max(0, min(1, y1 / height)),
    )


def _deskew_and_enhance(source: Path, destination: Path) -> None:
    image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Cannot read rendered page: {source.name}")

    inverted = cv2.bitwise_not(image)
    points = np.column_stack(np.where(inverted > 32))
    angle = 0.0
    if len(points) > 100:
        raw_angle = cv2.minAreaRect(points)[-1]
        angle = -(90 + raw_angle) if raw_angle < -45 else -raw_angle
        if abs(angle) > 7:
            angle = 0.0

    if abs(angle) >= 0.15:
        height, width = image.shape
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        image = cv2.warpAffine(
            image,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

    denoised = cv2.fastNlMeansDenoising(image, None, 8, 7, 21)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
    if not cv2.imwrite(str(destination), enhanced):
        raise OSError(f"Cannot write enhanced page: {destination.name}")


def _validate_input(data: bytes, filename: str, max_bytes: int) -> str:
    if not data:
        raise ValueError("Uploaded document is empty")
    if len(data) > max_bytes:
        raise ValueError(f"Uploaded document exceeds {max_bytes // (1024 * 1024)} MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix or 'missing extension'}")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("File extension is PDF but content is not a PDF")
    if suffix != ".pdf":
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except Exception as exc:
            raise ValueError("Image content is invalid or unsupported") from exc
    return suffix


def ingest_document(
    data: bytes,
    filename: str,
    workdir: Path,
    *,
    dpi: int,
    max_bytes: int,
    max_pages: int = 500,
    max_page_pixels: int = 20_000_000,
) -> IngestedDocument:
    suffix = _validate_input(data, filename, max_bytes)
    digest = hashlib.sha256(data).hexdigest()
    source_path = workdir / f"source{suffix}"
    source_path.write_bytes(data)
    pages_dir = workdir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    pages = (
        _ingest_pdf(data, pages_dir, dpi, max_pages, max_page_pixels)
        if suffix == ".pdf"
        else _ingest_image(data, pages_dir, dpi, max_pages, max_page_pixels)
    )
    if not pages:
        raise ValueError("Document contains no readable pages")
    return IngestedDocument(filename, digest, source_path, pages)


def _ingest_pdf(
    data: bytes, pages_dir: Path, dpi: int, max_pages: int, max_page_pixels: int
) -> list[PageEvidence]:
    pages: list[PageEvidence] = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if document.page_count > max_pages:
            raise ValueError(f"Document exceeds page limit of {max_pages}")
        scale = dpi / 72
        matrix = pymupdf.Matrix(scale, scale)
        for index, page in enumerate(document):
            page_number = index + 1
            width, height = float(page.rect.width), float(page.rect.height)
            if int(width * scale) * int(height * scale) > max_page_pixels:
                raise ValueError(f"Page {page_number} exceeds rendered pixel limit")
            image_path = pages_dir / f"page-{page_number:04d}.png"
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_path.write_bytes(pixmap.tobytes("png"))

            blocks: list[TextBlock] = []
            text_dict = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
            for block in text_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                spans = [
                    span
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                    if span.get("text", "").strip()
                ]
                if not spans:
                    continue
                text = " ".join(str(span["text"]).strip() for span in spans)
                raw_bbox = tuple(float(value) for value in block["bbox"])
                blocks.append(
                    TextBlock(
                        text=text,
                        bbox=_normalized_bbox(raw_bbox, width, height),
                        source_bbox=BoundingBox(
                            x0=raw_bbox[0],
                            y0=raw_bbox[1],
                            x1=raw_bbox[2],
                            y1=raw_bbox[3],
                            unit="pdf_points",
                        ),
                        font_size=max(float(span.get("size", 0)) for span in spans),
                        font=str(spans[0].get("font", "")),
                    )
                )

            char_count = sum(len(block.text.strip()) for block in blocks)
            # A short title page can still contain a valid native text layer.
            # Treat only effectively empty layers as scans; Paddle still analyzes
            # every page, so this flag only controls OCR preprocessing/verification.
            scanned = char_count < 20
            ocr_path = pages_dir / f"page-{page_number:04d}-enhanced.png"
            if scanned:
                _deskew_and_enhance(image_path, ocr_path)
            else:
                ocr_path = image_path
            pages.append(
                PageEvidence(
                    number=page_number,
                    width=width,
                    height=height,
                    dpi=dpi,
                    image_path=image_path,
                    ocr_image_path=ocr_path,
                    scanned=scanned,
                    text_blocks=blocks,
                    links=page.get_links(),
                )
            )
    return pages


def _ingest_image(
    data: bytes, pages_dir: Path, dpi: int, max_pages: int, max_page_pixels: int
) -> list[PageEvidence]:
    pages: list[PageEvidence] = []
    with Image.open(io.BytesIO(data)) as image:
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            page_number = index + 1
            if page_number > max_pages:
                raise ValueError(f"Document exceeds page limit of {max_pages}")
            if frame.width * frame.height > max_page_pixels:
                raise ValueError(f"Page {page_number} exceeds pixel limit")
            rgb = ImageOps.exif_transpose(frame).convert("RGB")
            image_path = pages_dir / f"page-{page_number:04d}.png"
            rgb.save(image_path, "PNG")
            ocr_path = pages_dir / f"page-{page_number:04d}-enhanced.png"
            _deskew_and_enhance(image_path, ocr_path)
            pages.append(
                PageEvidence(
                    number=page_number,
                    width=float(rgb.width),
                    height=float(rgb.height),
                    dpi=dpi,
                    image_path=image_path,
                    ocr_image_path=ocr_path,
                    scanned=True,
                )
            )
    return pages
