from __future__ import annotations

from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from grounded_docparse.content_range import (
    ContentRange,
    ContentRangeInfo,
    ContentUnit,
    resolve_content_range,
)
from grounded_docparse.ingest import ingest_document
from grounded_docparse.universal import inspect_content_range


def test_range_validation_and_resolution() -> None:
    with pytest.raises(ValueError, match="end must be at or after start"):
        ContentRange(start=3, end=2)

    info = ContentRangeInfo(unit=ContentUnit.PAGE, total=4)
    applied = resolve_content_range(ContentRange(start=2, end=3), info)
    assert applied is not None
    assert applied.model_dump() == {
        "start": 2,
        "end": 3,
        "unit": ContentUnit.PAGE,
        "total": 4,
    }
    with pytest.raises(ValueError, match="within 1-4"):
        resolve_content_range(ContentRange(start=2, end=5), info)


def test_inspection_uses_natural_units() -> None:
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.new_page()
    pdf_bytes = pdf.tobytes()
    pdf.close()
    assert inspect_content_range(pdf_bytes, "two.pdf") == ContentRangeInfo(
        unit=ContentUnit.PAGE,
        total=2,
    )

    first = Image.new("RGB", (8, 8), "white")
    second = Image.new("RGB", (8, 8), "black")
    buffer = BytesIO()
    first.save(buffer, format="TIFF", save_all=True, append_images=[second])
    assert inspect_content_range(buffer.getvalue(), "two.tiff") == ContentRangeInfo(
        unit=ContentUnit.FRAME,
        total=2,
    )
    assert inspect_content_range(b"a,b\n1,2\n", "rows.csv") == ContentRangeInfo(
        unit=ContentUnit.ROW,
        total=2,
    )
    assert inspect_content_range(b"First\n\nSecond\n", "blocks.md") == ContentRangeInfo(
        unit=ContentUnit.BLOCK,
        total=2,
    )


def test_ingest_range_preserves_original_page_numbers(tmp_path) -> None:
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.new_page()
    pdf.new_page()
    data = pdf.tobytes()
    pdf.close()

    ingested = ingest_document(
        data,
        "three.pdf",
        tmp_path,
        dpi=72,
        max_bytes=1_000_000,
        page_range=(2, 3),
    )

    assert ingested.total_pages == 3
    assert [page.number for page in ingested.pages] == [2, 3]
