from __future__ import annotations

import html
import inspect
import os
import re
import tempfile
import time
import unicodedata
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from queue import Empty, SimpleQueue

from PIL import Image

from .config import LUNA_MODEL, OcrEngine, ParserConfig
from .enhancement import (
    build_enhancement_chunks,
    combine_page_markdown,
    render_chunk_plan,
)
from .gateways import OpenAIDocumentGateway
from .ingest import IngestedDocument, PageEvidence, ingest_document, render_region_crop
from .grounded_ocr import get_grounded_ocr_runtime
from .local_ocr import GlmPageResult, OcrPageResult
from .models import (
    AgentRole,
    AgentTraceEvent,
    AgentUsage,
    AnalysisRegionType,
    AtomicDraft,
    AtomicEvidence,
    Block,
    BoundingBox,
    Citation,
    ConfidenceSpan,
    CorrectionLineage,
    CropInspectionRequest,
    Document,
    DraftBoundingBox,
    EnhancementMetadata,
    FormData,
    InspectionAction,
    InspectionDecision,
    LayoutRegionEvidence,
    NodeType,
    OcrComparisonResult,
    Page,
    PageAnalysis,
    PageDraft,
    PageInspection,
    ParseMetadata,
    ParseResult,
    ProgressCallback,
    ProgressEvent,
    RegionDraft,
    RunUsage,
    SpanRepairAction,
    SpanRepairDecision,
    SpanRepairRequest,
    SpanRepairTarget,
    TableCell,
    TableCellDraft,
    TableData,
    VerificationState,
    VisualRecoveryResult,
)
from .ocr_disagreement import token_edit_similarity
from .ocr_services import ensure_managed_ocr_engine
from .paddle_ocr import get_paddleocr_runtime
from .page_analysis import PageAnalyzer, draft_from_analysis
from .quality import (
    MAX_REPAIR_BLOCKS,
    literal_repair_candidates,
    normalize_page_blocks,
    requires_region_repair,
    select_repair_blocks,
    semantic_text,
)
from .render import (
    build_elements,
    materialize_document_quality,
    render_agentic_document,
    render_annotated_pdf,
)
from .runtime import ProviderRuntime

VERIFICATION_CONFIDENCE_THRESHOLD = 0.85
MAX_CROPS_PER_PAGE = 8
MAX_VISUAL_RECOVERY_CROPS_PER_PAGE = 3
MIN_VISUAL_RECOVERY_CROPS_PER_DOCUMENT = 8
RECOVERY_OCR_CONFIDENCE_THRESHOLD = 0.75
RECOVERY_LARGE_REGION_AREA = 0.02
RECOVERY_MIN_CHARACTER_DENSITY = 50.0
RECOVERY_GARBAGE_RATIO = 0.35
RECOVERY_TABLE_QUALITY = 0.5
RECOVERY_OVERLAP_IOU = 0.5
RECOVERY_CONTAINMENT = 0.85
COMPLEX_REGION_TYPES = {
    NodeType.TABLE,
    NodeType.FORM_FIELD,
    NodeType.CHECKBOX,
    NodeType.FIGURE,
    NodeType.IMAGE,
    NodeType.CHART,
    NodeType.FORMULA,
    NodeType.SIGNATURE,
    NodeType.SEAL,
}


class _UnavailableGateway:
    """Preserve GLM parsing when Luna credentials are unavailable."""

    input_tokens = 0
    output_tokens = 0

    def __init__(self, reason: str = "OPENAI_API_KEY is not set") -> None:
        self.reason = reason
        self.usage = RunUsage()
        self.trace: list[AgentTraceEvent] = []

    def draft_page(self, _page: PageEvidence) -> PageDraft:
        return PageDraft(warnings=[f"Luna visual recovery unavailable: {self.reason}"])

    def inspect_crops(self, *_args, **_kwargs) -> PageInspection:
        return PageInspection(warnings=["Luna visual recovery unavailable"])


CRITICAL_LITERAL_PATTERN = re.compile(
    r"(?:\d|https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"
)
AMBIGUOUS_LITERAL_PATTERN = re.compile(
    r"(?:#{2,}|(?i:\b(?:id|no|number)2(?=\s+[A-Z0-9][A-Z0-9_-]{2,}\b)))"
)
_HTML_CELL_PATTERN = re.compile(
    r"(?is)<(?P<tag>td|th)(?P<attrs>\s[^>]*)?>(?P<body>.*?)</(?P=tag)>"
)
_HTML_ROW_PATTERN = re.compile(r"(?is)<tr(?:\s[^>]*)?>(?P<body>.*?)</tr>")
_CHECKBOX_PREFIX_PATTERN = re.compile(
    r"^\s*(?:\[(?P<bracket>[xX ?])\]|(?P<glyph>[☑✓✔☐□])|(?P<x>[xX])(?=\s+))\s*"
)
_RAW_CHECKBOX_PREFIX_PATTERN = re.compile(
    r"^\s*(?:\[[xX ?]\]|[☑✓✔☐□]|[xX](?=\s+))\s*"
)
_FORM_OPTION_LABELS = frozenset(
    {
        "participating",
        "nonparticipating",
        "outpatient",
        "planned inpatient",
        "emergent inpatient",
        "skilled nursing facility",
        "long-term services & supports/long-term care",
        "home health",
        "durable medical equipment",
        "diagnostic study",
        "hospice",
        "office visit",
        "personal care services",
        "hospital",
        "ambulatory surgery center",
        "office",
        "home",
        "independent lab",
        "nursing facility",
    }
)
VISUAL_REGION_TYPES = {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}
INVALID_CONFIDENCE_EVIDENCE_REASON = "Invalid confidence evidence"


@dataclass(frozen=True, slots=True)
class _RawHTMLCell:
    start: int
    end: int
    body: str
    text: str


def _visible_html(value: str) -> str:
    with_breaks = re.sub(r"(?i)<br\s*/?>", "\n", value)
    return " ".join(html.unescape(re.sub(r"(?s)<[^>]+>", " ", with_breaks)).split())


def _raw_html_cells(value: str) -> list[_RawHTMLCell]:
    return [
        _RawHTMLCell(
            start=match.start("body"),
            end=match.end("body"),
            body=match.group("body"),
            text=_visible_html(match.group("body")),
        )
        for match in _HTML_CELL_PATTERN.finditer(value)
    ]


def _checkbox_state_and_label(value: str) -> tuple[str | None, str]:
    match = _CHECKBOX_PREFIX_PATTERN.match(value)
    state = None
    if match is not None:
        token = match.group("bracket") or match.group("glyph") or match.group("x")
        if token in {"x", "X", "☑", "✓", "✔"}:
            state = "checked"
        elif token in {" ", "☐", "□"}:
            state = "unchecked"
        value = value[match.end() :]
    return state, " ".join(value.casefold().rstrip(":").split())


def _form_option(value: str) -> tuple[str | None, str | None]:
    state, label = _checkbox_state_and_label(value)
    return (state, label) if label in _FORM_OPTION_LABELS else (None, None)


def _option_states(value: str) -> dict[tuple[str, int], str | None]:
    counts: dict[str, int] = {}
    states: dict[tuple[str, int], str | None] = {}
    for cell in _raw_html_cells(value):
        state, label = _form_option(cell.text)
        if label is None:
            continue
        occurrence = counts.get(label, 0)
        counts[label] = occurrence + 1
        states[(label, occurrence)] = state
    return states


def _paddle_form_states(value: str) -> dict[tuple[str, int], str | None]:
    """Read explicit and standalone Paddle checkbox markers within table rows."""

    rows = [match.group("body") for match in _HTML_ROW_PATTERN.finditer(value)]
    if not rows:
        return _option_states(value)
    checked_markers = {"x", "☒", "☑", "✓", "✔"}
    unchecked_markers = {"☐", "□"}
    counts: dict[str, int] = {}
    states: dict[tuple[str, int], str | None] = {}
    for row in rows:
        pending: str | None = None
        for cell in _raw_html_cells(row):
            token = cell.text.strip().casefold()
            if token in checked_markers:
                pending = "checked"
                continue
            if token in unchecked_markers:
                pending = "unchecked"
                continue
            state, label = _form_option(cell.text)
            if label is None:
                pending = None
                continue
            occurrence = counts.get(label, 0)
            counts[label] = occurrence + 1
            states[(label, occurrence)] = state or pending
            pending = None

    occurrences = {
        occurrence
        for label, occurrence in states
        if label in {"participating", "nonparticipating"}
    }
    for occurrence in occurrences:
        participating = ("participating", occurrence)
        nonparticipating = ("nonparticipating", occurrence)
        if participating not in states or nonparticipating not in states:
            continue
        if states[participating] == "checked" and states[nonparticipating] is None:
            states[nonparticipating] = "unchecked"
        elif (
            states[nonparticipating] == "checked"
            and states[participating] is None
        ):
            states[participating] = "unchecked"
    return states


def _merge_confirmed_form_states(
    primary: str, confirmed: dict[tuple[str, int], str]
) -> tuple[str, int]:
    """Add only missing option states confirmed by independent Paddle passes."""

    cells = _raw_html_cells(primary)
    occurrences: dict[str, int] = {}
    replacements: dict[int, str] = {}
    for index, cell in enumerate(cells):
        primary_state, label = _form_option(cell.text)
        if label is None:
            continue
        occurrence = occurrences.get(label, 0)
        occurrences[label] = occurrence + 1
        state = confirmed.get((label, occurrence))
        if state is None or primary_state is not None:
            continue
        marker = {"checked": "[x]", "unchecked": "[ ]"}.get(state)
        if marker is None:
            continue
        cleaned = _RAW_CHECKBOX_PREFIX_PATTERN.sub("", cell.body, count=1)
        replacements[index] = f"{marker} {cleaned.lstrip()}"
    if not replacements:
        return primary, 0
    pieces: list[str] = []
    cursor = 0
    for index, cell in enumerate(cells):
        replacement = replacements.get(index)
        if replacement is None:
            continue
        pieces.extend((primary[cursor : cell.start], replacement))
        cursor = cell.end
    pieces.append(primary[cursor:])
    return "".join(pieces), len(replacements)


def _form_control_recovery_severity(value: str) -> int | None:
    unresolved = sum(state is None for state in _option_states(value).values())
    if unresolved >= 4:
        return 0
    if unresolved >= 2:
        return 1
    return 2 if unresolved else None


def _merge_form_html(primary: str, recovered: str) -> tuple[str, str, int]:
    """Add explicit control states and fill only structurally aligned blank cells."""

    primary_cells = _raw_html_cells(primary)
    if not primary_cells:
        return primary, "unchanged", 0
    recovered_cells = _raw_html_cells(recovered)
    recovered_states = _option_states(recovered)
    occurrences: dict[str, int] = {}
    replacements: dict[int, str] = {}
    resolved = unknown = conflicts = filled = 0

    for index, cell in enumerate(primary_cells):
        primary_state, label = _form_option(cell.text)
        if label is not None:
            occurrence = occurrences.get(label, 0)
            occurrences[label] = occurrence + 1
            recovery_state = recovered_states.get((label, occurrence))
            if primary_state and recovery_state and primary_state != recovery_state:
                state = None
                conflicts += 1
            else:
                state = recovery_state or primary_state
            marker = {"checked": "[x]", "unchecked": "[ ]"}.get(state, "[?]")
            cleaned = _RAW_CHECKBOX_PREFIX_PATTERN.sub("", cell.body, count=1)
            replacements[index] = f"{marker} {cleaned.lstrip()}"
            if state is None:
                unknown += 1
            else:
                resolved += 1
            continue

        if (
            not cell.text
            and index > 0
            and index < len(recovered_cells)
            and primary_cells[index - 1].text.rstrip().endswith(":")
            and recovered_cells[index - 1].text.casefold()
            == primary_cells[index - 1].text.casefold()
            and recovered_cells[index].text
        ):
            replacements[index] = html.escape(recovered_cells[index].text)
            filled += 1

    if not replacements:
        return primary, "unchanged", 0
    pieces: list[str] = []
    cursor = 0
    for index, cell in enumerate(primary_cells):
        replacement = replacements.get(index)
        if replacement is None:
            continue
        pieces.extend((primary[cursor : cell.start], replacement))
        cursor = cell.end
    pieces.append(primary[cursor:])
    status = (
        "conflict"
        if conflicts
        else "partial"
        if unknown and (resolved or filled)
        else "ambiguous"
        if unknown
        else "resolved"
    )
    return "".join(pieces), status, resolved + filled


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.translate(
        {ord("\u00ad"): None, ord("\u200b"): None, ord("\ufeff"): None}
    )


