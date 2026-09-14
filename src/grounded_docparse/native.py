"""Immutable native-document evidence contract (`base_text` + `SourceAnchor`).

Responsibility: define the frozen `base_text` string, the `SourceSpan`s that
map half-open character ranges of it to `SourceAnchor` records (page/slide/
sheet/cell/CSV-row/text-line origin), and the `NativeDocument` model whose
validator enforces that every element and asset actually grounds to a real,
in-range span. This module must not perform any parsing or format-specific
extraction itself — that lives in native_parsers.py and docling_native.py,
which are the next files to read to see how these contracts get built and
which the manual routing in universal.py dispatches to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .content_range import AppliedContentRange
from .models import AgentTraceEvent, RunUsage, StoredSchema


class ProcessingType(StrEnum):
    NATIVE_PDF = "native-pdf"
    SCANNED_PDF = "scanned-pdf"
    MIXED_PDF = "mixed-pdf"
    WORD = "word"
    POWERPOINT = "powerpoint"
    EXCEL = "excel"
    CSV = "csv"
    IMAGE = "image"
    OTHER_NATIVE = "other-native"


class SourceFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    CSV = "csv"
    ODT = "odt"
    ODP = "odp"
    ODS = "ods"
    HTML = "html"
    MARKDOWN = "markdown"
    EPUB = "epub"
    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"


class PageRoute(StrEnum):
    NATIVE = "native"
    OCR = "ocr"


NormalizedBox = tuple[float, float, float, float]


class PdfSourceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["pdf"] = "pdf"
    unit_id: str
    page: int = Field(ge=1)
    bbox: NormalizedBox | None = None


class StructuralSourceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["structural"] = "structural"
    unit_id: str
    path: str
    bbox: NormalizedBox | None = None


class CellSourceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["cell"] = "cell"
    unit_id: str
    sheet: str
    cell_range: str


class CsvSourceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["csv"] = "csv"
    unit_id: str
    row_start: int = Field(ge=1)
    row_end: int = Field(ge=1)
    column_start: int = Field(ge=1)
    column_end: int = Field(ge=1)


class TextSourceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text"] = "text"
    unit_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_column: int = Field(ge=1)
    end_column: int = Field(ge=1)


# Discriminated on `kind` because each native source format needs a
# different notion of "where in the source": a page/box for PDF, a structural
# path for DOCX/PPTX/HTML-like formats, a sheet+range for XLSX, a row/column
# range for CSV, and a line/column range for plain text/Markdown.
SourceAnchor = Annotated[
    PdfSourceAnchor
    | StructuralSourceAnchor
    | CellSourceAnchor
    | CsvSourceAnchor
    | TextSourceAnchor,
    Field(discriminator="kind"),
]


class SourceSpan(BaseModel):
    """`start`/`end` are a half-open `[start, end)` range over `base_text`,
    measured in Unicode codepoints (Python string indices), not bytes."""

    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    element_id: str
    anchor: SourceAnchor

    @model_validator(mode="after")
    def valid_range(self) -> SourceSpan:
        if self.start >= self.end:
            raise ValueError("source span start must be below end")
        return self


class SourceUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["document", "page", "slide", "sheet", "section"]
    index: int = Field(ge=1)
    label: str | None = None
    requested_route: PageRoute
    effective_route: PageRoute
    parser: str
    fallback_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class NativeElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    text: str
    reading_order: int = Field(ge=0)
    source: SourceSpan
    children: list[str] = Field(default_factory=list)


class NativeAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["embedded_image"] = "embedded_image"
    anchor: SourceAnchor
    media_type: str | None = None
    filename: str | None = None
    reference: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    alt_text: str | None = None
    caption: str | None = None
    # Fixed to False rather than omitted: this asset shape only exists for
    # OCR-disabled Docling conversion, so the field makes that guarantee
    # explicit and machine-checkable in every serialized document rather than
    # relying on callers to remember which pipeline produced it.
    ocr_performed: Literal[False] = False


class CharacterInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self) -> CharacterInterval:
        if self.start >= self.end:
            raise ValueError("character interval start must be below end")
        return self


class NativeExtractionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text: str
    char_interval: CharacterInterval
    source_spans: list[SourceSpan] = Field(min_length=1)


class NativeExtractedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(pattern=r"^/")
    extraction_class: str
    value: Any
    evidence: NativeExtractionEvidence


class NativeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    source_name: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_format: SourceFormat
    requested_processing_type: ProcessingType
    # Immutable by design (Pydantic `frozen=True` field + model-level
    # `validate_assignment=True` above): every accepted value, native
    # extraction, and render must trace back to this exact text. Presentation
    # (refined Markdown) may diverge from base_text; evidence never does.
    base_text: str = Field(frozen=True)
    units: list[SourceUnit]
    elements: list[NativeElement]
    assets: list[NativeAsset] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    content_range: AppliedContentRange | None = None

    # This is the enforcement point for the whole native-evidence guarantee:
    # every element/asset must reference a real unit, every span must fall
    # inside base_text, and IDs can't collide across the three ID spaces.
    # If this validator ever accepts a document, downstream code is entitled
    # to assume grounding is sound and skip re-checking it.
    @model_validator(mode="after")
    def valid_grounding(self) -> NativeDocument:
        unit_ids = {unit.id for unit in self.units}
        element_ids = {element.id for element in self.elements}
        asset_ids = {asset.id for asset in self.assets}
        if (
            len(unit_ids) != len(self.units)
            or len(element_ids) != len(self.elements)
            or len(asset_ids) != len(self.assets)
        ):
            raise ValueError("unit, element, and asset IDs must be unique")
        if element_ids & asset_ids:
            raise ValueError("element and asset IDs must not overlap")
        for element in self.elements:
            if element.source.element_id != element.id:
                raise ValueError("source span element_id must match its element")
            if element.source.end > len(self.base_text):
                raise ValueError("source span is outside base_text")
            if element.source.anchor.unit_id not in unit_ids:
                raise ValueError("source anchor references an unknown unit")
        for asset in self.assets:
            if asset.anchor.unit_id not in unit_ids:
                raise ValueError("asset anchor references an unknown unit")
        return self

    def source_spans_for(self, start: int, end: int) -> list[SourceSpan]:
        if start < 0 or end <= start or end > len(self.base_text):
            raise ValueError("source range must be within base_text")
        # Half-open interval overlap test: two [start, end) ranges overlap
        # iff each starts before the other ends. Using <=/>= here would
        # incorrectly count adjacent, non-overlapping spans as overlapping.
        return sorted(
            (
                element.source
                for element in self.elements
                if element.source.start < end and element.source.end > start
            ),
            key=lambda span: (span.start, span.end, span.element_id),
        )


@dataclass(frozen=True, slots=True)
class PreviewArtifact:
    media_type: Literal["application/pdf", "text/html"]
    content: bytes | str


@dataclass(slots=True)
class NativeParseResult:
    document: NativeDocument
    markdown: str
    json: str
    annotated_pdf: bytes | None = None
    preview: PreviewArtifact | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    usage: RunUsage = field(default_factory=RunUsage)
    trace: list[AgentTraceEvent] = field(default_factory=list)


@dataclass(slots=True)
class NativeExtractionResult:
    schema: StoredSchema
    schema_fingerprint: str
    data: dict[str, Any]
    values: list[NativeExtractedValue]
    evidence: dict[str, list[dict[str, Any]]]
    json: str
    warnings: list[str] = field(default_factory=list)
    usage: RunUsage = field(default_factory=RunUsage)
    trace: list[AgentTraceEvent] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RenderedNativeDocument:
    markdown: str
    json: str


def render_native_document(
    document: NativeDocument,
    *,
    markdown: str,
) -> RenderedNativeDocument:
    # "5.0.0"/"5.1.0" below are the public native-document JSON contract
    # versions (see docs/architecture.md); bump deliberately, not silently,
    # on any shape change consumers could depend on.
    payload = {
        "schema_version": "5.0.0",
        "markdown": markdown,
        "base_text": document.base_text,
        "metadata": {
            "source_name": document.source_name,
            "source_sha256": document.source_sha256,
            "source_format": document.source_format.value,
            "requested_processing_type": document.requested_processing_type.value,
            "range_units": "unicode_codepoints",
            "range_target": "base_text",
            "warnings": document.warnings,
            "content_range": (
                document.content_range.model_dump(mode="json")
                if document.content_range is not None
                else None
            ),
        },
        "elements": [element.model_dump(mode="json") for element in document.elements],
        "assets": [asset.model_dump(mode="json") for asset in document.assets],
        "document": {
            "id": "document",
            "units": [unit.model_dump(mode="json") for unit in document.units],
        },
    }
    return RenderedNativeDocument(
        markdown=markdown,
        json=json.dumps(payload, ensure_ascii=False, indent=2),
    )


def render_native_combined_result(
    parse_result: NativeParseResult,
    extraction: NativeExtractionResult | None = None,
) -> str:
    payload = json.loads(parse_result.json)
    payload["schema_version"] = "5.1.0"  # combined native + extraction contract
    payload["extraction"] = (
        json.loads(extraction.json) if extraction is not None else None
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)
