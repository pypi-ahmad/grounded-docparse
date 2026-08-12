from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .config import ParserConfig
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


def inspect_pdf_content(data: bytes) -> PdfInspection:
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
    )


def _zip_names(data: bytes) -> tuple[set[str], bytes | None]:
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


def validate_pdf_processing_type(
    inspection: PdfInspection,
    processing_type: ProcessingType,
    page_routes: dict[int, PageRoute] | None = None,
) -> None:
    expected_type = {
        ProcessingType.NATIVE_PDF: {"text_based"},
        ProcessingType.SCANNED_PDF: {"scanned", "image_based"},
        ProcessingType.MIXED_PDF: {"mixed"},
    }[processing_type]
    if inspection.pdf_type not in expected_type:
        raise ProcessingTypeMismatch(
            f"selected {processing_type.value}, but pdf-inspector classified "
            f"the file as {inspection.pdf_type}"
        )
    if processing_type is not ProcessingType.MIXED_PDF:
        return
    expected_pages = set(range(1, inspection.page_count + 1))
    if page_routes is None or set(page_routes) != expected_pages:
        raise ProcessingTypeMismatch(
            "mixed PDF requires one explicit processing route for every page"
        )
    incompatible = [
        page
        for page, route in page_routes.items()
        if (route is PageRoute.OCR) != (page in inspection.pages_needing_ocr)
    ]
    if incompatible:
        raise ProcessingTypeMismatch(
            "mixed PDF page route conflicts with pdf-inspector for page(s): "
            + ", ".join(str(page) for page in sorted(incompatible))
        )


class UniversalDocumentParser:
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
    ) -> object | NativeParseResult:
        if len(data) > self.config.max_upload_bytes:
            raise ValueError("document exceeds the configured upload limit")
        source_format = detect_source_format(data, filename)
        validate_processing_type(source_format, processing_type)
        if source_format is SourceFormat.PDF:
            validate_pdf_processing_type(
                self.pdf_inspector(data),
                processing_type,
                page_routes,
            )
        if processing_type in {ProcessingType.SCANNED_PDF, ProcessingType.IMAGE}:
            return self.legacy_parser.parse(
                data,
                filename,
                progress_callback=progress_callback,
                refine_markdown=refine_markdown,
                visual_recovery=visual_recovery,
            )
        if source_format is SourceFormat.PDF:
            if self.pdf_parser is None:
                from .native_parsers import PdfInspectorParser

                self.pdf_parser = PdfInspectorParser(self.config, self.legacy_parser)
            return self.pdf_parser.parse(
                data,
                filename,
                processing_type=processing_type,
                page_routes=page_routes,
            )

        if self.docling_parser is None:
            from .native_parsers import DoclingNativeParser

            self.docling_parser = DoclingNativeParser(self.config)
        return self.docling_parser.parse(
            data,
            filename,
            source_format=source_format,
            processing_type=processing_type,
        )
