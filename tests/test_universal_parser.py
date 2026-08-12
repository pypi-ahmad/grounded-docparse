from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from grounded_docparse.native import PageRoute, ProcessingType, SourceFormat
from grounded_docparse.universal import (
    PdfInspection,
    ProcessingTypeMismatch,
    UniversalDocumentParser,
    detect_source_format,
    validate_processing_type,
)


def _zip(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("a.pdf", b"%PDF-1.7\n", SourceFormat.PDF),
        ("a.png", b"\x89PNG\r\n\x1a\n", SourceFormat.PNG),
        ("a.jpg", b"\xff\xd8\xff\xe0", SourceFormat.JPEG),
        ("a.csv", b"name,value\na,1\n", SourceFormat.CSV),
        ("a.md", b"# Heading\n", SourceFormat.MARKDOWN),
        ("a.html", b"<!doctype html><p>Hello</p>", SourceFormat.HTML),
        (
            "a.docx",
            _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>"}),
            SourceFormat.DOCX,
        ),
        (
            "a.epub",
            _zip({"mimetype": b"application/epub+zip", "META-INF/container.xml": b"<x/>"}),
            SourceFormat.EPUB,
        ),
    ],
)
def test_detect_source_format(name: str, data: bytes, expected: SourceFormat) -> None:
    assert detect_source_format(data, name) is expected


def test_detect_source_format_rejects_spoofed_extension() -> None:
    with pytest.raises(ValueError, match="signature"):
        detect_source_format(b"not a pdf", "notice.pdf")


def test_detect_source_format_rejects_wrong_ooxml_container() -> None:
    data = _zip({"[Content_Types].xml": b"<Types/>", "ppt/presentation.xml": b"<p/>"})

    with pytest.raises(ValueError, match="DOCX"):
        detect_source_format(data, "notice.docx")


@pytest.mark.parametrize(
    ("source_format", "processing_type"),
    [
        (SourceFormat.PDF, ProcessingType.NATIVE_PDF),
        (SourceFormat.PDF, ProcessingType.SCANNED_PDF),
        (SourceFormat.PDF, ProcessingType.MIXED_PDF),
        (SourceFormat.DOCX, ProcessingType.WORD),
        (SourceFormat.PPTX, ProcessingType.POWERPOINT),
        (SourceFormat.XLSX, ProcessingType.EXCEL),
        (SourceFormat.CSV, ProcessingType.CSV),
        (SourceFormat.EPUB, ProcessingType.OTHER_NATIVE),
        (SourceFormat.PNG, ProcessingType.IMAGE),
    ],
)
def test_processing_type_compatibility(
    source_format: SourceFormat, processing_type: ProcessingType
) -> None:
    validate_processing_type(source_format, processing_type)


def test_processing_type_rejects_mismatch() -> None:
    with pytest.raises(ValueError, match="not compatible"):
        validate_processing_type(SourceFormat.DOCX, ProcessingType.NATIVE_PDF)


def test_scanned_pdf_delegates_to_legacy_parser() -> None:
    sentinel = object()

    class LegacyParser:
        def parse(self, data, filename, progress_callback=None, **kwargs):
            assert data.startswith(b"%PDF")
            assert filename == "scan.pdf"
            assert progress_callback is None
            assert kwargs == {
                "refine_markdown": True,
                "visual_recovery": True,
            }
            return sentinel

    parser = UniversalDocumentParser(
        legacy_parser=LegacyParser(),
        pdf_inspector=lambda _data: PdfInspection(
            pdf_type="scanned",
            page_count=1,
            pages_needing_ocr=frozenset({1}),
        ),
    )

    assert (
        parser.parse(
            b"%PDF-1.7\n",
            "scan.pdf",
            processing_type=ProcessingType.SCANNED_PDF,
        )
        is sentinel
    )


def test_wrong_pdf_selection_blocks_before_any_pipeline() -> None:
    calls = []

    class Parser:
        def parse(self, *_args, **_kwargs):
            calls.append("called")

    parser = UniversalDocumentParser(
        legacy_parser=Parser(),
        pdf_parser=Parser(),
        pdf_inspector=lambda _data: PdfInspection(
            pdf_type="text_based",
            page_count=1,
            pages_needing_ocr=frozenset(),
        ),
    )

    with pytest.raises(ProcessingTypeMismatch, match="classified"):
        parser.parse(
            b"%PDF-1.7\n",
            "scan.pdf",
            processing_type=ProcessingType.SCANNED_PDF,
        )

    assert calls == []


def test_native_pdf_reaches_only_native_pipeline() -> None:
    calls = []
    sentinel = object()

    class LegacyParser:
        def parse(self, *_args, **_kwargs):
            calls.append("legacy")

    class NativeParser:
        def parse(self, *_args, **_kwargs):
            calls.append("native")
            return sentinel

    parser = UniversalDocumentParser(
        legacy_parser=LegacyParser(),
        pdf_parser=NativeParser(),
        pdf_inspector=lambda _data: PdfInspection(
            pdf_type="text_based",
            page_count=1,
            pages_needing_ocr=frozenset(),
        ),
    )

    result = parser.parse(
        b"%PDF-1.7\n",
        "native.pdf",
        processing_type=ProcessingType.NATIVE_PDF,
    )

    assert result is sentinel
    assert calls == ["native"]


def test_mixed_pdf_requires_complete_compatible_page_routes() -> None:
    parser = UniversalDocumentParser(
        legacy_parser=object(),
        pdf_parser=object(),
        pdf_inspector=lambda _data: PdfInspection(
            pdf_type="mixed",
            page_count=2,
            pages_needing_ocr=frozenset({2}),
        ),
    )

    with pytest.raises(ProcessingTypeMismatch, match="every page"):
        parser.parse(
            b"%PDF-1.7\n",
            "mixed.pdf",
            processing_type=ProcessingType.MIXED_PDF,
        )
    with pytest.raises(ProcessingTypeMismatch, match="conflicts"):
        parser.parse(
            b"%PDF-1.7\n",
            "mixed.pdf",
            processing_type=ProcessingType.MIXED_PDF,
            page_routes={1: PageRoute.OCR, 2: PageRoute.NATIVE},
        )
