from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pymupdf
import pytest

from grounded_docparse.config import ParserConfig
from grounded_docparse.content_range import AppliedContentRange, ContentUnit
from grounded_docparse.models import Block, BoundingBox, Document, Page, ParseResult
from grounded_docparse.native import PageRoute, ProcessingType
from grounded_docparse.native_parsers import PdfInspectorParser
from grounded_docparse.render import render_agentic_document
from grounded_docparse.universal import MixedNativePageUnusable, PdfInspection


def _pdf(page_count: int = 3) -> bytes:
    document = pymupdf.open()
    try:
        for page in range(1, page_count + 1):
            document.new_page().insert_text((72, 72), f"Native page {page}")
        return document.tobytes()
    finally:
        document.close()


class FakePdfInspector:
    def extract_pages_markdown_bytes(self, _data, *, pages):
        return SimpleNamespace(
            pages=[
                SimpleNamespace(
                    page=page,
                    markdown=(
                        "Native page 1\n\n| A | B |\n|---|---|\n| 1 | 2 |"
                        if page == 0
                        else f"Native page {page + 1}"
                    ),
                    needs_ocr=False,
                )
                for page in pages
            ]
        )

    def extract_text_with_positions_bytes(self, _data, *, pages):
        return [
            SimpleNamespace(
                page=page,
                text=f"Native page {page}",
                x=72.0,
                y=60.0,
                width=100.0,
                height=14.0,
                item_type="text",
                mcid=None,
            )
            for page in pages
        ]

    def extract_structure_elements_bytes(self, _data, *, pages):
        del pages
        return []


class FakeLegacyParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, data, filename, **_kwargs):
        self.calls += 1
        with pymupdf.open(stream=data, filetype="pdf") as subset:
            assert subset.page_count == 1
        document = Document(
            source_name=filename,
            source_sha256=hashlib.sha256(data).hexdigest(),
            pages=[
                Page(
                    number=1,
                    width=595,
                    height=842,
                    blocks=[
                        Block(
                            id="ocr-1",
                            type="paragraph",
                            text="OCR page 2",
                            bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.4, y1=0.2),
                            reading_order=0,
                        )
                    ],
                )
            ],
        )
        rendered = render_agentic_document(document)
        return ParseResult(
            document=document,
            markdown=rendered.markdown,
            json=rendered.json,
            input_tokens=0,
            output_tokens=0,
            annotated_pdf=data,
        )


def test_native_pdf_extracts_markdown_positions_and_table_metadata() -> None:
    legacy = FakeLegacyParser()
    inspector = FakePdfInspector()
    parser = PdfInspectorParser(ParserConfig(), legacy, pdf_module=inspector)

    result = parser.parse(
        _pdf(page_count=1),
        "native.pdf",
        processing_type=ProcessingType.NATIVE_PDF,
        page_routes=None,
        inspection=PdfInspection(
            pdf_type="text_based",
            page_count=1,
            pages_needing_ocr=frozenset(),
            pages_with_tables=frozenset({1}),
        ),
    )

    assert legacy.calls == 0
    assert result.document.base_text == "Native page 1"
    assert result.document.elements[0].source.anchor.page == 1
    assert result.document.elements[0].source.anchor.bbox is not None
    assert result.document.units[0].warnings == ["table layout detected"]
    assert "Native page 1" in result.markdown
    assert "| A | B |" in result.markdown


def test_mixed_pdf_merges_native_and_ocr_pages_in_source_order() -> None:
    legacy = FakeLegacyParser()
    parser = PdfInspectorParser(
        ParserConfig(), legacy, pdf_module=FakePdfInspector()
    )
    routes = {
        1: PageRoute.NATIVE,
        2: PageRoute.OCR,
        3: PageRoute.NATIVE,
    }

    result = parser.parse(
        _pdf(),
        "mixed.pdf",
        processing_type=ProcessingType.MIXED_PDF,
        page_routes=routes,
        inspection=PdfInspection(
            pdf_type="mixed",
            page_count=3,
            pages_needing_ocr=frozenset({2}),
            pages_with_tables=frozenset({1}),
        ),
    )

    assert legacy.calls == 1
    assert [unit.effective_route for unit in result.document.units] == [
        PageRoute.NATIVE,
        PageRoute.OCR,
        PageRoute.NATIVE,
    ]
    assert [element.source.anchor.page for element in result.document.elements] == [
        1,
        2,
        3,
    ]
    assert result.markdown.index("Native page 1") < result.markdown.index("OCR page 2")
    assert result.markdown.index("OCR page 2") < result.markdown.index("Native page 3")
    assert result.annotated_pdf.startswith(b"%PDF")


def test_mixed_ocr_to_native_override_fails_without_ocr_fallback() -> None:
    legacy = FakeLegacyParser()
    parser = PdfInspectorParser(
        ParserConfig(), legacy, pdf_module=FakePdfInspector()
    )

    with pytest.raises(MixedNativePageUnusable, match=r"page\(s\) 2"):
        parser.parse(
            _pdf(),
            "mixed.pdf",
            processing_type=ProcessingType.MIXED_PDF,
            page_routes={
                1: PageRoute.NATIVE,
                2: PageRoute.NATIVE,
                3: PageRoute.NATIVE,
            },
            inspection=PdfInspection(
                pdf_type="mixed",
                page_count=3,
                pages_needing_ocr=frozenset({2}),
            ),
        )

    assert legacy.calls == 0


def test_mixed_pdf_range_keeps_original_page_indices() -> None:
    parser = PdfInspectorParser(
        ParserConfig(), FakeLegacyParser(), pdf_module=FakePdfInspector()
    )
    selected = AppliedContentRange(
        start=2,
        end=3,
        unit=ContentUnit.PAGE,
        total=3,
    )

    result = parser.parse(
        _pdf(),
        "mixed.pdf",
        processing_type=ProcessingType.MIXED_PDF,
        page_routes={1: PageRoute.NATIVE, 2: PageRoute.OCR, 3: PageRoute.NATIVE},
        inspection=PdfInspection(
            pdf_type="mixed",
            page_count=3,
            pages_needing_ocr=frozenset({2}),
        ),
        content_range=selected,
    )

    assert [unit.index for unit in result.document.units] == [2, 3]
    assert [element.source.anchor.page for element in result.document.elements] == [2, 3]
    assert result.document.content_range == selected
    with pymupdf.open(stream=result.annotated_pdf, filetype="pdf") as annotated:
        assert annotated.page_count == 3
