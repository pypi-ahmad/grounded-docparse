"""Detects the source format of an uploaded document, validates that the
caller-supplied `ProcessingType` is compatible with it, and dispatches to
exactly one parser (legacy OCR, PDF Inspector, or Docling).

Must not: infer or override a caller's processing-type selection, or route a
document through a pipeline other than the one explicitly selected — a
mismatch must fail closed (see `validate_processing_type` and
`validate_pdf_processing_type`).

Next: `pipeline.py` for the OCR/grounded-parse route used for Scanned PDF and
Image; `native.py` for the `NativeParseResult`, `PageRoute`, `ProcessingType`,
and `SourceFormat` contracts the native routes populate.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pymupdf
from PIL import Image

from .config import ParserConfig
from .content_range import (
    AppliedContentRange,
    ContentRange,
    ContentRangeInfo,
    ContentUnit,
    resolve_content_range,
)
from .native import (
    NativeParseResult,
    PageRoute,
    ProcessingType,
    SourceFormat,
)
from .pipeline import DocumentParser

_SUFFIX_FORMATS = {
    ".pdf": SourceFormat.PDF,
    ".docx": SourceFormat.DOCX,
    ".pptx": SourceFormat.PPTX,
    ".xlsx": SourceFormat.XLSX,
    ".csv": SourceFormat.CSV,
    ".odt": SourceFormat.ODT,
    ".odp": SourceFormat.ODP,
    ".ods": SourceFormat.ODS,
    ".html": SourceFormat.HTML,
    ".htm": SourceFormat.HTML,
    ".md": SourceFormat.MARKDOWN,
    ".markdown": SourceFormat.MARKDOWN,
    ".epub": SourceFormat.EPUB,
    ".png": SourceFormat.PNG,
    ".jpg": SourceFormat.JPEG,
    ".jpeg": SourceFormat.JPEG,
    ".tif": SourceFormat.TIFF,
    ".tiff": SourceFormat.TIFF,
}

_COMPATIBLE_PROCESSING_TYPES = {
    SourceFormat.PDF: {
        ProcessingType.NATIVE_PDF,
        ProcessingType.SCANNED_PDF,
        ProcessingType.MIXED_PDF,
    },
    SourceFormat.DOCX: {ProcessingType.WORD},
    SourceFormat.PPTX: {ProcessingType.POWERPOINT},
    SourceFormat.XLSX: {ProcessingType.EXCEL},
    SourceFormat.CSV: {ProcessingType.CSV},
    SourceFormat.ODT: {ProcessingType.OTHER_NATIVE},
    SourceFormat.ODP: {ProcessingType.OTHER_NATIVE},
    SourceFormat.ODS: {ProcessingType.OTHER_NATIVE},
    SourceFormat.HTML: {ProcessingType.OTHER_NATIVE},
    SourceFormat.MARKDOWN: {ProcessingType.OTHER_NATIVE},
    SourceFormat.EPUB: {ProcessingType.OTHER_NATIVE},
    SourceFormat.PNG: {ProcessingType.IMAGE},
    SourceFormat.JPEG: {ProcessingType.IMAGE},
    SourceFormat.TIFF: {ProcessingType.IMAGE},
}


class ProcessingTypeMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PdfInspection:
    pdf_type: str
    page_count: int
    pages_needing_ocr: frozenset[int]
    ocr_reasons_by_page: tuple[tuple[int, tuple[str, ...]], ...] = ()
    pages_with_tables: frozenset[int] = frozenset()
    pages_with_columns: frozenset[int] = frozenset()
    confidence: float = 0.0

    @property
    def suggested_routes(self) -> dict[int, PageRoute]:
        return {
            page: (
                PageRoute.OCR
                if page in self.pages_needing_ocr
                else PageRoute.NATIVE
            )
            for page in range(1, self.page_count + 1)
        }


class NativePdfRequiresMixed(ProcessingTypeMismatch):
    def __init__(self, pages: set[int] | frozenset[int]) -> None:
        self.pages = tuple(sorted(pages))
        super().__init__(
            "native PDF has unusable page(s) "
            + ", ".join(str(page) for page in self.pages)
            + "; select Mixed PDF"
        )


class MixedNativePageUnusable(ProcessingTypeMismatch):
    def __init__(self, pages: set[int] | frozenset[int]) -> None:
        self.pages = tuple(sorted(pages))
        super().__init__(
            "mixed PDF native route is unusable for page(s) "
            + ", ".join(str(page) for page in self.pages)
            + "; choose OCR for those pages"
        )


def inspect_pdf_content(data: bytes) -> PdfInspection:
    # pdf_inspector ships only with the optional `native` extra; import
    # lazily so code paths that never touch PDFs don't need it installed.
    try:
        import pdf_inspector
    except ImportError as exc:
        raise RuntimeError(
            "PDF processing-type validation requires grounded-docparse[native]"
        ) from exc
    result = pdf_inspector.process_pdf_bytes(data)
    return PdfInspection(
        pdf_type=result.pdf_type,
        page_count=result.page_count,
        pages_needing_ocr=frozenset(result.pages_needing_ocr),
        ocr_reasons_by_page=tuple(
            (item.page, tuple(item.reasons))
            for item in result.ocr_reasons_by_page
        ),
        pages_with_tables=frozenset(result.pages_with_tables),
        pages_with_columns=frozenset(result.pages_with_columns),
        confidence=result.confidence,
    )


def _zip_names(data: bytes) -> tuple[set[str], bytes | None]:
    # `data` is untrusted upload content. Bound entry count and expanded size
    # before reading names/contents to avoid a zip-bomb-style resource blowup.
    try:
        with ZipFile(BytesIO(data)) as archive:
            if len(archive.infolist()) > 10_000:
                raise ValueError("document archive contains too many entries")
            if sum(item.file_size for item in archive.infolist()) > 1_000_000_000:
                raise ValueError("document archive expands beyond 1 GB")
            names = set(archive.namelist())
            mime = archive.read("mimetype") if "mimetype" in names else None
            return names, mime
    except BadZipFile as exc:
        raise ValueError("document does not contain a valid ZIP container") from exc


def detect_source_format(data: bytes, filename: str) -> SourceFormat:
    # `filename` (and its extension) is caller-supplied and not trusted on
    # its own; the checks below confirm `data` actually matches the claimed
    # format (magic-byte signature, then ZIP container contents) before
    # anything downstream treats it as that format.
    suffix = Path(filename).suffix.casefold()
    source_format = _SUFFIX_FORMATS.get(suffix)
    if source_format is None:
        raise ValueError(f"unsupported input type: {suffix or 'missing extension'}")

    if source_format is SourceFormat.PDF and not data.startswith(b"%PDF-"):
        raise ValueError("PDF signature does not match its extension")
    if source_format is SourceFormat.PNG and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG signature does not match its extension")
    if source_format is SourceFormat.JPEG and not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("JPEG signature does not match its extension")
    if source_format is SourceFormat.TIFF and not data.startswith((b"II*\x00", b"MM\x00*")):
        raise ValueError("TIFF signature does not match its extension")

    if source_format in {
        SourceFormat.DOCX,
        SourceFormat.PPTX,
        SourceFormat.XLSX,
        SourceFormat.ODT,
        SourceFormat.ODP,
        SourceFormat.ODS,
        SourceFormat.EPUB,
    }:
        # The signature check above only proved "this is a ZIP"; confirm it
        # also holds the specific parts/mimetype each format requires.
        names, mime = _zip_names(data)
        if source_format is SourceFormat.DOCX and not {
            "[Content_Types].xml",
            "word/document.xml",
        }.issubset(names):
            raise ValueError("DOCX container is missing required Word parts")
        if source_format is SourceFormat.PPTX and not {
            "[Content_Types].xml",
            "ppt/presentation.xml",
        }.issubset(names):
            raise ValueError("PPTX container is missing required PowerPoint parts")
        if source_format is SourceFormat.XLSX and not {
            "[Content_Types].xml",
            "xl/workbook.xml",
        }.issubset(names):
            raise ValueError("XLSX container is missing required Excel parts")
        expected_mime = {
            SourceFormat.ODT: b"application/vnd.oasis.opendocument.text",
            SourceFormat.ODP: b"application/vnd.oasis.opendocument.presentation",
            SourceFormat.ODS: b"application/vnd.oasis.opendocument.spreadsheet",
            SourceFormat.EPUB: b"application/epub+zip",
        }.get(source_format)
        if expected_mime is not None and mime != expected_mime:
            raise ValueError(f"{source_format.value.upper()} container has an invalid mimetype")

    if source_format in {
        SourceFormat.CSV,
        SourceFormat.HTML,
        SourceFormat.MARKDOWN,
    }:
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{source_format.value} input must be UTF-8") from exc
    return source_format


def validate_processing_type(
    source_format: SourceFormat,
    processing_type: ProcessingType,
) -> None:
    if processing_type not in _COMPATIBLE_PROCESSING_TYPES[source_format]:
        raise ValueError(
            f"processing type {processing_type.value} is not compatible with "
            f"{source_format.value}"
        )


def inspect_content_range(data: bytes, filename: str) -> ContentRangeInfo:
    source_format = detect_source_format(data, filename)
    if source_format is SourceFormat.PDF:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            return ContentRangeInfo(unit=ContentUnit.PAGE, total=max(1, document.page_count))
    if source_format in {SourceFormat.PNG, SourceFormat.JPEG, SourceFormat.TIFF}:
        with Image.open(BytesIO(data)) as image:
            frames = max(1, int(getattr(image, "n_frames", 1)))
        return ContentRangeInfo(
            unit=ContentUnit.FRAME if source_format is SourceFormat.TIFF else ContentUnit.PAGE,
            total=frames,
        )
    if source_format is SourceFormat.CSV:
        rows = list(csv.reader(StringIO(data.decode("utf-8-sig"))))
        return ContentRangeInfo(unit=ContentUnit.ROW, total=max(1, len(rows)))

    # Only formats other than PDF/image/CSV (which return above) reach here;
    # importing docling_native (and Docling) lazily avoids paying that cost
    # for the formats that don't need it.
    from .docling_native import build_source_manifest

    manifest = build_source_manifest(data, source_format)
    unit = {
        SourceFormat.PPTX: ContentUnit.SLIDE,
        SourceFormat.ODP: ContentUnit.SLIDE,
        SourceFormat.XLSX: ContentUnit.SHEET,
        SourceFormat.ODS: ContentUnit.SHEET,
        SourceFormat.EPUB: ContentUnit.SECTION,
    }.get(source_format, ContentUnit.BLOCK)
    total = len(manifest.units) if unit is not ContentUnit.BLOCK else len(manifest.records)
    return ContentRangeInfo(unit=unit, total=max(1, total))


def validate_pdf_processing_type(
    inspection: PdfInspection,
    processing_type: ProcessingType,
    page_routes: dict[int, PageRoute] | None = None,
    content_range: AppliedContentRange | None = None,
) -> None:
    """Enforce the fail-closed PDF routing contract for the pages actually
    selected (via `content_range`, or all pages if unset).

    Native PDF must not silently fall back to OCR: if any selected page needs
    OCR, raise rather than proceed. Mixed PDF must not silently pick a route
    either: every selected page must already have an explicit, reviewed entry
    in `page_routes`. Scanned PDF has no `expected_type` entry, so it returns
    early with no pdf-inspector classification requirement — it always goes
    through the OCR engine regardless of `inspection.pdf_type`.
    """
    selected_pages = (
        set(range(content_range.start, content_range.end + 1))
        if content_range is not None
        else set(range(1, inspection.page_count + 1))
    )
    expected_type = {
        ProcessingType.NATIVE_PDF: {"text_based"},
        ProcessingType.MIXED_PDF: {"mixed"},
    }.get(processing_type)
    if expected_type is None:
        return
    if (
        processing_type is ProcessingType.NATIVE_PDF
        and (inspection.pages_needing_ocr & selected_pages)
    ):
        raise NativePdfRequiresMixed(inspection.pages_needing_ocr & selected_pages)
    if inspection.pdf_type not in expected_type:
        raise ProcessingTypeMismatch(
            f"selected {processing_type.value}, but pdf-inspector classified "
            f"the file as {inspection.pdf_type}"
        )
    if processing_type is not ProcessingType.MIXED_PDF:
        return
    if page_routes is None or not selected_pages.issubset(page_routes):
        raise ProcessingTypeMismatch(
            "mixed PDF requires one explicit processing route for every page in the selected range"
        )


class UniversalDocumentParser:
    """Validates a caller-supplied `ProcessingType` against the detected
    `SourceFormat` and dispatches to exactly one parser: the legacy OCR
    parser for Scanned PDF/Image, `PdfInspectorParser` for PDF, or
    `DoclingNativeParser` for other native formats.

    Must not: choose a route from file contents alone, or substitute a
    different route than the one the caller selected.
    """

    def __init__(
        self,
        config: ParserConfig | None = None,
        *,
        legacy_parser: DocumentParser | None = None,
        pdf_parser=None,
        docling_parser=None,
        pdf_inspector: Callable[[bytes], PdfInspection] | None = None,
    ) -> None:
        self.config = config or ParserConfig.from_env()
        self.legacy_parser = legacy_parser or DocumentParser(self.config)
        self.pdf_parser = pdf_parser
        self.docling_parser = docling_parser
        self.pdf_inspector = pdf_inspector or inspect_pdf_content
        # pdf_parser/docling_parser are left unset here and constructed
        # lazily in parse() on first use, so a caller that never parses a PDF
        # (or never parses a non-PDF native document) doesn't need that
        # parser's optional-extra dependencies importable.

    def parse(
        self,
        data: bytes,
        filename: str,
        progress_callback=None,
        *,
        processing_type: ProcessingType,
        page_routes: dict[int, PageRoute] | None = None,
        refine_markdown: bool = True,
        visual_recovery: bool = True,
        content_range: ContentRange | None = None,
    ) -> object | NativeParseResult:
        if len(data) > self.config.max_upload_bytes:
            raise ValueError("document exceeds the configured upload limit")
        source_format = detect_source_format(data, filename)
        validate_processing_type(source_format, processing_type)
        applied_range = (
            resolve_content_range(
                content_range,
                inspect_content_range(data, filename),
            )
            if content_range is not None
            else None
        )
        if processing_type in {ProcessingType.SCANNED_PDF, ProcessingType.IMAGE}:
            # Only route that still goes through the OCR/grounded pipeline
            # (DocumentParser) rather than a native/PDF-Inspector path.
            legacy_kwargs = {
                "progress_callback": progress_callback,
                "refine_markdown": refine_markdown,
                "visual_recovery": visual_recovery,
            }
            if applied_range is not None:
                legacy_kwargs["content_range"] = applied_range
            return self.legacy_parser.parse(
                data,
                filename,
                **legacy_kwargs,
            )
        inspection = None
        if source_format is SourceFormat.PDF:
            # Native/Mixed PDF only: classify pages so
            # validate_pdf_processing_type can enforce the fail-closed
            # contract below before any page is actually parsed.
            inspection = self.pdf_inspector(data)
            validate_pdf_processing_type(
                inspection,
                processing_type,
                page_routes,
                applied_range,
            )
        if source_format is SourceFormat.PDF:
            if self.pdf_parser is None:
                from .native_parsers import PdfInspectorParser

                # See __init__: built here, not eagerly, to skip this import
                # for non-PDF documents.
                self.pdf_parser = PdfInspectorParser(self.config, self.legacy_parser)
            pdf_kwargs = {
                "processing_type": processing_type,
                "page_routes": page_routes,
                "inspection": inspection,
                "progress_callback": progress_callback,
                "refine_markdown": refine_markdown,
                "visual_recovery": visual_recovery,
            }
            if applied_range is not None:
                pdf_kwargs["content_range"] = applied_range
            return self.pdf_parser.parse(
                data,
                filename,
                **pdf_kwargs,
            )

        if self.docling_parser is None:
            from .native_parsers import DoclingNativeParser

            # Reached only for non-PDF, non-legacy formats; see __init__ for
            # why this isn't constructed eagerly.
            self.docling_parser = DoclingNativeParser(self.config)
        docling_kwargs = {
            "source_format": source_format,
            "processing_type": processing_type,
        }
        if applied_range is not None:
            docling_kwargs["content_range"] = applied_range
        return self.docling_parser.parse(
            data,
            filename,
            **docling_kwargs,
        )