_REMOVED_TEXT_CODEPOINTS = frozenset({"\u00ad", "\u200b", "\ufeff"})


def _clean_form_data(value: FormData | None) -> FormData | None:
    if value is None:
        return None
    return FormData(
        label=_clean_text(value.label) or "Field",
        value=_clean_text(value.value),
        hint=_clean_text(value.hint),
    )


def _emit(
    callback: ProgressCallback | None,
    stage: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if callback is not None:
        callback(
            ProgressEvent(stage=stage, current=current, total=total, message=message)
        )


def _form(region: RegionDraft) -> FormData | None:
    if region.type is not NodeType.FORM_FIELD:
        return None
    if region.form is not None:
        return _clean_form_data(region.form)
    label, separator, value = (_clean_text(region.text) or "").partition(":")
    return FormData(
        label=label.strip() or "Field", value=value.strip() if separator else None
    )


def _bbox(value: DraftBoundingBox | None) -> BoundingBox | None:
    if value is None:
        return None
    try:
        return BoundingBox(**value.model_dump())
    except ValueError:
        return None


def _valid_confidence_spans(
    text: str,
    spans: list[ConfidenceSpan],
) -> tuple[list[ConfidenceSpan], bool]:
    valid = [span for span in spans if 0 <= span.start < span.end <= len(text)]
    return valid, len(valid) != len(spans)


def _clean_confidence_spans(
    text: str,
    spans: list[ConfidenceSpan],
    *,
    confidence: float | None,
    bbox: BoundingBox | None,
    source: str = "provider",
) -> tuple[str, list[ConfidenceSpan], bool]:
    valid, invalid = _valid_confidence_spans(text, spans)
    cleaned = _clean_text(text) or ""
    rebased: list[ConfidenceSpan] = []
    previous_end = -1
    for span in sorted(valid, key=lambda item: (item.start, item.end)):
        if span.start < previous_end:
            invalid = True
            continue
        if any(
            character in _REMOVED_TEXT_CODEPOINTS
            for character in text[span.start : span.end]
        ):
            invalid = True
            continue
        start = sum(
            character not in _REMOVED_TEXT_CODEPOINTS
            for character in text[: span.start]
        )
        end = sum(
            character not in _REMOVED_TEXT_CODEPOINTS for character in text[: span.end]
        )
        span_text = cleaned[start:end]
        if span.text is not None and _clean_text(span.text) != span_text:
            invalid = True
            continue
        rebased.append(
            ConfidenceSpan(
                start=start,
                end=end,
                text=span_text,
                confidence=span.confidence
                if span.confidence is not None
                else confidence,
                source=span.source or source,
                bbox=span.bbox or bbox,
            )
        )
        previous_end = span.end
    return cleaned, rebased, invalid


def _table(region: RegionDraft) -> tuple[TableData | None, bool]:
    if region.type is not NodeType.TABLE:
        return None, False
    invalid = False
    cells: list[TableCell] = []
    for cell in region.table_cells:
        cell_bbox = _bbox(cell.bbox)
        text, spans, spans_invalid = _clean_confidence_spans(
            cell.text,
            cell.low_confidence_spans,
            confidence=(
                cell.confidence if cell.confidence is not None else region.confidence
            ),
            bbox=cell_bbox,
        )
        invalid = invalid or spans_invalid
        cells.append(
            TableCell(
                row=cell.row_index,
                column=cell.column_index,
                text=text,
                row_span=cell.row_span,
                column_span=cell.column_span,
                header=cell.header,
                bbox=cell_bbox,
                confidence=cell.confidence,
                low_confidence_spans=spans,
            )
        )
    return TableData(cells=cells), invalid


def _atoms(region: RegionDraft) -> tuple[list[AtomicEvidence], bool]:
    invalid = False
    atoms: list[AtomicEvidence] = []
    for atom in region.atoms:
        atom_bbox = _bbox(atom.bbox)
        text, spans, spans_invalid = _clean_confidence_spans(
            atom.text,
            atom.low_confidence_spans,
            confidence=(
                atom.confidence if atom.confidence is not None else region.confidence
            ),
            bbox=atom_bbox,
        )
        invalid = invalid or spans_invalid
        atoms.append(
            AtomicEvidence(
                kind=atom.kind,
                text=text,
                bbox=atom_bbox,
                confidence=atom.confidence,
                low_confidence_spans=spans,
            )
        )
    return atoms, invalid


def _aggregated_confidence(region: RegionDraft) -> float | None:
    values = [
        *(value for value in [region.confidence] if value is not None),
        *(
            cell.confidence
            for cell in region.table_cells
            if cell.confidence is not None
        ),
        *(atom.confidence for atom in region.atoms if atom.confidence is not None),
    ]
    return min(values) if values else None


def _block(region: RegionDraft, page_number: int, index: int) -> Block:
    block_id = f"p{page_number}-b{index + 1}"
    bbox = _bbox(region.bbox)
    table, invalid_table_confidence = _table(region)
    atoms, invalid_atom_confidence = _atoms(region)
    block = Block(
        id=block_id,
        type=region.type,
        text=_clean_text(region.text) or "",
        bbox=bbox,
        reading_order=region.reading_order,
        confidence=_aggregated_confidence(region),
        citation=Citation(page=page_number, bbox=bbox),
        heading_level=region.heading_level,
        list_marker=region.list_marker,
        table=table,
        form=_form(region),
        checkbox_state=region.checkbox_state,
        checkbox_group=region.checkbox_group,
        checkbox_option=region.checkbox_option,
        caption=_clean_text(region.caption),
        figure_description=_clean_text(region.figure_description),
        chart_type=_clean_text(region.chart_type),
        chart_data=[
            point.model_copy(
                update={
                    "label": _clean_text(point.label) or "",
                    "value": _clean_text(point.value) or "",
                    "series": _clean_text(point.series),
                }
            )
            for point in region.chart_data
        ],
        atoms=atoms,
    )
    if region.bbox is not None and bbox is None:
        block.verification = VerificationState.NEEDS_REVIEW
        block.verification_reason = "Invalid bounding box"
    elif invalid_table_confidence or invalid_atom_confidence:
        block.verification = VerificationState.NEEDS_REVIEW
        block.verification_reason = INVALID_CONFIDENCE_EVIDENCE_REASON
    return block


def _needs_verification(block: Block) -> bool:
    return (
        (
            block.confidence is not None
            and block.confidence < VERIFICATION_CONFIDENCE_THRESHOLD
        )
        or block.verification is VerificationState.NEEDS_REVIEW
    )


def _apply_correction(
    block: Block,
    region: RegionDraft,
    page_number: int,
    *,
    preserve_layout: bool = False,
) -> bool:
    del page_number, preserve_layout
    changed = False

    def replace_text(owner, attribute: str, value: str | None) -> None:
        nonlocal changed
        cleaned = _clean_text(value)
        if cleaned is None or not cleaned.strip() or cleaned == getattr(owner, attribute):
            return
        setattr(owner, attribute, cleaned)
        if hasattr(owner, "low_confidence_spans"):
            owner.low_confidence_spans = []
        changed = True

    replace_text(block, "text", region.text)

    if block.table is not None and region.table_cells:
        cells = {(cell.row, cell.column): cell for cell in block.table.cells}
        for recovered in region.table_cells:
            existing = cells.get((recovered.row_index, recovered.column_index))
            if existing is not None:
                replace_text(existing, "text", recovered.text)

    if block.form is not None and region.form is not None:
        replace_text(block.form, "label", region.form.label)
        replace_text(block.form, "value", region.form.value)
        replace_text(block.form, "hint", region.form.hint)

    for attribute in (
        "checkbox_group",
        "checkbox_option",
        "caption",
        "figure_description",
        "chart_type",
    ):
        replace_text(block, attribute, getattr(region, attribute))

    if len(block.chart_data) == len(region.chart_data):
        for existing, recovered in zip(block.chart_data, region.chart_data, strict=True):
            replace_text(existing, "label", recovered.label)
            replace_text(existing, "value", recovered.value)
            replace_text(existing, "series", recovered.series)

    if len(block.atoms) == len(region.atoms):
        for existing, recovered in zip(block.atoms, region.atoms, strict=True):
            if existing.kind == recovered.kind:
                replace_text(existing, "text", recovered.text)

    block.verification_reason = (
        None if changed else "Luna correction contained no applicable text changes"
    )
    return changed


def _apply_decision(
    block: Block,
    decision: InspectionDecision,
    page_number: int,
    *,
    preserve_layout: bool = False,
) -> None:
    if decision.region_id != block.id:
        block.verification_reason = "Verification returned a different region ID"
    elif decision.action is InspectionAction.ACCEPT:
        if block.verification_reason == INVALID_CONFIDENCE_EVIDENCE_REASON:
            block.verification = VerificationState.NEEDS_REVIEW
            return
        block.verification = VerificationState.VERIFIED
    elif decision.action is InspectionAction.CORRECT:
        if decision.corrected_region is None:
            block.verification = VerificationState.NEEDS_REVIEW
            block.verification_reason = "Correction did not include a region"
        elif decision.confidence < 0.85:
            block.verification = VerificationState.NEEDS_REVIEW
            block.verification_reason = "Luna correction confidence below 0.85"
        elif _apply_correction(
            block,
            decision.corrected_region,
            page_number,
            preserve_layout=preserve_layout,
        ):
            block.verification = VerificationState.VERIFIED
    elif decision.action is InspectionAction.REJECT:
        block.verification = VerificationState.NEEDS_REVIEW
        block.verification_reason = decision.reason or "Rejected by visual inspection"
    else:
        block.verification = VerificationState.NEEDS_REVIEW
        block.verification_reason = decision.reason or "Crop remained ambiguous"


def _region_from_block(block: Block) -> RegionDraft:
    bbox = block.bbox.model_dump(exclude={"unit"}) if block.bbox is not None else None
    cells = []
    if block.table is not None:
        cells = [
            TableCellDraft(
                row_index=cell.row,
                column_index=cell.column,
                text=cell.text,
                bbox=(
                    cell.bbox.model_dump(exclude={"unit"})
                    if cell.bbox is not None
                    else None
                ),
                row_span=cell.row_span,
                column_span=cell.column_span,
                header=cell.header,
                confidence=cell.confidence,
                low_confidence_spans=cell.low_confidence_spans,
            )
            for cell in block.table.cells
        ]
    return RegionDraft(
        type=block.type,
        bbox=bbox,
        reading_order=block.reading_order,
        text=block.text,
        confidence=block.confidence,
        heading_level=block.heading_level,
        list_marker=block.list_marker,
        table_cells=cells,
        form=block.form,
        checkbox_state=block.checkbox_state,
        checkbox_group=block.checkbox_group,
        checkbox_option=block.checkbox_option,
        caption=block.caption,
        figure_description=block.figure_description,
        chart_type=block.chart_type,
        chart_data=block.chart_data,
        atoms=[
            AtomicDraft(
                kind=atom.kind,
                text=atom.text,
                bbox=(
                    atom.bbox.model_dump(exclude={"unit"})
                    if atom.bbox is not None
                    else None
                ),
                confidence=atom.confidence,
                low_confidence_spans=atom.low_confidence_spans,
            )
            for atom in block.atoms
        ],
    )


def _span_owner(block: Block, owner_kind: str, owner_index: int):
    if owner_kind == "atom" and owner_index < len(block.atoms):
        return block.atoms[owner_index]
    if (
        owner_kind == "table_cell"
        and block.table is not None
        and owner_index < len(block.table.cells)
    ):
        return block.table.cells[owner_index]
    return None


def _span_repair_target(
    block: Block,
    candidate,
    *,
    page_number: int,
) -> SpanRepairTarget | None:
    owner = _span_owner(block, candidate.owner_kind, candidate.owner_index)
    if owner is None:
        return None
    span = candidate.span
    if not 0 <= span.start < span.end <= len(owner.text):
        return None
    text = owner.text[span.start : span.end]
    if span.text is not None and span.text != text:
        return None
    target_id = (
        f"{block.id}:{candidate.owner_kind}:{candidate.owner_index}:"
        f"{candidate.span_index}"
    )
    evidence_ref = f"page:{page_number}:{target_id}"
    return SpanRepairTarget(
        target_id=target_id,
        region_id=block.id,
        owner_kind=candidate.owner_kind,
        owner_index=candidate.owner_index,
        start=span.start,
        end=span.end,
        text=text,
        context_before=owner.text[max(0, span.start - 32) : span.start],
        context_after=owner.text[span.end : span.end + 32],
        confidence=(
            span.confidence
            if span.confidence is not None
            else owner.confidence
            if owner.confidence is not None
            else block.confidence
        ),
        source=span.source or "unknown",
        bbox=span.bbox or owner.bbox or block.bbox,
        evidence_ref=evidence_ref,
    )


def _rebase_owner_spans(
    owner,
    target: SpanRepairTarget,
    replacement: str,
) -> None:
    delta = len(replacement) - (target.end - target.start)
    rebased: list[ConfidenceSpan] = []
    removed = False
    for span in owner.low_confidence_spans:
        if (
            not removed
            and span.start == target.start
            and span.end == target.end
            and (span.text is None or span.text == target.text)
        ):
            removed = True
            continue
        if span.end <= target.start:
            rebased.append(span)
        elif span.start >= target.end:
            rebased.append(
                span.model_copy(
                    update={"start": span.start + delta, "end": span.end + delta}
                )
            )
        else:
            # Overlaps are rejected during normalization; fail closed if one survives.
            rebased.append(span)
    owner.low_confidence_spans = rebased


def _apply_span_repairs(
    block: Block,
    targets: list[SpanRepairTarget],
    decisions: list[SpanRepairDecision],
    *,
    repair_source: str,
) -> None:
    by_id: dict[str, SpanRepairDecision] = {}
    duplicate_ids: set[str] = set()
    for decision in decisions:
        if decision.target_id in by_id:
            duplicate_ids.add(decision.target_id)
        by_id[decision.target_id] = decision

    for target in sorted(
        targets, key=lambda item: (item.owner_kind, item.owner_index, -item.start)
    ):
        decision = by_id.get(target.target_id)
        owner = _span_owner(block, target.owner_kind, target.owner_index)
        if (
            decision is None
            or target.target_id in duplicate_ids
            or decision.evidence_ref != target.evidence_ref
            or owner is None
            or owner.text[target.start : target.end] != target.text
            or decision.action is SpanRepairAction.UNRESOLVED
        ):
            block.verification = VerificationState.NEEDS_REVIEW
            block.verification_reason = (
                decision.reason
                if decision is not None and decision.reason
                else "Targeted literal repair was inconclusive"
            )
            continue

        replacement = (
            target.text
            if decision.action is SpanRepairAction.CONFIRM
            else decision.replacement_text
        )
        if replacement is None:
            block.verification = VerificationState.NEEDS_REVIEW
            block.verification_reason = (
                "Targeted literal repair omitted replacement text"
            )
            continue

        previous_state = block.verification
        original_owner_text = owner.text
        mirrored_atom = None
        if target.owner_kind == "table_cell":
            matching_atoms = [
                atom
                for atom in block.atoms
                if atom.text == original_owner_text
                and (atom.bbox == owner.bbox or atom.bbox is None or owner.bbox is None)
            ]
            if len(matching_atoms) == 1:
                mirrored_atom = matching_atoms[0]
        if target.owner_kind == "atom" and block.type not in VISUAL_REGION_TYPES:
            occurrences = [
                match.start()
                for match in re.finditer(re.escape(original_owner_text), block.text)
            ]
            if len(occurrences) != 1:
                block.verification = VerificationState.NEEDS_REVIEW
                block.verification_reason = (
                    "Targeted atom could not be mapped uniquely to canonical text"
                )
                continue
            block_start = occurrences[0] + target.start
            block_end = occurrences[0] + target.end
            block.text = block.text[:block_start] + replacement + block.text[block_end:]

        owner.text = owner.text[: target.start] + replacement + owner.text[target.end :]
        _rebase_owner_spans(owner, target, replacement)
        owner.confidence = decision.confidence
        if mirrored_atom is not None:
            mirrored_atom.text = (
                mirrored_atom.text[: target.start]
                + replacement
                + mirrored_atom.text[target.end :]
            )
            _rebase_owner_spans(mirrored_atom, target, replacement)
            mirrored_atom.confidence = decision.confidence
        block.correction_lineage.append(
            CorrectionLineage(
                original_id=block.id,
                replacement_id=block.id,
                provider_id=target.target_id,
                reason=(
                    f"{decision.reason or 'Targeted literal repair'}; "
                    f"repair_source={repair_source}; source={target.source}; "
                    f"{target.text!r} -> {replacement!r}"
                ),
                previous_state=previous_state,
                final_state=block.verification,
            )
        )


def _proactive_crop_priority(block: Block) -> int | None:
    searchable = "\n".join(
        value
        for value in (block.text, block.caption, block.figure_description)
        if value
    )
    if AMBIGUOUS_LITERAL_PATTERN.search(searchable):
        return 1
    return None


RecoveryBoxKey = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class _RecoveryCandidate:
    page: int
    bbox: RecoveryBoxKey
    severity: int
    confidence: float
    reading_order: int
    target_id: str
    reasons: tuple[str, ...] = ()
    primary_text: str = ""

    @property
    def rank(self) -> tuple[int, int, float, int, int, str]:
        return (
            0 if "unresolved_form_controls" in self.reasons else 1,
            self.severity,
            self.confidence,
            self.page,
            self.reading_order,
            self.target_id,
        )


@dataclass(slots=True)
class _GlmFormRecovery:
    statuses: dict[int, dict[RecoveryBoxKey, str]] = field(default_factory=dict)
    candidate_count: int = 0
    crops: int = 0
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _PaddleFormRecovery:
    attempts: int = 0
    resolved: int = 0
    duration: float = 0.0
    warnings: list[str] = field(default_factory=list)


def _paddle_table_anchor(value: str) -> str | None:
    markers = {"x", "☒", "☑", "✓", "✔", "☐", "□"}
    for cell in _raw_html_cells(value):
        text = cell.text.strip()
        if not text or text.casefold() in markers:
            continue
        _state, label = _form_option(text)
        if label is None:
            return " ".join(text.casefold().split())
    return None


def _paddle_recovery_content(result: OcrPageResult, anchor: str) -> str | None:
    matches = [
        region.content
        for region in result.regions
        if "<table" in region.content.casefold()
        and _paddle_table_anchor(region.content) == anchor
    ]
    return matches[0] if len(matches) == 1 else None


def _confirmed_paddle_states(
    left: dict[tuple[str, int], str | None],
    right: dict[tuple[str, int], str | None],
) -> dict[tuple[str, int], str]:
    return {
        key: state
        for key, state in left.items()
        if state is not None and right.get(key) == state
    }


def _recover_paddle_form_regions(
    source: IngestedDocument,
    pages: list[PageEvidence],
    analyses: dict[int, PageAnalysis | None],
    workdir: Path,
    config: ParserConfig,
) -> _PaddleFormRecovery:
    """Recover only missing Paddle form states confirmed at two render scales."""

    started = time.perf_counter()
    outcome = _PaddleFormRecovery()
    if source.source_path.suffix.casefold() != ".pdf":
        return outcome

    candidates: dict[int, list[tuple[LayoutRegionEvidence, str]]] = {}
    for page_number, analysis in analyses.items():
        if analysis is None or analysis.quality.blank:
            continue
        for region in analysis.regions:
            if region.type not in {AnalysisRegionType.TABLE, AnalysisRegionType.FORM}:
                continue
            states = _paddle_form_states(region.text)
            anchor = _paddle_table_anchor(region.text)
            if (
                len(states) >= 2
                and any(state is None for state in states.values())
                and anchor
            ):
                candidates.setdefault(page_number, []).append((region, anchor))
    if not candidates:
        outcome.duration = time.perf_counter() - started
        return outcome

    pages_by_number = {page.number: page for page in pages}
    page_limit = config.max_visual_recovery_crops // 2
    selected_pages = sorted(candidates)[:page_limit]
    if len(selected_pages) < len(candidates):
        outcome.warnings.append(
            "Paddle checkbox recovery deferred "
            f"{len(candidates) - len(selected_pages)} page(s) due to the "
            "visual recovery budget"
        )
    recovery_dir = workdir / "paddle-form-recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    full_page = BoundingBox(x0=0, y0=0, x1=1, y1=1)
    runtime = get_paddleocr_runtime(
        config.paddleocr_service_url, config.paddleocr_timeout_seconds
    )

    for page_number in selected_pages:
        page = pages_by_number.get(page_number)
        if page is None:
            continue
        anchor_counts: dict[str, int] = {}
        for _region, anchor in candidates[page_number]:
            anchor_counts[anchor] = anchor_counts.get(anchor, 0) + 1
        unique_candidates = [
            (region, anchor)
            for region, anchor in candidates[page_number]
            if anchor_counts[anchor] == 1
        ]
        if not unique_candidates:
            outcome.warnings.append(
                f"Page {page_number}: Paddle checkbox recovery skipped ambiguous tables"
            )
            continue

        results: list[OcrPageResult] = []
        try:
            for dpi in (190, 200):
                if (
                    dpi == 200
                    and page.effective_dpi == 200
                    and page.image_path.exists()
                ):
                    image_path = page.image_path
                else:
                    image_path = recovery_dir / f"p{page_number}-{dpi}dpi.png"
                    render_region_crop(
                        source,
                        page,
                        full_page,
                        image_path,
                        dpi=dpi,
                        padding=0,
                    )
                outcome.attempts += 1
                results.append(runtime.parse_recovery_image(image_path))
        except Exception as exc:  # noqa: BLE001 - first-pass output must survive
            outcome.warnings.append(
                f"Page {page_number}: Paddle checkbox recovery unavailable: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        for region, anchor in unique_candidates:
            recovered = [
                _paddle_recovery_content(result, anchor) for result in results
            ]
            if any(content is None for content in recovered):
                outcome.warnings.append(
                    f"Page {page_number}: Paddle checkbox recovery could not align "
                    f"{region.id}"
                )
                continue
            left, right = (  # narrowed by the guard above
                _paddle_form_states(content or "") for content in recovered
            )
            confirmed = _confirmed_paddle_states(left, right)
            merged, resolved = _merge_confirmed_form_states(region.text, confirmed)
            if not resolved:
                if left != right:
                    outcome.warnings.append(
                        f"Page {page_number}: Paddle checkbox recovery disagreed for "
                        f"{region.id}"
                    )
                continue
            region.text = merged
            outcome.resolved += resolved
            analysis = analyses.get(page_number)
            if analysis is not None:
                analysis.warnings.append(
                    "Paddle checkbox recovery confirmed "
                    f"{resolved} state(s) for {region.id} at 190/200 DPI"
                )
    outcome.duration = time.perf_counter() - started
    return outcome


def _form_recovery_priority(region: LayoutRegionEvidence) -> int | None:
    if region.type not in {AnalysisRegionType.TABLE, AnalysisRegionType.FORM}:
        return None
    option_count = sum(
        _form_option(cell.text)[1] is not None for cell in _raw_html_cells(region.text)
    )
    if option_count >= 2:
        return 0
    if region.type is AnalysisRegionType.FORM:
        return 1
    if re.search(r"<table\b", region.text, re.IGNORECASE) and region.text.count(":") >= 4:
        return 2
    return None


def _glm_recovery_content(result: GlmPageResult) -> str:
    tables = [
        region.content
        for region in result.regions
        if region.label.casefold() == "table" and region.content.strip()
    ]
    if tables:
        return max(tables, key=len)
    return "\n".join(
        region.content for region in result.regions if region.content.strip()
    )


def _recover_glm_form_regions(
    source: IngestedDocument,
    pages: list[PageEvidence],
    analyses: dict[int, PageAnalysis | None],
    workdir: Path,
    config: ParserConfig,
) -> _GlmFormRecovery:
    started = time.perf_counter()
    outcome = _GlmFormRecovery()
    if not config.glm_form_recovery_enabled or not config.local_ocr_enabled:
        return outcome

    candidates: list[tuple[int, int, PageEvidence, LayoutRegionEvidence]] = []
    pages_by_number = {page.number: page for page in pages}
    for page_number, analysis in analyses.items():
        if analysis is None or analysis.quality.blank:
            continue
        for order, region in enumerate(analysis.regions):
            priority = _form_recovery_priority(region)
            if priority is not None:
                candidates.append(
                    (priority, order, pages_by_number[page_number], region)
                )
    outcome.candidate_count = len(candidates)
    selected: list[tuple[PageEvidence, LayoutRegionEvidence]] = []
    per_page: dict[int, int] = {}
    for _priority, _order, page, region in sorted(
        candidates, key=lambda item: (item[0], item[2].number, item[1])
    ):
        if per_page.get(page.number, 0) >= MAX_VISUAL_RECOVERY_CROPS_PER_PAGE:
            continue
        selected.append((page, region))
        per_page[page.number] = per_page.get(page.number, 0) + 1
    if not selected:
        outcome.duration = time.perf_counter() - started
        return outcome

    requests: dict[Path, tuple[PageEvidence, LayoutRegionEvidence]] = {}
    for index, (page, region) in enumerate(selected, start=1):
        crop_path = workdir / "glm-form-recovery" / f"p{page.number}-{index}.png"
        try:
            render_region_crop(
                source,
                page,
                region.bbox.normalized,
                crop_path,
                dpi=config.crop_dpi,
                padding=config.crop_padding,
            )
        except Exception as exc:  # noqa: BLE001 - recovery must preserve first pass
            outcome.warnings.append(
                f"Page {page.number}: GLM form crop failed: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        requests[crop_path.resolve()] = (page, region)
    if not requests:
        outcome.duration = time.perf_counter() - started
        return outcome

    try:
        runtime = get_grounded_ocr_runtime(
            replace(config, ocr_engine=OcrEngine.GLM_OCR)
        )
        if hasattr(runtime, "parse_many"):
            results = runtime.parse_many(list(requests))
        else:
            results = (
                GlmPageResult(path, runtime.parse(path)) for path in requests
            )
        for result in results:
            target = requests.get(result.image_path.resolve())
            if target is None:
                continue
            page, region = target
            outcome.crops += 1
            recovered = "" if result.error else _glm_recovery_content(result)
            if not recovered:
                outcome.warnings.append(
                    f"Page {page.number}: GLM form recovery returned no usable text"
                )
                continue
            merged, status, evidence_count = _merge_form_html(
                region.text, recovered
            )
            if merged == region.text:
                continue
            region.text = merged
            key = _recovery_box_key(region.bbox.normalized)
            if key is not None:
                outcome.statuses.setdefault(page.number, {})[key] = status
            region_id = region.id
            analysis = analyses.get(page.number)
            if analysis is not None:
                analysis.warnings.append(
                    "GLM form recovery "
                    f"{status} for {region_id} ({evidence_count} resolved value(s))"
                )
    except Exception as exc:  # noqa: BLE001 - recovery must preserve first pass
        outcome.warnings.append(
            f"GLM form recovery unavailable: {type(exc).__name__}: {exc}"
        )
    outcome.duration = time.perf_counter() - started
    return outcome


def _recovery_box_key(bbox: BoundingBox | None) -> RecoveryBoxKey | None:
    if bbox is None:
        return None
    return tuple(round(value, 6) for value in (bbox.x0, bbox.y0, bbox.x1, bbox.y1))


def _box_area(box: RecoveryBoxKey) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _box_intersection(left: RecoveryBoxKey, right: RecoveryBoxKey) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1])
    )


