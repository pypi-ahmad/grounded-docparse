from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from grounded_docparse.ingest import ingest_document


def test_ingest_digital_pdf(simple_pdf: bytes, tmp_path: Path) -> None:
    document = ingest_document(
        simple_pdf,
        "test.pdf",
        tmp_path,
        dpi=150,
        max_bytes=10_000_000,
    )
    assert len(document.pages) == 1
    assert not document.pages[0].scanned
    assert "Grounded source paragraph" in document.pages[0].digital_text
    assert document.pages[0].text_blocks[0].bbox.unit == "normalized"


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
