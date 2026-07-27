from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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
    LAYOUT_TEXT = "layout_text_specialist"
    TABLE_FORM = "table_form_specialist"
    VISUAL = "visual_specialist"
    EVIDENCE_CRITIC = "evidence_critic"


class CheckboxState(StrEnum):
    CHECKED = "checked"
    UNCHECKED = "unchecked"
    INDETERMINATE = "indeterminate"
    UNKNOWN = "unknown"


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


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    bbox: BoundingBox | None = None


class ConfidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int
    end: int


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
    confidence: float = Field(default=0.5, ge=0, le=1)
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
    summary: str | None = None


class SchemaProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str
    json_schema: dict
    usage: RunUsage = Field(default_factory=RunUsage)


class SchemaProposalWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_text: str


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
    confidence: float = Field(default=0.5, ge=0, le=1)
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


class SpecialistOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str
    model: str
    timestamp: datetime
    decision: InspectionDecision
    confidence: float = Field(default=0.5, ge=0, le=1)
    reasoning: str = ""


class SpecialistResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    outcome: str
    final_decision: InspectionDecision | None = None
    reasoning: str = ""


class SpecialistAdditionOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str
    model: str
    timestamp: datetime
    addition: InspectionRegionAddition


class SpecialistAdditionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_id: str
    outcome: str
    proposal_region_ids: list[str] = Field(default_factory=list)
    final_addition: InspectionRegionAddition | None = None
    reasoning: str = ""


class SpecialistOrderingOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer: str
    model: str
    timestamp: datetime
    ordered_region_ids: list[str] = Field(default_factory=list)


class SpecialistOrderingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    ordered_region_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""


class SpecialistAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opinions: list[SpecialistOpinion] = Field(default_factory=list)
    resolutions: list[SpecialistResolution] = Field(default_factory=list)
    addition_opinions: list[SpecialistAdditionOpinion] = Field(default_factory=list)
    addition_resolutions: list[SpecialistAdditionResolution] = Field(default_factory=list)
    ordering_opinions: list[SpecialistOrderingOpinion] = Field(default_factory=list)
    ordering_resolution: SpecialistOrderingResolution | None = None


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
    specialist_audit: SpecialistAudit = Field(default_factory=SpecialistAudit)
    warnings: list[str] = Field(default_factory=list)
    quality: PageQuality = Field(default_factory=PageQuality)


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.3.0"
    source_name: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: list[Page]
    warnings: list[str] = Field(default_factory=list)


class AgentDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    target_region_ids: list[str] = Field(default_factory=list)
    use_terra: bool = False
    reason: str


class PagePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delegations: list[AgentDelegation] = Field(default_factory=list)
    finish: bool = False
    summary: str = ""


@dataclass(frozen=True, slots=True)
class CropInspectionRequest:
    crop_path: str
    region_id: str
    candidate_region: RegionDraft
    evidence_ref: str


class ProgressEvent(BaseModel):
    stage: str
    current: int
    total: int
    message: str


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass(slots=True)
class ParseResult:
    document: Document
    markdown: str
    json: str
    input_tokens: int
    output_tokens: int
    annotated_pdf: bytes
    legacy_json: str = ""
    usage: RunUsage | None = None
    trace: list[AgentTraceEvent] | None = None