def _same_recovery_area(left: RecoveryBoxKey, right: RecoveryBoxKey) -> bool:
    intersection = _box_intersection(left, right)
    if not intersection:
        return False
    left_area, right_area = _box_area(left), _box_area(right)
    union = left_area + right_area - intersection
    return (union > 0 and intersection / union >= RECOVERY_OVERLAP_IOU) or (
        min(left_area, right_area) > 0
        and intersection / min(left_area, right_area) >= RECOVERY_CONTAINMENT
    )


def _visible_character_count(text: str) -> int:
    return sum(not character.isspace() for character in text)


def _garbage_ratio(text: str) -> float:
    visible = [character for character in text if not character.isspace()]
    if not visible:
        return 0.0
    mojibake = sum(text.count(marker) for marker in ("�", "Ã", "Â", "â€"))
    broken = sum(
        unicodedata.category(character).startswith("C") for character in visible
    )
    noisy_runs = sum(
        len(match.group(0))
        for match in re.finditer(r"([^\w\s|_./,:;+'\"%$€£¥₹()-])\1{2,}", text)
    )
    return min(1.0, (mojibake + broken + noisy_runs) / len(visible))


def _table_quality(block: Block) -> float:
    if block.type is not NodeType.TABLE or block.table is None or not block.table.cells:
        return 0.0
    cells = block.table.cells
    rows = max(cell.row for cell in cells) + 1
    columns = max(cell.column for cell in cells) + 1
    if rows < 2 or columns < 2:
        return 0.25
    nonempty = sum(bool(cell.text.strip()) for cell in cells) / len(cells)
    rectangular = len({(cell.row, cell.column) for cell in cells}) / (
        rows * columns
    )
    return (nonempty + rectangular) / 2


