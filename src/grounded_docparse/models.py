from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NodeType(StrEnum):
    DOCUMENT = "Document"
    PAGE = "Page"
    SECTION = "Section"
    HEADING = "Heading"
    PARAGRAPH = "Paragraph"
    TABLE = "Table"
    TABLE_ROW = "TableRow"
    TABLE_CELL = "TableCell"
    FIGURE = "Figure"
    CAPTION = "Caption"
    FORMULA = "Formula"
    LIST = "List"
    LIST_ITEM = "ListItem"
    HEADER = "Header"
    FOOTER = "Footer"
    SIDEBAR = "Sidebar"
    FOOTNOTE = "Footnote"
    REFERENCE = "Reference"
    IMAGE = "Image"
    CHART = "Chart"
    FORM_FIELD = "FormField"
    CHECKBOX = "Checkbox"
    SIGNATURE = "Signature"
    SEAL = "Seal"
    OCR_BLOCK = "OCRBlock"


class ProcessingProfile(StrEnum):
    LOCAL_ONLY = "local-only"
    HYBRID = "hybrid"
    MAXIMUM_ACCURACY = "maximum-accuracy"


class SegmentationMode(StrEnum):
    AUTO = "auto"
    OFF = "off"


class DocumentProfile(StrEnum):
    AUTO = "auto"
    GENERIC = "generic"
    TECHNICAL_DOCUMENTATION = "technical-documentation"
    SCIENTIFIC_PAPER = "scientific-paper"
    INVOICE = "invoice"
    INSURANCE_CLAIM = "insurance-claim"
    HEALTHCARE_FORM = "healthcare-form"
    PURCHASE_ORDER = "purchase-order"
    RECEIPT = "receipt"
    CONTRACT = "contract"
    CORRESPONDENCE = "correspondence"
    GENERIC_FORM = "generic-form"
    ATTACHMENT_UNKNOWN = "attachment-unknown"
    MIXED_BATCH = "mixed-batch"


class GroundingScope(StrEnum):
    EXACT = "exact"
    TABLE = "table"
    AGGREGATE = "aggregate"
    UNRESOLVED = "unresolved"


class BoundingBox(BaseModel):
    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    unit: str = "normalized"

    @model_validator(mode="after")
    def valid_normalized_range(self) -> BoundingBox:
        if self.unit == "normalized" and max(self.x0, self.y0, self.x1, self.y1) > 1:
            raise ValueError("normalized coordinates must be <= 1")
        return self

    @field_validator("x1")
    @classmethod
    def valid_x(cls, value: float, info: Any) -> float:
        if "x0" in info.data and value < info.data["x0"]:
            raise ValueError("x1 must be >= x0")
        return value

    @field_validator("y1")
    @classmethod
    def valid_y(cls, value: float, info: Any) -> float:
        if "y0" in info.data and value < info.data["y0"]:
            raise ValueError("y1 must be >= y0")
        return value


class Confidence(BaseModel):
    score: float = Field(ge=0, le=1)
    level: str
    calibration: str = "heuristic-v1"
    signals: dict[str, float] = Field(default_factory=dict)


class Provenance(BaseModel):
    source: str
    source_ref: str | None = None
    literal: bool = True
    model: str | None = None
    prompt_version: str | None = None


class Relationship(BaseModel):
    type: str
    target_id: str
    confidence: float = Field(default=1, ge=0, le=1)


class DocumentLink(BaseModel):
    uri: str
    bbox: BoundingBox | None = None


class Citation(BaseModel):
    id: str
    source_node_id: str
    page_number: int | None = None
    segment_page_number: int | None = None
    bbox: BoundingBox | None = None
    source_bbox: BoundingBox | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_source: str
    grounding_scope: GroundingScope
    parent_citation_id: str | None = None


class FormFieldData(BaseModel):
    label: str = Field(max_length=10_000)
    value: str = Field(default="", max_length=100_000)
    field_kind: str = "text"
    state: str | None = None
    label_node_id: str | None = None
    value_node_id: str | None = None


class VisualDataPoint(BaseModel):
    label: str | None = Field(default=None, max_length=1_000)
    value: str = Field(max_length=10_000)
    series: str | None = Field(default=None, max_length=1_000)
    source_text: str | None = Field(default=None, max_length=10_000)


