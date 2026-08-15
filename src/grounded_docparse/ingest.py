from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence

from .models import BoundingBox

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass(slots=True)
class PageEvidence:
    number: int
    width: float
    height: float
    dpi: int
    image_path: Path
    render_width_pixels: int = 1
    render_height_pixels: int = 1
    effective_dpi: float | None = None
    source_width: float = 1
    source_height: float = 1
    source_unit: str = "pixels"
    source_rotation_degrees: int = 0
    scanned: bool = True


@dataclass(slots=True)
class IngestedDocument:
    name: str
    sha256: str
    source_path: Path
    pages: list[PageEvidence]
    total_pages: int = 0


def render_region_crop(
    document: IngestedDocument,
    page: PageEvidence,
    bbox: BoundingBox,
    output: Path,
    *,
    dpi: int,
    padding: float,
) -> Path:
    if bbox.unit != "normalized":
        raise ValueError("region crop requires normalized coordinates")
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    if not 0 <= padding <= 0.5:
        raise ValueError("padding must be between 0 and 0.5")
    pad_x = (bbox.x1 - bbox.x0) * padding
    pad_y = (bbox.y1 - bbox.y0) * padding
    x0 = max(0.0, bbox.x0 - pad_x)
    y0 = max(0.0, bbox.y0 - pad_y)
    x1 = min(1.0, bbox.x1 + pad_x)
    y1 = min(1.0, bbox.y1 + pad_y)
    output.parent.mkdir(parents=True, exist_ok=True)

    if document.source_path.suffix.casefold() == ".pdf":
        source = pymupdf.open(document.source_path)
        try:
            source_page = source[page.number - 1]
            rect = source_page.rect
            clip = pymupdf.Rect(
                rect.x0 + x0 * rect.width,
                rect.y0 + y0 * rect.height,
                rect.x0 + x1 * rect.width,
                rect.y0 + y1 * rect.height,
            )
            pixmap = source_page.get_pixmap(dpi=dpi, clip=clip, alpha=False)
            pixmap.save(output)
        finally:
            source.close()
        return output

    with Image.open(document.source_path) as source_image:
        if getattr(source_image, "n_frames", 1) > 1:
            source_image.seek(page.number - 1)
        image = ImageOps.exif_transpose(source_image).convert("RGB")
        width, height = image.size
        crop = image.crop(
            (
                int(x0 * width),
                int(y0 * height),
                max(int(x1 * width), int(x0 * width) + 1),
                max(int(y1 * height), int(y0 * height) + 1),
            )
        )
        scale = max(1.0, dpi / max(page.dpi, 1))
        if scale > 1:
            crop = crop.resize(
                (round(crop.width * scale), round(crop.height * scale)),
                Image.Resampling.LANCZOS,
            )
        crop.save(output, "PNG")
    return output


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
    page_range: tuple[int, int] | None = None,
) -> IngestedDocument:
    suffix = _validate_input(data, filename, max_bytes)
    digest = hashlib.sha256(data).hexdigest()
    source_path = workdir / f"source{suffix}"
    source_path.write_bytes(data)
    pages_dir = workdir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    pages, total_pages = (
        _ingest_pdf(data, pages_dir, dpi, max_pages, max_page_pixels, page_range)
        if suffix == ".pdf"
        else _ingest_image(data, pages_dir, dpi, max_pages, max_page_pixels, page_range)
    )
    if not pages:
        raise ValueError("Document contains no readable pages")
    return IngestedDocument(filename, digest, source_path, pages, total_pages)


def _ingest_pdf(
    data: bytes,
    pages_dir: Path,
    dpi: int,
    max_pages: int,
    max_page_pixels: int,
    page_range: tuple[int, int] | None,
) -> tuple[list[PageEvidence], int]:
    pages: list[PageEvidence] = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported")
        if document.page_count > max_pages:
            raise ValueError(f"Document exceeds page limit of {max_pages}")
        selected = range(1, document.page_count + 1)
        if page_range is not None:
            start, end = page_range
            if not 1 <= start <= end <= document.page_count:
                raise ValueError(f"page range must be within 1-{document.page_count}")
            selected = range(start, end + 1)
        scale = dpi / 72
        matrix = pymupdf.Matrix(scale, scale)
        for index, page in enumerate(document):
            page_number = index + 1
            if page_number not in selected:
                continue
            width, height = float(page.rect.width), float(page.rect.height)
            if int(width * scale) * int(height * scale) > max_page_pixels:
                raise ValueError(f"Page {page_number} exceeds rendered pixel limit")
            image_path = pages_dir / f"page-{page_number:04d}.png"
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_path.write_bytes(pixmap.tobytes("png"))

            pages.append(
                PageEvidence(
                    number=page_number,
                    width=width,
                    height=height,
                    dpi=dpi,
                    image_path=image_path,
                    render_width_pixels=pixmap.width,
                    render_height_pixels=pixmap.height,
                    effective_dpi=float(dpi),
                    source_width=width,
                    source_height=height,
                    source_unit="pdf_points",
                    source_rotation_degrees=int(page.rotation),
                )
            )
        total_pages = document.page_count
    return pages, total_pages


def _ingest_image(
    data: bytes,
    pages_dir: Path,
    dpi: int,
    max_pages: int,
    max_page_pixels: int,
    page_range: tuple[int, int] | None,
) -> tuple[list[PageEvidence], int]:
    pages: list[PageEvidence] = []
    with Image.open(io.BytesIO(data)) as image:
        total_pages = int(getattr(image, "n_frames", 1))
        if page_range is not None:
            start, end = page_range
            if not 1 <= start <= end <= total_pages:
                raise ValueError(f"frame range must be within 1-{total_pages}")
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            page_number = index + 1
            if page_number > max_pages:
                raise ValueError(f"Document exceeds page limit of {max_pages}")
            if page_range is not None and not start <= page_number <= end:
                continue
            if frame.width * frame.height > max_page_pixels:
                raise ValueError(f"Page {page_number} exceeds pixel limit")
            rgb = ImageOps.exif_transpose(frame).convert("RGB")
            image_path = pages_dir / f"page-{page_number:04d}.png"
            rgb.save(image_path, "PNG")
            pages.append(
                PageEvidence(
                    number=page_number,
                    width=float(rgb.width),
                    height=float(rgb.height),
                    dpi=dpi,
                    image_path=image_path,
                    render_width_pixels=rgb.width,
                    render_height_pixels=rgb.height,
                    effective_dpi=None,
                    source_width=float(rgb.width),
                    source_height=float(rgb.height),
                    source_unit="pixels",
                )
            )
    return pages, total_pages