def _page_recovery_candidates(
    page: PageEvidence,
    analysis: PageAnalysis | None,
) -> list[_RecoveryCandidate]:
    if analysis is None or analysis.quality.blank or not analysis.regions:
        return []

    draft = draft_from_analysis(analysis)
    blocks = [
        _block(region, page.number, index)
        for index, region in enumerate(draft.regions)
    ]
    warnings = [*draft.warnings, *analysis.warnings]
    by_box: dict[RecoveryBoxKey, _RecoveryCandidate] = {}

    def add(
        block: Block,
        severity: int,
        *,
        bbox: BoundingBox | None = None,
        target_id: str | None = None,
        reasons: tuple[str, ...] = (),
    ) -> None:
        key = _recovery_box_key(bbox or block.bbox)
        if key is None:
            return
        if block.type in COMPLEX_REGION_TYPES or CRITICAL_LITERAL_PATTERN.search(
            semantic_text(block)
        ):
            severity = max(0, severity - 1)
        candidate = _RecoveryCandidate(
            page=page.number,
            bbox=key,
            severity=severity,
            confidence=block.confidence if block.confidence is not None else 1.0,
            reading_order=block.reading_order,
            target_id=target_id or block.id,
            primary_text=semantic_text(block),
            reasons=reasons,
        )
        existing = by_box.get(key)
        if existing is None or candidate.rank < existing.rank:
            by_box[key] = candidate

    repair_ids = {block.id for block in select_repair_blocks(page, blocks, warnings)}
    for source, region, block in zip(
        analysis.regions, draft.regions, blocks, strict=True
    ):
        box = _recovery_box_key(block.bbox)
        area = _box_area(box) if box else 0.0
        text = semantic_text(block)
        visible = _visible_character_count(text)
        reasons: list[str] = []
        severity = 99
        if not text.strip() and area >= RECOVERY_LARGE_REGION_AREA:
            severity = 0
            reasons.append("empty_large_region")
        form_control_severity = (
            _form_control_recovery_severity(block.text)
            if block.type is NodeType.TABLE
            else None
        )
        if form_control_severity is not None:
            severity = min(severity, form_control_severity)
            reasons.append("unresolved_form_controls")
        if block.type is NodeType.TABLE and _table_quality(block) < RECOVERY_TABLE_QUALITY:
            severity = min(severity, 1)
            reasons.append("low_table_quality")
        garbage = _garbage_ratio(text)
        low_confidence = (
            source.ocr_confidence is not None
            and source.ocr_confidence < RECOVERY_OCR_CONFIDENCE_THRESHOLD
        )
        if low_confidence and garbage > RECOVERY_GARBAGE_RATIO:
            severity = min(severity, 2)
            reasons.extend(("low_ocr_confidence", "garbage_text"))
        elif garbage > RECOVERY_GARBAGE_RATIO:
            severity = min(severity, 3)
            reasons.append("garbage_text")
        elif low_confidence:
            severity = min(severity, 4)
            reasons.append("low_ocr_confidence")
        if area >= RECOVERY_LARGE_REGION_AREA and visible / max(area, 1e-9) < RECOVERY_MIN_CHARACTER_DENSITY:
            severity = min(severity, 5)
            reasons.append("low_character_density")
        if reasons:
            add(block, severity, reasons=tuple(dict.fromkeys(reasons)))
        if block.id in repair_ids:
            add(
                block,
                1 if requires_region_repair(page, block, warnings) else 4,
                reasons=("structured_or_literal_risk",),
            )
        for literal in literal_repair_candidates(page, block):
            target = _span_repair_target(block, literal, page_number=page.number)
            if target is not None:
                add(
                    block,
                    4,
                    bbox=target.bbox,
                    target_id=target.target_id,
                    reasons=("low_confidence_literal",),
                )
        if _needs_verification(block):
            add(block, 4, reasons=("verification_required",))
        if _proactive_crop_priority(block) is not None:
            add(block, 6, reasons=("visual_or_ambiguous_content",))

    selected: list[_RecoveryCandidate] = []
    for candidate in sorted(by_box.values(), key=lambda item: item.rank):
        if not any(
            _same_recovery_area(candidate.bbox, existing.bbox)
            for existing in selected
        ):
            selected.append(candidate)
    return selected


@dataclass(slots=True)
class _VisualRecoveryPlan:
    allowed: dict[int, set[RecoveryBoxKey]] = field(default_factory=dict)
    deferred: dict[int, set[RecoveryBoxKey]] = field(default_factory=dict)
    candidate_count: int = 0


def _visual_recovery_crop_budget(page_count: int, *, ceiling: int) -> int:
    return min(ceiling, max(MIN_VISUAL_RECOVERY_CROPS_PER_DOCUMENT, page_count))


def _visual_recovery_plan(
    pages: list[PageEvidence],
    analyses: dict[int, PageAnalysis | None],
    *,
    enabled: bool,
    limit: int,
) -> _VisualRecoveryPlan:
    by_page = {
        page.number: _page_recovery_candidates(page, analyses.get(page.number))
        for page in pages
    }
    candidates = [candidate for items in by_page.values() for candidate in items]
    plan = _VisualRecoveryPlan(candidate_count=len(candidates))
    if not enabled:
        for candidate in candidates:
            plan.deferred.setdefault(candidate.page, set()).add(candidate.bbox)
        return plan

    units = candidates

    selected: list[_RecoveryCandidate] = []
    per_page: dict[int, int] = {}
    for candidate in sorted(units, key=lambda item: item.rank):
        if len(selected) >= limit:
            break
        if per_page.get(candidate.page, 0) >= MAX_VISUAL_RECOVERY_CROPS_PER_PAGE:
            continue
        selected.append(candidate)
        per_page[candidate.page] = per_page.get(candidate.page, 0) + 1
    selected_keys = {(candidate.page, candidate.bbox) for candidate in selected}
    for candidate in units:
        target = (
            plan.allowed
            if (candidate.page, candidate.bbox) in selected_keys
            else plan.deferred
        )
        target.setdefault(candidate.page, set()).add(candidate.bbox)
    return plan


def _build_recovery_log(
    document: Document,
    recovered_region_ids: set[str],
) -> list[VisualRecoveryResult]:
    recovered: list[tuple[int, Block]] = []

    def collect(page_number: int, blocks: list[Block]) -> None:
        for block in sorted(blocks, key=lambda item: item.reading_order):
            if block.id in recovered_region_ids:
                recovered.append((page_number, block))
            collect(page_number, block.children)

    for page in document.pages:
        collect(page.number, page.blocks)

    records = []
    for index, (page_number, block) in enumerate(recovered, start=1):
        records.append(
            VisualRecoveryResult(
                region_id=f"recovery_{index}",
                page=page_number,
                original_element_id=block.id,
                recovered_text=semantic_text(block),
                confidence="high",
                notes=block.verification_reason or "Recovered by visual recovery",
            )
        )
    return records


def _decision_issue(
    decision: InspectionDecision,
    region_id: str,
    *,
    source: str = "Verification",
) -> str | None:
    if decision.region_id != region_id:
        return f"{source} returned a different region ID"
    if decision.action is InspectionAction.CORRECT:
        if decision.corrected_region is None:
            return (
                f"{source} correction did not include a region"
                if source == "Arbitration"
                else "Correction did not include a region"
            )
    elif decision.corrected_region is not None:
        return f"{source} returned a correction for a non-correct decision"
    return None