class VisualAnalysis(BaseModel):
    kind: str
    literal_text: str = Field(default="", max_length=100_000)
    title: str | None = Field(default=None, max_length=10_000)
    chart_type: str | None = Field(default=None, max_length=1_000)
    axes: list[str] = Field(default_factory=list, max_length=20)
    legends: list[str] = Field(default_factory=list, max_length=100)
    data_points: list[VisualDataPoint] = Field(default_factory=list, max_length=10_000)
    derived_summary: str | None = Field(default=None, max_length=20_000)
    summary_literal: bool = False
    source_node_ids: list[str] = Field(default_factory=list, max_length=1_000)
    confidence: float = Field(default=0.5, ge=0, le=1)


class RecognitionCandidate(BaseModel):
    id: str
    source: str
    task: str
    prompt_version: str
    pass_number: int = Field(ge=0, le=2)
    text: str = Field(max_length=100_000)
    bbox: BoundingBox | None = None
    validation_signals: dict[str, float] = Field(default_factory=dict)


class RegionEvidence(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    page_number: int
    type: NodeType
    bbox: BoundingBox | None = None
    reading_order: int
    semantic_role: str | None = None
    candidates: list[RecognitionCandidate] = Field(default_factory=list, max_length=10)
    agreement_score: float = Field(default=0, ge=0, le=1)
    verification_status: str = "unverified"
    selected_candidate_id: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    attributes: dict[str, Any] = Field(default_factory=dict)


class VerificationDecision(BaseModel):
    region_id: str
    selected_candidate_id: str | None = None
    proposed_text: str | None = Field(default=None, max_length=100_000)
    semantic_role: str | None = None
    needs_retry: bool = False


class PageVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[VerificationDecision] = Field(
        default_factory=list, max_length=1_000
    )
    warnings: list[str] = Field(default_factory=list, max_length=1_000)


class DocumentNode(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    type: NodeType
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    page_number: int | None = None
    bbox: BoundingBox | None = None
    source_bbox: BoundingBox | None = None
    reading_order: int | None = None
    semantic_role: str | None = None
    text: str | None = None
    markdown: str | None = None
    confidence: Confidence | None = None
    provenance: list[Provenance] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    links: list[DocumentLink] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    recognition_candidates: list[RecognitionCandidate] = Field(default_factory=list)
    agreement_score: float | None = Field(default=None, ge=0, le=1)
    verification_status: str | None = None
    selected_candidate_id: str | None = None
    citations: list[Citation] = Field(default_factory=list, max_length=10_000)
    form_field: FormFieldData | None = None
    visual_analysis: VisualAnalysis | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class PageRecord(BaseModel):
    id: str
    number: int
    segment_page_number: int | None = None
    width: float
    height: float
    dpi: int
    scanned: bool
    content_node_ids: list[str] = Field(default_factory=list)


class RunRecord(BaseModel):
    provider: str
    model: str
    stage: str
    page_number: int | None = None
    region_id: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    prompt_version: str | None = None


class DocumentClassification(BaseModel):
    profile: DocumentProfile
    domain: str
    confidence: float = Field(ge=0, le=1)
    method: str
    source_node_ids: list[str] = Field(default_factory=list, max_length=1_000)


class FieldSource(BaseModel):
    node_id: str
    page_number: int | None = None
    bbox: BoundingBox | None = None
    source_bbox: BoundingBox | None = None


class GroundedField(BaseModel):
    path: str
    raw_value: str = Field(max_length=100_000)
    normalized_value: str | None = Field(default=None, max_length=100_000)
    source_node_ids: list[str] = Field(min_length=1, max_length=1_000)
    sources: list[FieldSource] = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0, le=1)
    status: str = "literal"


class ValueCitation(BaseModel):
    citation_id: str
    node_id: str
    page_number: int | None = None
    segment_page_number: int | None = None
    bbox: BoundingBox | None = None
    source_bbox: BoundingBox | None = None
    grounding_scope: GroundingScope
    confidence: float = Field(default=0.5, ge=0, le=1)
    logical_table_id: str | None = None
    row_index: int | None = Field(default=None, ge=0)
    column_name: str | None = None


class ExtractionProvenance(BaseModel):
    path: str
    citations: list[ValueCitation] = Field(min_length=1, max_length=10_000)
    confidence: float = Field(ge=0, le=1)
    status: str = "literal"
    method: str = "deterministic"


class LogicalTable(BaseModel):
    id: str
    source_table_node_ids: list[str] = Field(min_length=1, max_length=1_000)
    column_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    header_rows: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.5, ge=0, le=1)
    status: str = "physical"


