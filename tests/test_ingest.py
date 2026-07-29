from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from grounded_docparse.ingest import ingest_document, render_region_crop
from grounded_docparse.models import BoundingBox


def test_ingest_pdf_ignores_selectable_text(simple_pdf: bytes, tmp_path: Path) -> None:
    document = ingest_document(
        simple_pdf,
        "test.pdf",
        tmp_path,
        dpi=150,
        max_bytes=10_000_000,
    )
    assert len(document.pages) == 1
    assert document.pages[0].scanned


def test_rejects_fake_pdf(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a PDF"):
        ingest_document(b"not pdf", "bad.pdf", tmp_path, dpi=150, max_bytes=100)


def test_rejects_excessive_page_count(tmp_path: Path) -> None:
    source = pymupdf.open()
    source.new_page()
    source.new_page()
    data = source.tobytes()
    source.close()
    with pytest.raises(ValueError, match="page limit"):
        ingest_document(
            data,
            "many.pdf",
            tmp_path,
            dpi=72,
            max_bytes=1_000_000,
            max_pages=1,
            max_page_pixels=20_000_000,
        )


def test_region_crop_is_rerendered_from_pdf_at_requested_dpi(
    simple_pdf: bytes, tmp_path: Path
) -> None:
    document = ingest_document(
        simple_pdf,
        "source.pdf",
        tmp_path,
        dpi=72,
        max_bytes=1_000_000,
    )
    output = tmp_path / "crop.png"

    render_region_crop(
        document,
        document.pages[0],
        BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2),
        output,
        dpi=450,
        padding=0.05,
    )

    pixmap = pymupdf.Pixmap(str(output))
    assert pixmap.width > 300
    assert pixmap.height > 400