def _validated_crop_decisions(
    requests: list[CropInspectionRequest],
    inspection: PageInspection,
    *,
    source: str,
) -> tuple[dict[str, InspectionDecision], str | None]:
    expected: dict[str, str] = {}
    duplicate_requests: set[str] = set()
    for request in requests:
        if request.region_id in expected:
            duplicate_requests.add(request.region_id)
        expected[request.region_id] = request.evidence_ref

    returned: dict[str, InspectionDecision] = {}
    seen_decision_ids: set[str] = set()
    duplicate_decisions: set[str] = set()
    unexpected_ids: set[str] = set()
    evidence_mismatches: set[str] = set()
    invalid_decisions: dict[str, str] = {}
    for decision in inspection.decisions:
        region_id = decision.region_id
        if region_id not in expected:
            unexpected_ids.add(region_id)
            continue
        if region_id in seen_decision_ids:
            duplicate_decisions.add(region_id)
            returned.pop(region_id, None)
            continue
        seen_decision_ids.add(region_id)
        if decision.evidence_refs != [expected[region_id]]:
            evidence_mismatches.add(region_id)
            continue
        issue = _decision_issue(decision, region_id, source=source)
        if issue is not None:
            invalid_decisions[region_id] = issue
            continue
        returned[region_id] = decision

    missing_ids = set(expected).difference(
        decision.region_id for decision in inspection.decisions
    )
    problems: list[str] = []
    if duplicate_requests:
        problems.append(
            f"multiple requests for {', '.join(sorted(duplicate_requests))}"
        )
    if duplicate_decisions:
        problems.append(
            f"multiple decisions for {', '.join(sorted(duplicate_decisions))}"
        )
    if unexpected_ids:
        problems.append(
            f"unexpected region IDs {', '.join(sorted(unexpected_ids))}"
        )
    if missing_ids:
        problems.append(f"missing decisions for {', '.join(sorted(missing_ids))}")
    if evidence_mismatches:
        problems.append(
            "evidence reference mismatch for "
            f"{', '.join(sorted(evidence_mismatches))}"
        )
    if invalid_decisions:
        problems.extend(invalid_decisions[key] for key in sorted(invalid_decisions))
    if problems:
        return {}, f"{source} response rejected: {'; '.join(problems)}"
    return returned, None


def _hierarchy(
    blocks: list[Block], inherited_sections: list[str]
) -> tuple[list[Block], list[str]]:
    roots: list[Block] = []
    heading_stack: list[Block] = []
    sections = list(inherited_sections)
    for block in sorted(blocks, key=lambda item: item.reading_order):
        if block.type is NodeType.HEADING:
            level = block.heading_level or 1
            while heading_stack and (heading_stack[-1].heading_level or 1) >= level:
                heading_stack.pop()
            while len(sections) >= level:
                sections.pop()
            block.section_path = list(sections)
            if heading_stack:
                heading_stack[-1].children.append(block)
            else:
                roots.append(block)
            heading_stack.append(block)
            sections.append(block.text)
            continue
        block.section_path = list(sections)
        if heading_stack:
            heading_stack[-1].children.append(block)
        else:
            roots.append(block)
    return roots, sections


@dataclass(slots=True)
class _ProcessedPage:
    page: Page
    warnings: list[str]
    usage: RunUsage
    trace: list[AgentTraceEvent]
    visual_recovery_crops: int = 0
    recovered_region_ids: list[str] = field(default_factory=list)