class SchemaExtraction(BaseModel):
    schema_version: str = "1.0.0"
    schema_name: str
    schema_sha256: str
    document_id: str
    subdocument_id: str | None = None
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, ExtractionProvenance] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list, max_length=10_000)


class ExtractionSelection(BaseModel):
    path: str = Field(max_length=2_000)
    source_node_ids: list[str] = Field(min_length=1, max_length=100)
    literal_value: str = Field(max_length=100_000)
    confidence: float = Field(ge=0, le=1)


class ExtractionDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selections: list[ExtractionSelection] = Field(default_factory=list, max_length=2_000)


class ValidationFinding(BaseModel):
    code: str
    severity: str
    message: str = Field(max_length=10_000)
    field_paths: list[str] = Field(default_factory=list, max_length=100)
    source_node_ids: list[str] = Field(default_factory=list, max_length=1_000)


class WindowRun(BaseModel):
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    attempts: int = Field(default=1, ge=1)
    status: str


class FailureCase(BaseModel):
    schema_version: str = "1.0.0"
    id: str
    code: str = Field(max_length=100)
    stage: str = Field(max_length=100)
    severity: Literal["error", "warning", "info"]
    outcome: Literal["unresolved", "degraded", "recovered"]
    scope: Literal["document", "page", "region", "node"]
    message: str = Field(max_length=1_000)
    page_number: int | None = Field(default=None, ge=1)
    segment_page_number: int | None = Field(default=None, ge=1)
    region_id: str | None = Field(default=None, max_length=1_000)
    node_ids: list[str] = Field(default_factory=list, max_length=1_000)
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    attempt: int | None = Field(default=None, ge=1)
    exception_type: str | None = Field(default=None, max_length=200)
    evidence_refs: list[str] = Field(default_factory=list, max_length=1_000)


class AdaptiveRetryRecord(BaseModel):
    id: str
    scope: Literal["page", "region"]
    page_number: int = Field(ge=1)
    region_id: str | None = None
    trigger_codes: list[str] = Field(default_factory=list, max_length=20)
    providers: list[str] = Field(default_factory=list, max_length=10)
    dpi: int = Field(ge=72, le=1200)
    crop_padding: float = Field(default=0, ge=0, le=0.5)
    before_score: float = Field(ge=0, le=1)
    after_score: float | None = Field(default=None, ge=0, le=1)
    outcome: Literal["applied", "rejected", "failed"]
    selected_candidate_id: str | None = None


class QualityReport(BaseModel):
    schema_version: str = "1.0.0"
    document_id: str
    source_sha256: str
    summary: dict[str, Any]
    pages: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


class IdentifierEvidence(BaseModel):
    kind: str
    value: str = Field(max_length=10_000)
    normalized_value: str = Field(max_length=10_000)
    page_number: int = Field(ge=1)
    node_id: str
    bbox: BoundingBox | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    primary: bool = False


class PageClassification(BaseModel):
    page_number: int = Field(ge=1)
    profile: DocumentProfile
    confidence: float = Field(ge=0, le=1)
    source_node_ids: list[str] = Field(default_factory=list, max_length=1_000)
    identifiers: list[IdentifierEvidence] = Field(default_factory=list, max_length=1_000)


class BoundaryDecision(BaseModel):
    before_page: int = Field(ge=2)
    score: float = Field(ge=0, le=1)
    decision: str
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list, max_length=100)
    adjudication: str = "deterministic"


class BoundaryAdjudication(BaseModel):
    decision: str
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=2_000)

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        if value not in {"split", "keep", "uncertain"}:
            raise ValueError("decision must be split, keep, or uncertain")
        return value


class SubdocumentDescriptor(BaseModel):
    id: str
    index: int = Field(ge=1)
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    profile: DocumentProfile
    confidence: float = Field(ge=0, le=1)
    instance_key: str | None = None
    identifiers: list[IdentifierEvidence] = Field(default_factory=list, max_length=10_000)
    related_segment_ids: list[str] = Field(default_factory=list, max_length=1_000)
    warnings: list[str] = Field(default_factory=list, max_length=1_000)


class BatchManifest(BaseModel):
    schema_version: str = "1.0.0"
    batch_id: str
    source_name: str
    source_sha256: str
    page_count: int = Field(ge=1)
    processing_profile: ProcessingProfile
    page_classifications: list[PageClassification]
    boundaries: list[BoundaryDecision]
    subdocuments: list[SubdocumentDescriptor]


