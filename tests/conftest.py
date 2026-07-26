from __future__ import annotations

import pymupdf
import pytest


@pytest.fixture
def simple_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Test Report", fontsize=20)
    page.insert_text((72, 110), "Grounded source paragraph.", fontsize=11)
    data = document.tobytes()
    document.close()
    return data