class DocumentParser:
    def __init__(
        self,
        config: ParserConfig | None = None,
        *,
        gateway_factory: Callable[[ParserConfig], object] = OpenAIDocumentGateway,
        ocr_service_switcher: Callable[[OcrEngine], None] = ensure_managed_ocr_engine,
    ) -> None:
        self.config = config or ParserConfig.from_env()
        self.gateway_factory = gateway_factory
        self.ocr_service_switcher = ocr_service_switcher

    def _cross_check_uncertain_regions(
        self,
        source: IngestedDocument,
        pages: list[PageEvidence],
        analyses: dict[int, PageAnalysis | None],
        workdir: Path,
    ) -> tuple[list[OcrComparisonResult], int, float]:
        if not self.config.ocr_disagreement_enabled:
            return [], 0, 0.0
        candidates = sorted(
            (
                item
                for page in pages
                for item in _page_recovery_candidates(page, analyses.get(page.number))
            ),
            key=lambda item: item.rank,
        )
        selected: list[_RecoveryCandidate] = []
        per_page: dict[int, int] = {}
        for candidate in candidates:
            if len(selected) >= self.config.max_ocr_disagreement_crops:
                break
            if per_page.get(candidate.page, 0) >= self.config.max_ocr_disagreement_crops_per_page:
                continue
            selected.append(candidate)
            per_page[candidate.page] = per_page.get(candidate.page, 0) + 1
        if not selected:
            return [], len(candidates), 0.0

        started = time.perf_counter()
        primary = self.config.ocr_engine
        secondary = (
            OcrEngine.PADDLEOCR_VL_1_6
            if primary is OcrEngine.GLM_OCR
            else OcrEngine.GLM_OCR
        )
        page_by_number = {page.number: page for page in pages}
        results: list[OcrComparisonResult] = []
        try:
            self.ocr_service_switcher(secondary)
            if secondary is OcrEngine.GLM_OCR:
                runtime = get_grounded_ocr_runtime(
                    replace(self.config, ocr_engine=OcrEngine.GLM_OCR)
                )
            else:
                runtime = get_paddleocr_runtime(
                    self.config.paddleocr_service_url,
                    self.config.paddleocr_timeout_seconds,
                )
            for index, candidate in enumerate(selected):
                crop = render_region_crop(
                    source,
                    page_by_number[candidate.page],
                    BoundingBox(
                        x0=candidate.bbox[0],
                        y0=candidate.bbox[1],
                        x1=candidate.bbox[2],
                        y1=candidate.bbox[3],
                    ),
                    workdir / "ocr-disagreement" / f"{candidate.page}-{index}.png",
                    dpi=self.config.crop_dpi,
                    padding=self.config.crop_padding,
                )
                parsed = (
                    runtime.parse(crop)
                    if secondary is OcrEngine.GLM_OCR
                    else runtime.parse_recovery_image(crop).regions
                )
                texts = [region.content.strip() for region in parsed if region.content.strip()]
                alternatives = [*texts, "\n".join(texts)] if texts else [""]
                secondary_text = max(
                    alternatives,
                    key=lambda text: token_edit_similarity(candidate.primary_text, text),
                )
                similarity = token_edit_similarity(candidate.primary_text, secondary_text)
                disagreed = similarity < self.config.ocr_disagreement_similarity_threshold
                results.append(
                    OcrComparisonResult(
                        page=candidate.page,
                        bbox=candidate.bbox,
                        primary_engine=primary.value,
                        secondary_engine=secondary.value,
                        primary_text=candidate.primary_text,
                        secondary_text=secondary_text,
                        similarity=similarity,
                        status="disagreed" if disagreed else "agreed",
                        reason=(
                            "Local OCR engines disagreed on uncertain region"
                            if disagreed
                            else "Local OCR engines agreed"
                        ),
                    )
                )
        except Exception as exc:  # noqa: BLE001 - comparison is audit-only
            reason = f"Alternate OCR unavailable: {type(exc).__name__}: {exc}"
            completed = {(item.page, item.bbox) for item in results}
            for candidate in selected:
                if (candidate.page, candidate.bbox) not in completed:
                    results.append(
                        OcrComparisonResult(
                            page=candidate.page,
                            bbox=candidate.bbox,
                            primary_engine=primary.value,
                            secondary_engine=secondary.value,
                            primary_text=candidate.primary_text,
                            status="unavailable",
                            reason=reason,
                        )
                    )
        finally:
            try:
                self.ocr_service_switcher(primary)
            except Exception as exc:  # noqa: BLE001 - primary result remains authoritative
                results.append(
                    OcrComparisonResult(
                        page=selected[0].page,
                        primary_engine=primary.value,
                        secondary_engine=secondary.value,
                        primary_text="",
                        status="unavailable",
                        reason=f"Primary OCR restoration failed: {type(exc).__name__}: {exc}",
                    )
                )
        return results, len(candidates), time.perf_counter() - started

    def _process_page(
        self,
        source: IngestedDocument,
        page: PageEvidence,
        workdir: Path,
        total: int,
        progress_callback: ProgressCallback | None,
        runtime: ProviderRuntime,
        analyzer: PageAnalyzer,
        analysis=None,
        visual_recovery: bool = True,
        allowed_recovery_boxes: set[RecoveryBoxKey] | None = None,
        deferred_recovery_boxes: set[RecoveryBoxKey] | None = None,
        glm_recovery_statuses: dict[RecoveryBoxKey, str] | None = None,
        ocr_comparisons: dict[RecoveryBoxKey, OcrComparisonResult] | None = None,
    ) -> _ProcessedPage:
        recovery_available = visual_recovery and (
            self.gateway_factory is not OpenAIDocumentGateway
            or bool(os.getenv("OPENAI_API_KEY"))
        )
        gateway = (
            _UnavailableGateway(
                "disabled by user"
                if not visual_recovery
                else "OPENAI_API_KEY is not set"
            )
            if not visual_recovery
            or (
                self.gateway_factory is OpenAIDocumentGateway
                and not recovery_available
            )
            else self.gateway_factory(self.config)
        )
        bind_runtime = getattr(gateway, "bind_runtime", None)
        if callable(bind_runtime):
            bind_runtime(runtime)
        warnings: list[str] = []
        recovered_region_ids: set[str] = set()
        used_recovery_boxes: set[RecoveryBoxKey] = set()
        visual_recovery_crops = 0

        def consume_recovery_box(bbox: BoundingBox | None) -> bool:
            key = _recovery_box_key(bbox)
            if key is None:
                return False
            if allowed_recovery_boxes is None:
                return True
            if key in used_recovery_boxes:
                return False
            if allowed_recovery_boxes is not None and key not in allowed_recovery_boxes:
                return False
            used_recovery_boxes.add(key)
            return True
        _emit(
            progress_callback,
            "draft",
            page.number,
            total,
            f"Reading page {page.number}",
        )
        if analysis is None:
            draft = gateway.draft_page(page)
        else:
            if analysis.quality.blank:
                draft = PageDraft(
                    warnings=["Page contains no visible raster foreground"]
                )
            elif not analysis.regions:
                draft = PageDraft(
                    warnings=[
                        *(analysis.warnings or ["GLM-OCR returned no layout regions"]),
                        "Luna recovery skipped because GLM produced no grounded region",
                    ]
                )
            else:
                draft = draft_from_analysis(analysis)
        blocks = [
            _block(region, page.number, index)
            for index, region in enumerate(draft.regions)
        ]
        for block in blocks:
            status = (glm_recovery_statuses or {}).get(
                _recovery_box_key(block.bbox) or ()
            )
            if status is None:
                continue
            previous_state = block.verification
            block.verification = (
                VerificationState.VERIFIED
                if status == "resolved"
                else VerificationState.NEEDS_REVIEW
            )
            block.verification_reason = (
                "GLM form recovery agreed with the primary structure"
                if status == "resolved"
                else f"GLM form recovery {status}; unresolved controls use [?]"
            )
            block.correction_lineage.append(
                CorrectionLineage(
                    original_id=block.id,
                    replacement_id=block.id,
                    provider_id="glm-ocr-form-recovery",
                    reason=block.verification_reason,
                    previous_state=previous_state,
                    final_state=block.verification,
                )
            )
            if status == "resolved":
                recovered_region_ids.add(block.id)
        blocks_by_id = {block.id: block for block in blocks}
        try:
            with Image.open(page.image_path) as page_image:
                source_page_pixels = page_image.width * page_image.height
        except (FileNotFoundError, OSError):
            source_page_pixels = 0

        def inspect_targets(
            target_ids: list[str],
            *,
            agent_role: AgentRole = AgentRole.EVIDENCE_CRITIC,
            repair_round: int | None = None,
            stage: str = "crop_inspection",
        ) -> PageInspection:
            nonlocal visual_recovery_crops
            requests: list[CropInspectionRequest] = []
            for target_id in target_ids:
                block = blocks_by_id.get(target_id)
                if (
                    block is None
                    or block.bbox is None
                    or not consume_recovery_box(block.bbox)
                ):
                    continue
                crop_path = workdir / f"{block.id}-{stage}.png"
                render_region_crop(
                    source,
                    page,
                    block.bbox,
                    crop_path,
                    dpi=self.config.crop_dpi,
                    padding=max(self.config.crop_padding, 0.1),
                )
                requests.append(
                    CropInspectionRequest(
                        crop_path=str(crop_path),
                        region_id=block.id,
                        candidate_region=_region_from_block(block),
                        evidence_ref=f"page:{page.number}:{block.id}:{stage}",
                        source_page_pixels=source_page_pixels,
                    )
                )
            if not requests:
                return PageInspection()
            visual_recovery_crops += len(requests)
            crop_inspector = getattr(gateway, "inspect_crops", None)
            if not callable(crop_inspector):
                raise TypeError("gateway must implement crop inspection")
            optional = {
                "page_number": page.number,
                "agent_role": agent_role,
                "stage": stage,
                "repair_round": repair_round,
            }
            signature = inspect.signature(crop_inspector)
            accepts_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            supported = {
                name: value
                for name, value in optional.items()
                if accepts_kwargs or name in signature.parameters
            }
            inspection_result = crop_inspector(requests, **supported)
            bound_decisions, binding_issue = _validated_crop_decisions(
                requests,
                inspection_result,
                source="Verification",
            )
            if binding_issue is not None:
                raise ValueError(binding_issue)
            return inspection_result.model_copy(
                update={"decisions": list(bound_decisions.values())}
            )

        warnings.extend(f"Page {page.number}: {item}" for item in draft.warnings)
        deferred_count = len(deferred_recovery_boxes or ())
        if deferred_count:
            reason = (
                "Visual recovery disabled"
                if not visual_recovery
                else (
                    "Visual recovery unavailable: OPENAI_API_KEY is not set"
                    if not recovery_available
                    else "Document visual recovery crop limit reached"
                )
            )
            for block in blocks:
                if (
                    _recovery_box_key(block.bbox) in deferred_recovery_boxes
                    and block.verification is not VerificationState.REJECTED
                ):
                    block.verification = VerificationState.NEEDS_REVIEW
                    block.verification_reason = reason
            warnings.append(
                f"Page {page.number}: deferred {deferred_count} visual recovery "
                f"candidate{'s' if deferred_count != 1 else ''}: {reason}"
            )
        risky = [
            (region, block)
            for region, block in zip(draft.regions, blocks, strict=True)
            if _needs_verification(block)
        ]
        decisions: dict[str, InspectionDecision] = {}
        resolution_failures: dict[str, str] = {}
        if risky:
            _emit(
                progress_callback,
                "verify",
                page.number,
                total,
                f"Verifying page {page.number}",
            )
            risky_ids = [block.id for _region, block in risky]
            try:
                raw_inspection = inspect_targets(
                    risky_ids,
                    agent_role=AgentRole.EVIDENCE_CRITIC,
                    repair_round=1,
                )
            except Exception as exc:  # noqa: BLE001 - verification is best-effort
                reason = f"Verification failed: {type(exc).__name__}: {exc}"
                for _region, block in risky:
                    block.verification = VerificationState.NEEDS_REVIEW
                    block.verification_reason = block.verification_reason or reason
            else:
                inspection_warnings = list(raw_inspection.warnings)
                for decision in raw_inspection.decisions:
                    region_id = decision.region_id
                    if region_id not in risky_ids:
                        inspection_warnings.append(
                            f"ignored decision for unexpected region ID {region_id}"
                        )
                        continue
                    if region_id in decisions or region_id in resolution_failures:
                        reason = f"Verification returned multiple decisions for {region_id}"
                        decisions.pop(region_id, None)
                        resolution_failures[region_id] = reason
                        inspection_warnings.append(reason)
                        continue
                    issue = _decision_issue(decision, region_id)
                    if issue is None:
                        decisions[region_id] = decision
                    else:
                        resolution_failures[region_id] = issue

                if raw_inspection.additional_regions:
                    warnings.append(
                        f"Page {page.number}: ignored "
                        f"{len(raw_inspection.additional_regions)} Luna-added "
                        "region(s); GLM owns element identity and geometry"
                    )
                if raw_inspection.ordered_region_ids:
                    warnings.append(
                        f"Page {page.number}: ignored Luna reading-order changes; "
                        "GLM owns reading order"
                    )
                warnings.extend(
                    f"Page {page.number}: {item}" for item in inspection_warnings
                )

        explicit_crop_ids: set[str] = set()
        candidate_pairs = [
            (region, block)
            for region, block in zip(draft.regions, blocks, strict=True)
            if block.id in decisions
            or any(block.id == risky_block.id for _, risky_block in risky)
        ]
        for _region, block in candidate_pairs:
            decision = decisions.get(block.id)
            if decision is None:
                block.verification = VerificationState.NEEDS_REVIEW
                block.verification_reason = (
                    block.verification_reason
                    or resolution_failures.get(block.id, "No verification decision")
                )
                continue
            if decision.action is InspectionAction.REJECT:
                _apply_decision(block, decision, page.number)
                continue
            if block.bbox is None:
                block.verification_reason = (
                    block.verification_reason or "Missing bounding box"
                )
                block.verification = VerificationState.NEEDS_REVIEW
                continue
            if decision.action is InspectionAction.INSPECT_CROP:
                explicit_crop_ids.add(block.id)
            else:
                _apply_decision(block, decision, page.number)
                if (
                    decision.action is InspectionAction.CORRECT
                    and block.verification is VerificationState.VERIFIED
                ):
                    recovered_region_ids.add(block.id)

        nonvisual_candidates: dict[str, tuple[int, Block]] = {
            block.id: (0, block)
            for block in blocks
            if block.id in explicit_crop_ids and block.type not in VISUAL_REGION_TYPES
        }
        for block in blocks:
            if block.verification is VerificationState.REJECTED or block.bbox is None:
                continue
            box = _recovery_box_key(block.bbox)
            if (
                allowed_recovery_boxes is not None
                and box in allowed_recovery_boxes
                and box not in used_recovery_boxes
                and block.type not in VISUAL_REGION_TYPES
            ):
                nonvisual_candidates[block.id] = (-1, block)
            priority = _proactive_crop_priority(block)
            if (
                priority is not None
                and block.type not in VISUAL_REGION_TYPES
                and block.id not in nonvisual_candidates
            ):
                nonvisual_candidates[block.id] = (priority, block)

        visual_blocks = [
            block
            for block in blocks
            if block.type in VISUAL_REGION_TYPES
            and block.verification is not VerificationState.REJECTED
            and block.bbox is not None
        ]
        requested_nonvisual = sorted(
            nonvisual_candidates.values(),
            key=lambda item: (
                item[0],
                item[1].confidence is None,
                item[1].confidence if item[1].confidence is not None else 1.0,
            ),
        )[:MAX_CROPS_PER_PAGE]
        requested_blocks = visual_blocks + [
            block for _priority, block in requested_nonvisual
        ]
        requested_ids = {block.id for block in requested_blocks}
        for block_id in explicit_crop_ids:
            if block_id not in requested_ids:
                block = next(item for item in blocks if item.id == block_id)
                block.verification = VerificationState.NEEDS_REVIEW
                block.verification_reason = "Crop inspection limit exceeded"

        crop_requests: list[CropInspectionRequest] = []
        crop_blocks: list[Block] = []
        for block in requested_blocks:
            if block.bbox is not None and consume_recovery_box(block.bbox):
                crop_path = workdir / f"{block.id}-crop.png"
                try:
                    render_region_crop(
                        source,
                        page,
                        block.bbox,
                        crop_path,
                        dpi=self.config.crop_dpi,
                        padding=(
                            max(self.config.crop_padding, 0.15)
                            if block.type in VISUAL_REGION_TYPES
                            else self.config.crop_padding
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - verification is best-effort
                    block.verification = VerificationState.NEEDS_REVIEW
                    block.verification_reason = (
                        f"Crop rendering failed: {type(exc).__name__}: {exc}"
                    )
                    continue
                crop_requests.append(
                    CropInspectionRequest(
                        crop_path=str(crop_path),
                        region_id=block.id,
                        candidate_region=_region_from_block(block),
                        evidence_ref=f"page:{page.number}:{block.id}",
                        source_page_pixels=source_page_pixels,
                    )
                )
                crop_blocks.append(block)
        for batch_start in range(0, len(crop_requests), MAX_CROPS_PER_PAGE):
            batch_requests = crop_requests[
                batch_start : batch_start + MAX_CROPS_PER_PAGE
            ]
            batch_blocks = crop_blocks[batch_start : batch_start + MAX_CROPS_PER_PAGE]
            visual_recovery_crops += len(batch_requests)
            try:
                crop_inspection = gateway.inspect_crops(batch_requests)
            except Exception as exc:  # noqa: BLE001 - verification is best-effort
                reason = f"Crop verification failed: {type(exc).__name__}: {exc}"
                for block in batch_blocks:
                    block.verification = VerificationState.NEEDS_REVIEW
                    block.verification_reason = reason
            else:
                crop_decisions, binding_issue = _validated_crop_decisions(
                    batch_requests,
                    crop_inspection,
                    source="Crop verification",
                )
                if binding_issue is not None:
                    warnings.append(f"Page {page.number}: {binding_issue}")
                    for block in batch_blocks:
                        block.verification = VerificationState.NEEDS_REVIEW
                        block.verification_reason = binding_issue
                    continue
                for block in batch_blocks:
                    crop_decision = crop_decisions.get(block.id)
                    if crop_decision is None:
                        block.verification = VerificationState.NEEDS_REVIEW
                        block.verification_reason = "No crop verification decision"
                    else:
                        _apply_decision(
                            block,
                            crop_decision,
                            page.number,
                            preserve_layout=True,
                        )
                        if (
                            crop_decision.action is InspectionAction.CORRECT
                            and block.verification is VerificationState.VERIFIED
                        ):
                            recovered_region_ids.add(block.id)

        quality_inspector = getattr(gateway, "inspect_quality_crops", None)
        if callable(quality_inspector):
            grounded_corrections: list[Block] = []

            selected: list[Block] = []
            selected_ids: set[str] = set()
            for block in select_repair_blocks(page, blocks, warnings):
                if block.id not in selected_ids:
                    selected.append(block)
                    selected_ids.add(block.id)
            for block in blocks:
                if (
                    block.verification is not VerificationState.REJECTED
                    and block.id not in selected_ids
                    and literal_repair_candidates(page, block)
                ):
                    selected.append(block)
                    selected_ids.add(block.id)

            quality_requests: list[CropInspectionRequest] = []
            quality_blocks: list[Block] = []
            span_requests: list[SpanRepairRequest] = []
            span_targets_by_block: dict[str, list[SpanRepairTarget]] = {}
            span_blocks: dict[str, Block] = {}
            span_repairer = getattr(gateway, "repair_spans", None)
            original_verification = {block.id: block.verification for block in selected}
            original_reasons = {
                block.id: block.verification_reason for block in selected
            }
            for block in selected:
                candidates = literal_repair_candidates(page, block)
                use_targeted = (
                    callable(span_repairer)
                    and bool(candidates)
                    and not requires_region_repair(page, block, warnings)
                )
                if use_targeted:
                    targets = [
                        target
                        for candidate in candidates
                        if (
                            target := _span_repair_target(
                                block,
                                candidate,
                                page_number=page.number,
                            )
                        )
                        is not None
                        and target.bbox is not None
                    ]
                    for index, target in enumerate(targets):
                        if not consume_recovery_box(target.bbox):
                            if _recovery_box_key(target.bbox) in (
                                deferred_recovery_boxes or set()
                            ):
                                block.verification = VerificationState.NEEDS_REVIEW
                                block.verification_reason = (
                                    "Visual recovery disabled"
                                    if not visual_recovery
                                    else "Document visual recovery crop limit reached"
                                )
                            continue
                        crop_path = workdir / f"{block.id}-span-{index + 1}.png"
                        try:
                            render_region_crop(
                                source,
                                page,
                                target.bbox,
                                crop_path,
                                dpi=self.config.crop_dpi,
                                padding=self.config.crop_padding,
                            )
                        except Exception as exc:  # noqa: BLE001 - review failure is auditable
                            block.verification = VerificationState.NEEDS_REVIEW
                            block.verification_reason = (
                                "Targeted repair crop failed: "
                                f"{type(exc).__name__}: {exc}"
                            )
                            continue
                        span_requests.append(
                            SpanRepairRequest(
                                crop_path=str(crop_path),
                                target=target,
                                source_page_pixels=source_page_pixels,
                            )
                        )
                        span_targets_by_block.setdefault(block.id, []).append(target)
                        span_blocks[block.id] = block
                    if targets:
                        continue
                if block.bbox is None:
                    if block.verification is not VerificationState.REJECTED:
                        block.verification = VerificationState.NEEDS_REVIEW
                        block.verification_reason = (
                            block.verification_reason
                            or "Quality repair requires valid geometry"
                        )
                    warnings.append(
                        f"Page {page.number}: quality gate unresolved block {block.id}"
                    )
                    continue
                if not consume_recovery_box(block.bbox):
                    continue
                crop_path = workdir / f"{block.id}-quality-crop.png"
                try:
                    render_region_crop(
                        source,
                        page,
                        block.bbox,
                        crop_path,
                        dpi=self.config.crop_dpi,
                        padding=max(self.config.crop_padding, 0.1),
                    )
                except Exception as exc:  # noqa: BLE001 - review failure is auditable
                    if original_verification[block.id] is VerificationState.REJECTED:
                        block.verification = VerificationState.REJECTED
                        block.verification_reason = original_reasons[block.id]
                    else:
                        block.verification = VerificationState.NEEDS_REVIEW
                        block.verification_reason = f"Quality crop rendering failed: {type(exc).__name__}: {exc}"
                    warnings.append(
                        f"Page {page.number}: quality gate unresolved block {block.id}"
                    )
                    continue
                quality_requests.append(
                    CropInspectionRequest(
                        crop_path=str(crop_path),
                        region_id=block.id,
                        candidate_region=_region_from_block(block),
                        evidence_ref=f"page:{page.number}:{block.id}:quality",
                        source_page_pixels=source_page_pixels,
                    )
                )
                quality_blocks.append(block)

            if quality_requests or span_requests:
                pending = list(zip(quality_requests, quality_blocks, strict=True))
                for repair_round in range(1, 2):
                    if span_requests:
                        for batch_start in range(
                            0, len(span_requests), MAX_REPAIR_BLOCKS
                        ):
                            batch = span_requests[
                                batch_start : batch_start + MAX_REPAIR_BLOCKS
                            ]
                            visual_recovery_crops += len(batch)
                            try:
                                span_inspection = span_repairer(
                                    batch,
                                    page_number=page.number,
                                )
                            except Exception as exc:  # noqa: BLE001 - repair fails closed
                                reason = (
                                    "Targeted span repair failed: "
                                    f"{type(exc).__name__}: {exc}"
                                )
                                for request in batch:
                                    block = span_blocks[request.target.region_id]
                                    block.verification = VerificationState.NEEDS_REVIEW
                                    block.verification_reason = reason
                                continue
                            decisions_by_block: dict[str, list[SpanRepairDecision]] = {}
                            for decision in span_inspection.decisions:
                                region_id = decision.target_id.split(":", 1)[0]
                                decisions_by_block.setdefault(region_id, []).append(
                                    decision
                                )
                            for region_id, targets in span_targets_by_block.items():
                                batch_ids = {
                                    request.target.target_id for request in batch
                                }
                                batch_targets = [
                                    target
                                    for target in targets
                                    if target.target_id in batch_ids
                                ]
                                if batch_targets:
                                    decisions = decisions_by_block.get(region_id, [])
                                    repaired_block = span_blocks[region_id]
                                    _apply_span_repairs(
                                        repaired_block,
                                        batch_targets,
                                        decisions,
                                        repair_source=self.config.cloud_model.value,
                                    )
                                    if any(
                                        decision.action is SpanRepairAction.REPLACE
                                        for decision in decisions
                                    ) and repaired_block.verification is VerificationState.VERIFIED:
                                        recovered_region_ids.add(region_id)
                        span_requests = []
                    for batch_start in range(0, len(pending), MAX_REPAIR_BLOCKS):
                        batch = pending[batch_start : batch_start + MAX_REPAIR_BLOCKS]
                        batch_requests = [request for request, _block_item in batch]
                        visual_recovery_crops += len(batch_requests)
                        try:
                            quality_inspection = quality_inspector(
                                batch_requests,
                                page_number=page.number,
                            )
                        except Exception as exc:  # noqa: BLE001 - review failure is auditable
                            fallback_reason = f"Quality verification failed: {type(exc).__name__}: {exc}"
                            quality_decisions = {}
                        else:
                            quality_decisions, binding_issue = (
                                _validated_crop_decisions(
                                    batch_requests,
                                    quality_inspection,
                                    source="Quality verification",
                                )
                            )
                            fallback_reason = binding_issue or (
                                "No conclusive quality verification decision"
                            )
                            if binding_issue is not None:
                                warnings.append(
                                    f"Page {page.number}: {binding_issue}"
                                )
                        for request, block in batch:
                            decision = quality_decisions.get(block.id)
                            if decision is not None and decision.action in {
                                InspectionAction.ACCEPT,
                                InspectionAction.CORRECT,
                            }:
                                _apply_decision(
                                    block,
                                    decision,
                                    page.number,
                                    preserve_layout=True,
                                )
                                if (
                                    decision.action is InspectionAction.CORRECT
                                    and block.verification is VerificationState.VERIFIED
                                ):
                                    recovered_region_ids.add(block.id)
                                if (
                                    decision.action is InspectionAction.CORRECT
                                    and block.verification is VerificationState.VERIFIED
                                    and semantic_text(block).strip()
                                ):
                                    grounded_corrections.append(block)
                                if block.verification is VerificationState.VERIFIED:
                                    continue

                            if (
                                decision is not None
                                and decision.action is InspectionAction.CORRECT
                                and block.verification_reason
                            ):
                                reason = block.verification_reason
                            elif decision is not None and decision.reason:
                                reason = decision.reason
                            else:
                                reason = fallback_reason
                            block.verification = VerificationState.NEEDS_REVIEW
                            block.verification_reason = reason

            grounded_corrections = [
                block
                for block in grounded_corrections
                if block.verification is VerificationState.VERIFIED
            ]

            if grounded_corrections:
                warnings.append(
                    f"Page {page.number}: recovered {len(grounded_corrections)} "
                    "grounded quality corrections"
                )
        blocks, normalization_warnings = normalize_page_blocks(blocks)
        for block in blocks:
            comparison = (ocr_comparisons or {}).get(_recovery_box_key(block.bbox) or ())
            if comparison is None:
                continue
            comparison.block_id = block.id
            if comparison.status == "disagreed":
                block.verification = VerificationState.NEEDS_REVIEW
                reason = "Local OCR engines disagreed on this uncertain region"
                if block.verification_reason and reason not in block.verification_reason:
                    block.verification_reason = f"{block.verification_reason}; {reason}"
                else:
                    block.verification_reason = block.verification_reason or reason
        warnings.extend(
            f"Page {page.number}: {warning}" for warning in normalization_warnings
        )
        input_tokens = int(getattr(gateway, "input_tokens", 0))
        output_tokens = int(getattr(gateway, "output_tokens", 0))
        usage = getattr(gateway, "usage", None)
        if not isinstance(usage, RunUsage):
            usage = RunUsage(
                calls=[
                    AgentUsage(
                        agent="document_pipeline",
                        model="mixed",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
                ]
            )
        return _ProcessedPage(
            page=Page(
                number=page.number,
                width=page.width,
                height=page.height,
                blocks=blocks,
                warnings=warnings,
                analysis=analysis,
            ),
            warnings=warnings,
            usage=usage,
            trace=list(getattr(gateway, "trace", [])),
            visual_recovery_crops=visual_recovery_crops,
            recovered_region_ids=sorted(recovered_region_ids),
        )

    def _refine_document(
        self,
        document: Document,
        runtime: ProviderRuntime,
        *,
        enabled: bool,
    ) -> tuple[str, EnhancementMetadata, RunUsage, list[AgentTraceEvent], float]:
        started = time.perf_counter()
        base_markdown = render_agentic_document(document).markdown
        if not enabled:
            return (
                base_markdown,
                EnhancementMetadata(enabled=False, status="off"),
                RunUsage(),
                [],
                0.0,
            )
        if self.gateway_factory is not OpenAIDocumentGateway:
            return (
                base_markdown,
                EnhancementMetadata(
                    status="unavailable",
                    warnings=["Custom gateway does not enable Markdown refinement"],
                ),
                RunUsage(),
                [],
                0.0,
            )
        if not os.getenv("OPENAI_API_KEY"):
            warning = "Markdown refinement unavailable: OPENAI_API_KEY is not set"
            return (
                base_markdown,
                EnhancementMetadata(status="unavailable", warnings=[warning]),
                RunUsage(),
                [],
                0.0,
            )

        chunks, skipped_pages = build_enhancement_chunks(document)
        warnings = [
            f"Page {page}: refinement skipped because its prompt exceeds the safe limit"
            for page in skipped_pages
        ]
        if not chunks:
            status = "failed" if skipped_pages else "succeeded"
            return (
                base_markdown,
                EnhancementMetadata(
                    status=status,
                    chunks_total=len(skipped_pages),
                    warnings=warnings,
                ),
                RunUsage(),
                [],
                time.perf_counter() - started,
            )

        def refine(chunk):
            gateway = self.gateway_factory(self.config)
            bind_runtime = getattr(gateway, "bind_runtime", None)
            if callable(bind_runtime):
                bind_runtime(runtime)
            refiner = getattr(gateway, "refine_markdown", None)
            if not callable(refiner):
                raise TypeError("gateway must implement text-only Markdown refinement")
            plan = refiner(chunk.anchored_markdown, chunk.layout)
            return (
                chunk,
                render_chunk_plan(document, chunk, plan),
                getattr(gateway, "usage", RunUsage()),
                list(getattr(gateway, "trace", [])),
            )

        refined_pages: dict[int, str] = {}
        chunk_results: dict[int, tuple] = {}
        failures = len(skipped_pages)
        usage = RunUsage()
        trace: list[AgentTraceEvent] = []
        with ThreadPoolExecutor(
            max_workers=min(self.config.provider_concurrency, len(chunks)),
            thread_name_prefix="docparse-refinement",
        ) as executor:
            futures = {executor.submit(refine, chunk): chunk for chunk in chunks}
            for future, chunk in futures.items():
                try:
                    chunk_results[chunk.index] = future.result()
                except Exception as exc:  # noqa: BLE001 - refinement always falls back
                    failures += 1
                    warnings.append(
                        f"Pages {chunk.page_numbers}: refinement failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
        for index in sorted(chunk_results):
            _chunk, page_markdown, chunk_usage, chunk_trace = chunk_results[index]
            refined_pages.update(page_markdown)
            if isinstance(chunk_usage, RunUsage):
                usage.calls.extend(chunk_usage.calls)
            trace.extend(chunk_trace)

        succeeded = len(chunk_results)
        status = (
            "succeeded"
            if failures == 0
            else "partial"
            if succeeded
            else "failed"
        )
        return (
            combine_page_markdown(document, refined_pages),
            EnhancementMetadata(
                status=status,
                chunks_total=len(chunks) + len(skipped_pages),
                chunks_enhanced=succeeded,
                warnings=warnings,
            ),
            usage,
            trace,
            time.perf_counter() - started,
        )

    def parse(
        self,
        data: bytes,
        filename: str,
        progress_callback: ProgressCallback | None = None,
        *,
        refine_markdown: bool = True,
        visual_recovery: bool = True,
    ) -> ParseResult:
        started = time.perf_counter()
        runtime = ProviderRuntime(self.config)
        analyzer = PageAnalyzer(self.config)
        with tempfile.TemporaryDirectory(prefix="docparse-") as temporary:
            workdir = Path(temporary)
            source = ingest_document(
                data,
                filename,
                workdir,
                dpi=self.config.render_dpi,
                max_bytes=self.config.max_upload_bytes,
                max_pages=self.config.max_pages,
                max_page_pixels=self.config.max_page_pixels,
            )
            if self.config.ocr_disagreement_enabled:
                self.ocr_service_switcher(self.config.ocr_engine)
            if (
                self.gateway_factory is OpenAIDocumentGateway
                and self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6
            ):
                analyzer.prepare_document(source.source_path, source.pages)
            pages: list[Page] = []
            warnings: list[str] = []
            sections: list[str] = []
            usage = RunUsage()
            trace: list[AgentTraceEvent] = []
            recovered_region_ids: set[str] = set()
            visual_recovery_crops = 0
            total = len(source.pages)
            effective_visual_recovery = visual_recovery and (
                self.gateway_factory is not OpenAIDocumentGateway
                or bool(os.getenv("OPENAI_API_KEY"))
            )
            progress_events: SimpleQueue[ProgressEvent] = SimpleQueue()

            def queue_progress(event: ProgressEvent) -> None:
                progress_events.put(event)

            def drain_progress() -> None:
                if progress_callback is None:
                    return
                while True:
                    try:
                        event = progress_events.get_nowait()
                    except Empty:
                        return
                    progress_callback(event)

            analyses_by_page: dict[int, PageAnalysis | None] = {}
            analyzed_count = 0
            for batch_start in range(0, total, self.config.page_batch_size):
                batch = source.pages[
                    batch_start : batch_start + self.config.page_batch_size
                ]
                _emit(
                    progress_callback,
                    "batch",
                    batch[0].number,
                    total,
                    f"Processing pages {batch[0].number}-{batch[-1].number}",
                )
                if self.gateway_factory is OpenAIDocumentGateway:
                    for analysis in analyzer.analyze_window(batch):
                        page_number = analysis.render.source_page
                        analyses_by_page[page_number] = analysis
                        analyzed_count += 1
                        _emit(
                            progress_callback,
                            "layout",
                            analyzed_count,
                            total,
                            f"Detected layout on page {page_number}",
                        )
                else:
                    for page in batch:
                        analyses_by_page[page.number] = None

            if self.gateway_factory is OpenAIDocumentGateway:
                nonblank = [
                    analysis
                    for analysis in analyses_by_page.values()
                    if analysis is not None and not analysis.quality.blank
                ]
                if nonblank and all(not analysis.regions for analysis in nonblank):
                    raise RuntimeError(
                        f"{self.config.ocr_engine.label} produced no usable elements "
                        "for any nonblank page"
                    )
                ocr_regions = [
                    region
                    for analysis in nonblank
                    for region in analysis.regions
                    if region.type is not AnalysisRegionType.FIGURE
                ]
                recognition_failed = any(
                    "GLM-OCR recognition failed" in warning
                    for analysis in nonblank
                    for warning in analysis.warnings
                )
                if (
                    recognition_failed
                    and ocr_regions
                    and all(not region.text.strip() for region in ocr_regions)
                ):
                    raise RuntimeError(
                        "GLM-OCR recognition failed for all detected OCR regions on "
                        "nonblank pages"
                    )

            glm_time = time.perf_counter() - started

            paddle_form_recovery = (
                _recover_paddle_form_regions(
                    source,
                    source.pages,
                    analyses_by_page,
                    workdir,
                    self.config,
                )
                if self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6
                else _PaddleFormRecovery()
            )
            warnings.extend(paddle_form_recovery.warnings)
            effective_glm_form_recovery = (
                self.config.ocr_engine is OcrEngine.GLM_OCR
                and visual_recovery
                and self.config.glm_form_recovery_enabled
            )
            glm_form_recovery = (
                _recover_glm_form_regions(
                    source,
                    source.pages,
                    analyses_by_page,
                    workdir,
                    self.config,
                )
                if effective_glm_form_recovery
                else _GlmFormRecovery()
            )
            warnings.extend(glm_form_recovery.warnings)
            visual_recovery_crops = (
                glm_form_recovery.crops + paddle_form_recovery.attempts
            )
            if self.config.ocr_disagreement_enabled:
                _emit(
                    progress_callback,
                    "cross_check",
                    1,
                    1,
                    "Cross-checking uncertain regions with alternate local OCR",
                )
            ocr_comparisons, ocr_comparison_candidates, ocr_comparison_time = (
                self._cross_check_uncertain_regions(
                    source, source.pages, analyses_by_page, workdir
                )
            )
            comparisons_by_page: dict[
                int, dict[RecoveryBoxKey, OcrComparisonResult]
            ] = {}
            for comparison in ocr_comparisons:
                if comparison.bbox is not None:
                    comparisons_by_page.setdefault(comparison.page, {})[
                        comparison.bbox
                    ] = comparison
            luna_recovery_budget = _visual_recovery_crop_budget(
                total,
                ceiling=self.config.max_visual_recovery_crops,
            )

            planning_applies = self.gateway_factory is OpenAIDocumentGateway
            if planning_applies:
                recovery_plan = _visual_recovery_plan(
                    source.pages,
                    analyses_by_page,
                    enabled=effective_visual_recovery,
                    limit=luna_recovery_budget,
                )
                allowed_recovery = recovery_plan.allowed
                deferred_recovery = recovery_plan.deferred
                recovery_candidate_count = recovery_plan.candidate_count
                for page_number, statuses in glm_form_recovery.statuses.items():
                    if page_number in deferred_recovery:
                        deferred_recovery[page_number].difference_update(statuses)
            else:
                allowed_recovery, deferred_recovery, recovery_candidate_count = (
                    {},
                    {},
                    0,
                )

            with ThreadPoolExecutor(
                max_workers=min(self.config.max_page_concurrency, total),
                thread_name_prefix="docparse-page",
            ) as executor:
                for batch_start in range(0, total, self.config.page_batch_size):
                    batch = source.pages[
                        batch_start : batch_start + self.config.page_batch_size
                    ]
                    futures = {}
                    for page in batch:
                        future = executor.submit(
                            self._process_page,
                            source,
                            page,
                            workdir,
                            total,
                            queue_progress if progress_callback is not None else None,
                            runtime,
                            analyzer,
                            analyses_by_page[page.number],
                            visual_recovery,
                            allowed_recovery.get(page.number, set())
                            if planning_applies
                            else None,
                            deferred_recovery.get(page.number, set())
                            if planning_applies
                            else None,
                            glm_form_recovery.statuses.get(page.number, {}),
                            comparisons_by_page.get(page.number, {}),
                        )
                        futures[future] = page.number
                    pending = set(futures)
                    processed: list[_ProcessedPage] = []
                    completed_count = batch_start
                    while pending:
                        done, pending = wait(
                            pending,
                            timeout=0.05,
                            return_when=FIRST_COMPLETED,
                        )
                        drain_progress()
                        for future in done:
                            try:
                                processed.append(future.result())
                                completed_count += 1
                                _emit(
                                    progress_callback,
                                    "recognize",
                                    completed_count,
                                    total,
                                    f"Recognized page {futures[future]}",
                                )
                            except Exception:
                                for remaining in pending:
                                    remaining.cancel()
                                raise
                    drain_progress()

                    for result in sorted(processed, key=lambda item: item.page.number):
                        roots, sections = _hierarchy(result.page.blocks, sections)
                        pages.append(
                            Page(
                                number=result.page.number,
                                width=result.page.width,
                                height=result.page.height,
                                blocks=roots,
                                warnings=result.page.warnings,
                                quality=result.page.quality,
                                analysis=result.page.analysis,
                            )
                        )
                        warnings.extend(result.warnings)
                        usage.calls.extend(result.usage.calls)
                        trace.extend(result.trace)
                        visual_recovery_crops += result.visual_recovery_crops
                        recovered_region_ids.update(result.recovered_region_ids)

            document = Document(
                source_name=source.name,
                source_sha256=source.sha256,
                pages=pages,
                warnings=warnings,
            )
            materialize_document_quality(document)
            recovery_log = _build_recovery_log(document, recovered_region_ids)
            _emit(
                progress_callback,
                "assemble",
                1,
                1,
                "Assembling Markdown and structured JSON",
            )
            elements = build_elements(
                document,
                recovered_region_ids,
                local_source=self.config.ocr_engine.value,
            )
            base_markdown = render_agentic_document(document).markdown
            _emit(
                progress_callback,
                "annotate",
                1,
                1,
                "Rendering PDF annotations",
            )
            annotated_pdf = render_annotated_pdf(
                data,
                source.name,
                elements,
                page_count=len(document.pages),
            )
            visual_parse_time = time.perf_counter() - started
            if refine_markdown:
                _emit(
                    progress_callback,
                    "enhance",
                    1,
                    1,
                    f"Refining Markdown structure with {self.config.cloud_model.value}",
                )
            (
                final_markdown,
                enhancement,
                refinement_usage,
                refinement_trace,
                refinement_time,
            ) = self._refine_document(
                document,
                runtime,
                enabled=refine_markdown,
            )
            usage.calls.extend(refinement_usage.calls)
            trace.extend(refinement_trace)
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            runtime_diagnostics = runtime.diagnostics()
            duration_ms = round((time.perf_counter() - started) * 1000)
            version_getter = getattr(analyzer, "model_versions", None)
            model_versions = version_getter() if callable(version_getter) else {}
            luna_recovery_time = sum(
                event.duration_ms for event in trace if event.image_count
            ) / 1000
            luna_agentic_time = sum(
                event.duration_ms for event in trace if not event.image_count
            ) / 1000
            metadata = ParseMetadata(
                engine=(
                    f"{self.config.ocr_engine.value} + {self.config.cloud_model.value}"
                    if trace
                    else self.config.ocr_engine.value
                ),
                pages=len(document.pages),
                processing_time=duration_ms / 1000,
                visual_parse_time=visual_parse_time,
                refinement_time=refinement_time,
                visual_recovery_request_time=sum(
                    event.duration_ms for event in trace if event.image_count
                )
                / 1000
                + glm_form_recovery.duration,
                visual_recovery_enabled=(
                    effective_visual_recovery or effective_glm_form_recovery
                ),
                visual_recovery_candidates=(
                    recovery_candidate_count + glm_form_recovery.candidate_count
                ),
                visual_recovery_crops=visual_recovery_crops,
                visual_recovery_deferred=sum(
                    len(boxes) for boxes in deferred_recovery.values()
                ),
                visual_recovery_region_ids=sorted(recovered_region_ids),
                glm_time=(
                    glm_time if self.config.ocr_engine is OcrEngine.GLM_OCR else 0.0
                ),
                luna_recovery_time=luna_recovery_time,
                luna_agentic_time=luna_agentic_time,
                luna_time=luna_recovery_time + luna_agentic_time,
                recovered_regions=len(recovery_log),
                ocr_comparison_enabled=self.config.ocr_disagreement_enabled,
                ocr_comparison_candidates=ocr_comparison_candidates,
                ocr_comparison_crops=sum(
                    item.status != "unavailable" for item in ocr_comparisons
                ),
                ocr_comparison_disagreements=sum(
                    item.status == "disagreed" for item in ocr_comparisons
                ),
                ocr_comparison_unavailable=sum(
                    item.status == "unavailable" for item in ocr_comparisons
                ),
                ocr_comparison_deferred=max(
                    0, ocr_comparison_candidates - len(ocr_comparisons)
                ),
                ocr_comparison_time=ocr_comparison_time,
                ocr_comparison_secondary_engine=(
                    (
                        OcrEngine.PADDLEOCR_VL_1_6
                        if self.config.ocr_engine is OcrEngine.GLM_OCR
                        else OcrEngine.GLM_OCR
                    ).value
                    if self.config.ocr_disagreement_enabled
                    else None
                ),
                model_versions=model_versions,
                enhancement=enhancement,
            )
            rendered = render_agentic_document(
                document,
                usage=usage,
                trace=trace,
                runtime_diagnostics=runtime_diagnostics,
                duration_ms=duration_ms,
                elements=elements,
                parse_metadata=metadata,
                markdown_override=final_markdown,
                recovery_log=recovery_log,
                ocr_comparisons=ocr_comparisons,
            )
            _emit(progress_callback, "complete", 1, 1, "Parsing complete")
            return ParseResult(
                document=document,
                markdown=rendered.markdown,
                json=rendered.json,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                annotated_pdf=annotated_pdf,
                base_markdown=base_markdown,
                usage=usage,
                trace=trace,
                runtime_diagnostics=runtime_diagnostics,
                elements=elements,
                metadata=metadata,
                recovery_log=recovery_log,
                ocr_comparisons=ocr_comparisons,
            )