class DocumentTree(BaseModel):
    schema_version: str = "1.9.0"
    document_id: str
    source_name: str
    source_sha256: str
    processing_profile: ProcessingProfile = ProcessingProfile.LOCAL_ONLY
    root_id: str
    nodes: dict[str, DocumentNode]
    pages: list[PageRecord]
    assets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_runs: list[RunRecord] = Field(default_factory=list)
    document_classification: DocumentClassification | None = None
    grounded_fields: list[GroundedField] = Field(default_factory=list)
    logical_tables: list[LogicalTable] = Field(default_factory=list)
    schema_extractions: list[SchemaExtraction] = Field(default_factory=list)
    validation_findings: list[ValidationFinding] = Field(default_factory=list)
    window_runs: list[WindowRun] = Field(default_factory=list)
    failure_cases: list[FailureCase] = Field(default_factory=list)
    adaptive_retries: list[AdaptiveRetryRecord] = Field(default_factory=list)
    batch_manifest: BatchManifest | None = None


class ProgressEvent(BaseModel):
    stage: str
    current: int
    total: int
    message: str


ProgressCallback = Callable[[ProgressEvent], None]


class RegionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: NodeType
    bbox: BoundingBox | None = None
    reading_order: int
    semantic_role: str | None = None
    text: str = Field(default="", max_length=100_000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source_refs: list[str] = Field(default_factory=list, max_length=10)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def bounded_attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False, default=str)) > 1_000_000:
            raise ValueError("region attributes exceed size limit")
        return value

    @field_validator("bbox")
    @classmethod
    def normalized_bbox(cls, value: BoundingBox | None) -> BoundingBox | None:
        if value is not None and value.unit != "normalized":
            raise ValueError("region bbox must be normalized")
        return value


class PageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regions: list[RegionDraft] = Field(default_factory=list, max_length=1_000)
    warnings: list[str] = Field(default_factory=list, max_length=1_000)


class NodeUpdate(BaseModel):
    node_id: str
    semantic_role: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=6)


class RelationshipDraft(BaseModel):
    source_id: str
    target_id: str
    type: str
    confidence: float = Field(default=1, ge=0, le=1)


class DocumentResolution(BaseModel):
    updates: list[NodeUpdate] = Field(default_factory=list, max_length=1_000)
    relationships: list[RelationshipDraft] = Field(
        default_factory=list, max_length=1_000
    )
    warnings: list[str] = Field(default_factory=list, max_length=1_000)


class SubdocumentResult:
    def __init__(
        self,
        *,
        descriptor: SubdocumentDescriptor,
        markdown: str,
        llm_markdown: str,
        audit_json: str,
        json_text: str,
        tree: DocumentTree,
        source_pdf: bytes,
        bundle: bytes,
        extraction_json: str = "",
        table_exports: dict[str, bytes] | None = None,
        failures_jsonl: str = "",
        quality_json: str = "",
        annotated_pdf: bytes = b"",
    ) -> None:
        self.descriptor = descriptor
        self.markdown = markdown
        self.llm_markdown = llm_markdown
        self.audit_json = audit_json
        self.json = json_text
        self.tree = tree
        self.source_pdf = source_pdf
        self.bundle = bundle
        self.extraction_json = extraction_json
        self.table_exports = table_exports or {}
        self.failures_jsonl = failures_jsonl
        self.quality_json = quality_json
        self.annotated_pdf = annotated_pdf


class ParseResult:
    def __init__(
        self,
        *,
        markdown: str,
        llm_markdown: str,
        audit_json: str,
        json_text: str,
        tree: DocumentTree,
        assets: dict[str, bytes],
        bundle: bytes,
        batch_manifest_json: str = "",
        subdocuments: list[SubdocumentResult] | None = None,
        extraction_json: str = "",
        table_exports: dict[str, bytes] | None = None,
        failures_jsonl: str = "",
        quality_json: str = "",
        annotated_pdf: bytes = b"",
    ) -> None:
        self.markdown = markdown
        self.llm_markdown = llm_markdown
        self.audit_json = audit_json
        self.json = json_text
        self.tree = tree
        self.assets = assets
        self.bundle = bundle
        self.batch_manifest_json = batch_manifest_json
        self.subdocuments = subdocuments or []
        self.extraction_json = extraction_json
        self.table_exports = table_exports or {}
        self.failures_jsonl = failures_jsonl
        self.quality_json = quality_json
        self.annotated_pdf = annotated_pdf
