from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class NodeType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FIGURE = "figure"
    IMAGE = "image"
    CHART = "chart"
    FORM_FIELD = "form_field"
    CHECKBOX = "checkbox"
    LIST = "list"
    LIST_ITEM = "list_item"
    HEADER = "header"
    FOOTER = "footer"
    CAPTION = "caption"
    FORMULA = "formula"
    FOOTNOTE = "footnote"
    SIDEBAR = "sidebar"
    SIGNATURE = "signature"
    SEAL = "seal"
    REFERENCE = "reference"


class VerificationState(StrEnum):
    NOT_CHECKED = "not_checked"
    VERIFIED = "verified"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class InspectionAction(StrEnum):
    ACCEPT = "accept"
    CORRECT = "correct"
    REJECT = "reject"
    INSPECT_CROP = "inspect_crop"


class AgentRole(StrEnum):
    EVIDENCE_CRITIC = "evidence_critic"


class CheckboxState(StrEnum):
    CHECKED = "checked"
    UNCHECKED = "unchecked"
    INDETERMINATE = "indeterminate"
    UNKNOWN = "unknown"


class PageComplexity(StrEnum):
    BLANK_PAGE = "blank_page"
    SIMPLE_TEXT_PAGE = "simple_text_page"
    SIMPLE_TEXT_REGIONS = "simple_text_regions"
    COMPLEX_LAYOUT = "complex_layout"
    TABLE_OR_FORM_HEAVY = "table_or_form_heavy"
    VISUAL_HEAVY = "visual_heavy"
    LOW_QUALITY_SCAN = "low_quality_scan"
    UNCERTAIN = "uncertain"


class RegionComplexity(StrEnum):
    SIMPLE_TEXT = "simple_text"
    STRUCTURED = "structured"
    VISUAL = "visual"
    ROTATED = "rotated"
    LOW_QUALITY = "low_quality"
    UNCERTAIN = "uncertain"


class AnalysisRegionType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    FORM = "form"
    FIGURE = "figure"
    FORMULA = "formula"
    ROTATED_TEXT = "rotated_text"
    UNKNOWN = "unknown"


class ReadingOrderStatus(StrEnum):
    CONFIDENT = "confident"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    unit: str = "normalized"

    @model_validator(mode="after")
    def ordered(self) -> BoundingBox:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bounding box coordinates must be ordered")
        if self.unit != "normalized":
            raise ValueError("bounding boxes must use normalized coordinates")
        return self


class DraftBoundingBox(BaseModel):
    """Provider wire box; coordinate relationships are validated locally."""

    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)


class CoordinateBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    unit: str

    @model_validator(mode="after")
    def ordered(self) -> CoordinateBox:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("coordinate box values must be ordered")
        return self


class BoundingBoxProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized: BoundingBox
    rendered: CoordinateBox
    source: CoordinateBox
    source_page: int = Field(ge=1)


class PageRenderEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    render_width_pixels: int = Field(gt=0)
    render_height_pixels: int = Field(gt=0)
    render_dpi: float | None = Field(default=None, gt=0)
    effective_dpi: float | None = Field(default=None, gt=0)
    source_page: int = Field(ge=1)
    source_width: float = Field(gt=0)
    source_height: float = Field(gt=0)
    source_unit: str
    source_rotation_degrees: int = Field(default=0)


class QualityMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    value: float
    threshold: float
    warning: bool = False
    basis: str


class ScanQualityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blank: bool = False
    measurements: list[QualityMeasurement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LayoutRegionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    native_label: str
    type: AnalysisRegionType
    bbox: BoundingBoxProvenance
    polygon_rendered: list[tuple[float, float]] = Field(default_factory=list)
    text: str = ""
    layout_confidence: float | None = Field(default=None, ge=0, le=1)
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    rotation_degrees: float = 0.0
    complexity: RegionComplexity = RegionComplexity.UNCERTAIN


class ReadingOrderEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReadingOrderStatus = ReadingOrderStatus.UNAVAILABLE
    ordered_region_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    ambiguous_groups: list[list[str]] = Field(default_factory=list)
    basis: str = ""


class DetectedPageFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tables: list[str] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    multi_column_clusters: list[list[str]] = Field(default_factory=list)
    rotated_regions: list[str] = Field(default_factory=list)


class AnalysisEngineEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sdk: str = "glmocr"
    sdk_version: str | None = None
    layout_model: str = "PaddlePaddle/PP-DocLayoutV3_safetensors"
    ocr_model: str = "zai-org/GLM-OCR"
    layout_device: str = "cuda:0"
    latency_ms: int = Field(default=0, ge=0)


class PageAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    render: PageRenderEvidence
    quality: ScanQualityEvidence
    regions: list[LayoutRegionEvidence] = Field(default_factory=list)
    reading_order: ReadingOrderEvidence = Field(default_factory=ReadingOrderEvidence)
    features: DetectedPageFeatures = Field(default_factory=DetectedPageFeatures)
    complexity: PageComplexity = PageComplexity.UNCERTAIN
    engine: AnalysisEngineEvidence = Field(default_factory=AnalysisEngineEvidence)
    warnings: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    bbox: BoundingBox | None = None


class ConfidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = None
    bbox: BoundingBox | None = None


class TableCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    text: str = ""
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    header: bool = False
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    low_confidence_spans: list[ConfidenceSpan] = Field(default_factory=list)


class TableData(BaseModel):
    cells: list[TableCell] = Field(default_factory=list)


class FormData(BaseModel):
    label: str
    value: str | None = None
    hint: str | None = None


class ChartPoint(BaseModel):
    label: str
    value: str
    series: str | None = None


class AtomicEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    text: str
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    low_confidence_spans: list[ConfidenceSpan] = Field(default_factory=list)


class CorrectionLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_id: str
    replacement_id: str | None = None
    provider_id: str | None = None
    reason: str
    previous_state: VerificationState
    final_state: VerificationState


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    text: str = ""
    bbox: BoundingBox | None = None
    reading_order: int = Field(ge=0)
    confidence: float | None = Field(default=0.5, ge=0, le=1)
    verification: VerificationState = VerificationState.NOT_CHECKED
    verification_reason: str | None = None
    citation: Citation | None = None
    section_path: list[str] = Field(default_factory=list)
    children: list[Block] = Field(default_factory=list)
    heading_level: int | None = Field(default=None, ge=1, le=6)
    list_marker: str | None = None
    table: TableData | None = None
    form: FormData | None = None
    checkbox_state: CheckboxState | None = None
    checkbox_group: str | None = None
    checkbox_option: str | None = None
    caption: str | None = None
    figure_description: str | None = None
    chart_type: str | None = None
    chart_data: list[ChartPoint] = Field(default_factory=list)
    atoms: list[AtomicEvidence] = Field(default_factory=list)
    correction_lineage: list[CorrectionLineage] = Field(default_factory=list)


class AgentUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class RunUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: list[AgentUsage] = Field(default_factory=list)

    @computed_field
    @property
    def input_tokens(self) -> int:
        return sum(call.input_tokens for call in self.calls)

    @computed_field
    @property
    def output_tokens(self) -> int:
        return sum(call.output_tokens for call in self.calls)


class AgentTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    model: str
    action: str
    status: str
    page: int | None = Field(default=None, ge=1)
    target_ids: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    image_scope: str = "none"
    image_count: int = Field(default=0, ge=0)
    image_pixels: int = Field(default=0, ge=0)
    source_page_pixels: int = Field(default=0, ge=0)
    repair_round: int | None = Field(default=None, ge=1)
    prompt_version: str | None = None
    reasoning_effort: str | None = None
    summary: str | None = None


class RuntimeDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(default=0, ge=0)
    full_page_fallbacks: int = Field(default=0, ge=0)
    http_attempts: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    rate_limit_events: int = Field(default=0, ge=0)
    configured_concurrency: int = Field(ge=1)
    effective_concurrency: int = Field(ge=1)
    cooldown_until: float
    elapsed_seconds: float = Field(default=0, ge=0)
    limiter_wait_seconds: float = Field(default=0, ge=0)
    retry_sleep_seconds: float = Field(default=0, ge=0)


class SchemaProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str
    json_schema: dict
    usage: RunUsage = Field(default_factory=RunUsage)


class SchemaProposalWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_text: str


class SchemaField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    description: str = ""
    type: Literal["string", "number", "integer", "boolean", "date"] = "string"


class StoredSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    fields: list[SchemaField]

    @model_validator(mode="after")
    def unique_fields(self) -> StoredSchema:
        names = [field.name.casefold() for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("schema field names must be unique")
        if not names:
            raise ValueError("schema requires at least one field")
        return self


class ChatSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str
    page: int = Field(ge=1)
    text: str


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: object | None = None
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    confidence: Literal["high", "medium", "inferred", "not_found"]
    element_id: str | None = None
    source_text: str | None = None


class DocumentClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_type: Literal[
        "Invoice",
        "Contract",
        "Bank Statement",
        "Report",
        "Form",
        "Certificate",
        "Letter",
        "Other",
    ]
    confidence: float = Field(ge=0, le=1)
    secondary_types: list[str] = Field(default_factory=list)
    reasoning: str = ""


class TocSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    level: int = Field(ge=1, le=6)
    page: int = Field(ge=1)
    element_id: str | None = None
    children: list[TocSection] = Field(default_factory=list)


class TableOfContents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[TocSection] = Field(default_factory=list)


class ChatAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    usage: RunUsage = Field(default_factory=RunUsage)
    trace: list[AgentTraceEvent] = Field(default_factory=list)


class ChatCitationWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str


class ChatAnswerWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[ChatCitationWire] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class VisualRecoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    page: int = Field(ge=1)
    original_element_id: str | None = None
    status: Literal["recovered"] = "recovered"
    recovered_text: str
    confidence: Literal["high", "medium", "low"]
    notes: str = ""


class AgenticFeatureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["off", "unavailable", "succeeded", "partial", "failed"]
    duration_ms: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class AgenticAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: DocumentClassification | None = None
    toc: TableOfContents | None = None
    features: dict[str, AgenticFeatureMetadata] = Field(default_factory=dict)
    usage: RunUsage = Field(default_factory=RunUsage)
    trace: list[AgentTraceEvent] = Field(default_factory=list)


@dataclass(slots=True)
class ExtractionResult:
    data: dict
    evidence: dict[str, list[dict]]
    json: str
    warnings: list[str]
    input_tokens: int
    output_tokens: int
    usage: RunUsage
    trace: list[AgentTraceEvent]
    fields: dict[str, ExtractedField] = field(default_factory=dict)


class TableCellDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    text: str = ""
    bbox: DraftBoundingBox | None = None
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    header: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    low_confidence_spans: list[ConfidenceSpan] = Field(default_factory=list)


class AtomicDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    text: str
    bbox: DraftBoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    low_confidence_spans: list[ConfidenceSpan] = Field(default_factory=list)


class RegionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: NodeType
    bbox: DraftBoundingBox | None = None
    reading_order: int = Field(ge=0)
    text: str = ""
    confidence: float | None = Field(default=0.5, ge=0, le=1)
    heading_level: int | None = Field(default=None, ge=1, le=6)
    list_marker: str | None = None
    table_cells: list[TableCellDraft] = Field(default_factory=list)
    form: FormData | None = None
    checkbox_state: CheckboxState | None = None
    checkbox_group: str | None = None
    checkbox_option: str | None = None
    caption: str | None = None
    figure_description: str | None = None
    chart_type: str | None = None
    chart_data: list[ChartPoint] = Field(default_factory=list)
    atoms: list[AtomicDraft] = Field(default_factory=list)


class PageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[RegionDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class InspectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    action: InspectionAction
    corrected_region: RegionDraft | None = None
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    geometry_only: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class InspectionRegionAddition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    region: RegionDraft
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class PageInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[InspectionDecision] = Field(default_factory=list)
    additional_regions: list[InspectionRegionAddition] = Field(default_factory=list)
    ordered_region_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SpanRepairAction(StrEnum):
    CONFIRM = "confirm"
    REPLACE = "replace"
    UNRESOLVED = "unresolved"


class SpanRepairTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    region_id: str
    owner_kind: str
    owner_index: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str
    context_before: str = ""
    context_after: str = ""
    confidence: float = Field(ge=0, le=1)
    source: str
    bbox: BoundingBox | None = None
    evidence_ref: str


class SpanRepairDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str
    action: SpanRepairAction
    replacement_text: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str = ""
    evidence_ref: str

    @model_validator(mode="after")
    def valid_replacement(self) -> SpanRepairDecision:
        if self.action is SpanRepairAction.REPLACE and self.replacement_text is None:
            raise ValueError("replace decisions require replacement_text")
        if (
            self.action is not SpanRepairAction.REPLACE
            and self.replacement_text is not None
        ):
            raise ValueError("only replace decisions may include replacement_text")
        return self


class SpanRepairInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[SpanRepairDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PageQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_coverage: float = Field(default=1.0, ge=0, le=1)
    coverage_threshold: float = Field(default=1.0, ge=0, le=1)
    needs_review_reasons: list[str] = Field(default_factory=list)


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    blocks: list[Block] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    quality: PageQuality = Field(default_factory=PageQuality)
    analysis: PageAnalysis | None = None


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: list[Page]
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CropInspectionRequest:
    crop_path: str
    region_id: str
    candidate_region: RegionDraft
    evidence_ref: str
    source_page_pixels: int = 0


@dataclass(frozen=True, slots=True)
class SpanRepairRequest:
    crop_path: str
    target: SpanRepairTarget
    source_page_pixels: int = 0


class ProgressEvent(BaseModel):
    stage: str
    current: int
    total: int
    message: str


ProgressCallback = Callable[[ProgressEvent], None]


class PresentationDirective(BaseModel):
    """Text-free Luna instruction for deterministic Markdown presentation."""

    model_config = ConfigDict(extra="forbid")

    element_id: str
    render_as: Literal["source", "heading", "paragraph", "list_item", "caption"] = (
        "source"
    )
    heading_level: int | None = Field(default=None, ge=1, le=6)
    list_depth: int | None = Field(default=None, ge=0, le=6)
    group_with_previous: bool = False

    @model_validator(mode="after")
    def validate_options(self) -> PresentationDirective:
        if self.heading_level is not None and self.render_as != "heading":
            raise ValueError("heading_level requires render_as=heading")
        if self.list_depth is not None and self.render_as != "list_item":
            raise ValueError("list_depth requires render_as=list_item")
        return self


class PagePresentationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    elements: list[PresentationDirective]


class MarkdownPresentationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: list[PagePresentationPlan]


class EnhancementMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    status: Literal["off", "unavailable", "succeeded", "partial", "failed"] = (
        "off"
    )
    model: str = "gpt-5.6-luna"
    chunks_total: int = Field(default=0, ge=0)
    chunks_enhanced: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class Element(BaseModel):
    """Engine-neutral, layout-aware document element."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None
    text: str = ""
    reading_order: int = Field(ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal["glm-ocr", "luna-recovery"] = "glm-ocr"

    @model_validator(mode="after")
    def validate_bbox(self) -> Element:
        if self.bbox is None:
            return self
        x0, y0, x1, y1 = self.bbox
        if not all(0 <= value <= 1 for value in self.bbox):
            raise ValueError("bbox coordinates must be normalized between 0 and 1")
        if x1 < x0 or y1 < y0:
            raise ValueError("bbox coordinates must be ordered")
        return self


class ParseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str = "glm-ocr"
    pages: int = Field(default=0, ge=0)
    processing_time: float = Field(default=0.0, ge=0)
    visual_parse_time: float = Field(default=0.0, ge=0)
    refinement_time: float = Field(default=0.0, ge=0)
    visual_recovery_request_time: float = Field(default=0.0, ge=0)
    visual_recovery_enabled: bool = True
    visual_recovery_candidates: int = Field(default=0, ge=0)
    visual_recovery_crops: int = Field(default=0, ge=0)
    visual_recovery_deferred: int = Field(default=0, ge=0)
    visual_recovery_region_ids: list[str] = Field(default_factory=list)
    glm_time: float = Field(default=0.0, ge=0)
    luna_recovery_time: float = Field(default=0.0, ge=0)
    luna_agentic_time: float = Field(default=0.0, ge=0)
    luna_time: float = Field(default=0.0, ge=0)
    recovered_regions: int = Field(default=0, ge=0)
    model_versions: dict[str, str] = Field(default_factory=dict)
    enhancement: EnhancementMetadata = Field(default_factory=EnhancementMetadata)


@dataclass(slots=True)
class ParseResult:
    document: Document
    markdown: str
    json: str
    input_tokens: int
    output_tokens: int
    annotated_pdf: bytes
    base_markdown: str = ""
    usage: RunUsage | None = None
    trace: list[AgentTraceEvent] | None = None
    runtime_diagnostics: RuntimeDiagnostics | None = None
    elements: list[Element] = field(default_factory=list)
    metadata: ParseMetadata = field(default_factory=ParseMetadata)
    recovery_log: list[VisualRecoveryResult] = field(default_factory=list)

    @property
    def structured_json(self) -> dict:
        payload = json.loads(self.json)
        if not isinstance(payload, dict):
            raise TypeError("parse result JSON must contain an object")
        return payload
