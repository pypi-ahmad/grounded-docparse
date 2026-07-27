from __future__ import annotations

import json
import re
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, SimpleQueue

from .config import ParserConfig
from .gateways import OpenAIDocumentGateway
from .ingest import IngestedDocument, PageEvidence, ingest_document, render_region_crop
from .models import (
    AgentRole,
    AgentTraceEvent,
    AgentUsage,
    AtomicDraft,
    AtomicEvidence,
    Block,
    BoundingBox,
    ConfidenceSpan,
    Citation,
    CorrectionLineage,
    CropInspectionRequest,
    Document,
    DraftBoundingBox,
    FormData,
    InspectionAction,
    InspectionDecision,
    InspectionRegionAddition,
    NodeType,
    Page,
    PageInspection,
    ParseResult,
    ProgressCallback,
    ProgressEvent,
    RegionDraft,
    RunUsage,
    SpecialistAdditionOpinion,
    SpecialistAdditionResolution,
    SpecialistAudit,
    SpecialistOpinion,
    SpecialistOrderingOpinion,
    SpecialistOrderingResolution,
    SpecialistResolution,
    TableCell,
    TableCellDraft,
    TableData,
    VerificationState,
)
from .quality import (
    MAX_REPAIR_BLOCKS,
    find_missing_source_regions,
    normalize_page_blocks,
    select_repair_blocks,
    semantic_text,
)
from .render import (
    materialize_document_quality,
    render_agentic_document,
    render_annotated_pdf,
    render_json,
)

VERIFICATION_CONFIDENCE_THRESHOLD = 0.85
MAX_CROPS_PER_PAGE = 8
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
CRITICAL_LITERAL_PATTERN = re.compile(
    r"(?:\d|https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"
)
CRITICAL_WARNING_MARKERS = ("MUST", "DO NOT", "WILL NOT", "REQUIRED", "WARNING", "IMPORTANT")
AMBIGUOUS_LITERAL_PATTERN = re.compile(
    r"(?:https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|#{2,}|\b(?=\w*[A-Za-z])(?=\w*\d)[A-Za-z0-9_-]{5,}\b)"
)
VISUAL_REGION_TYPES = {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}
INVALID_CONFIDENCE_EVIDENCE_REASON = "Invalid confidence evidence"


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.translate({ord("\u00ad"): None, ord("\u200b"): None, ord("\ufeff"): None})


_REMOVED_TEXT_CODEPOINTS = frozenset({"\u00ad", "\u200b", "\ufeff"})


def _clean_form_data(value: FormData | None) -> FormData | None:
    if value is None:
        return None
    return FormData(
        label=_clean_text(value.label) or "Field",
        value=_clean_text(value.value),
        hint=_clean_text(value.hint),
    )


def _emit(callback: ProgressCallback | None, stage: str, current: int, total: int, message: str) -> None:
    if callback is not None:
        callback(ProgressEvent(stage=stage, current=current, total=total, message=message))


def _form(region: RegionDraft) -> FormData | None:
    if region.type is not NodeType.FORM_FIELD:
        return None
    if region.form is not None:
        return _clean_form_data(region.form)
    label, separator, value = (_clean_text(region.text) or "").partition(":")
    return FormData(label=label.strip() or "Field", value=value.strip() if separator else None)


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
) -> tuple[str, list[ConfidenceSpan], bool]:
    valid, invalid = _valid_confidence_spans(text, spans)
    cleaned = _clean_text(text) or ""
    rebased: list[ConfidenceSpan] = []
    for span in valid:
        if any(character in _REMOVED_TEXT_CODEPOINTS for character in text[span.start : span.end]):
            invalid = True
            continue
        rebased.append(
            ConfidenceSpan(
                start=sum(character not in _REMOVED_TEXT_CODEPOINTS for character in text[: span.start]),
                end=sum(character not in _REMOVED_TEXT_CODEPOINTS for character in text[: span.end]),
            )
        )
    return cleaned, rebased, invalid


def _table(region: RegionDraft) -> tuple[TableData | None, bool]:
    if region.type is not NodeType.TABLE:
        return None, False
    invalid = False
    cells: list[TableCell] = []
    for cell in region.table_cells:
        text, spans, spans_invalid = _clean_confidence_spans(
            cell.text,
            cell.low_confidence_spans,
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
                bbox=_bbox(cell.bbox),
                confidence=cell.confidence,
                low_confidence_spans=spans,
            )
        )
    return TableData(cells=cells), invalid


def _atoms(region: RegionDraft) -> tuple[list[AtomicEvidence], bool]:
    invalid = False
    atoms: list[AtomicEvidence] = []
    for atom in region.atoms:
        text, spans, spans_invalid = _clean_confidence_spans(
            atom.text,
            atom.low_confidence_spans,
        )
        invalid = invalid or spans_invalid
        atoms.append(
            AtomicEvidence(
                kind=atom.kind,
                text=text,
                bbox=_bbox(atom.bbox),
                confidence=atom.confidence,
                low_confidence_spans=spans,
            )
        )
    return atoms, invalid


def _aggregated_confidence(region: RegionDraft) -> float:
    values = [
        region.confidence,
        *(cell.confidence for cell in region.table_cells if cell.confidence is not None),
        *(atom.confidence for atom in region.atoms if atom.confidence is not None),
    ]
    return min(values)


def _has_low_confidence_spans(block: Block) -> bool:
    return bool(
        any(atom.low_confidence_spans for atom in block.atoms)
        or (
            block.table is not None
            and any(cell.low_confidence_spans for cell in block.table.cells)
        )
    )


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


def _needs_verification(region: RegionDraft, block: Block) -> bool:
    return (
        block.confidence < VERIFICATION_CONFIDENCE_THRESHOLD
        or _has_low_confidence_spans(block)
        or block.verification is VerificationState.NEEDS_REVIEW
        or region.type in COMPLEX_REGION_TYPES
        or bool(CRITICAL_LITERAL_PATTERN.search(region.text))
        or any(marker in region.text for marker in CRITICAL_WARNING_MARKERS)
    )


def _apply_correction(
    block: Block,
    region: RegionDraft,
    page_number: int,
    *,
    preserve_layout: bool = False,
) -> bool:
    bbox = _bbox(region.bbox)
    if not preserve_layout and (region.bbox is None or bbox is None):
        block.verification = VerificationState.NEEDS_REVIEW
        block.verification_reason = "Correction contained an invalid bounding box"
        return False
    block.type = region.type
    block.text = _clean_text(region.text) or ""
    if not preserve_layout:
        block.bbox = bbox
        block.reading_order = region.reading_order
    table, invalid_table_confidence = _table(region)
    atoms, invalid_atom_confidence = _atoms(region)
    block.confidence = _aggregated_confidence(region)
    if not preserve_layout:
        block.citation = Citation(page=page_number, bbox=bbox)
    block.heading_level = region.heading_level
    block.list_marker = region.list_marker
    block.table = table
    block.form = _form(region)
    block.checkbox_state = region.checkbox_state
    block.checkbox_group = region.checkbox_group
    block.checkbox_option = region.checkbox_option
    block.caption = _clean_text(region.caption)
    block.figure_description = _clean_text(region.figure_description)
    block.chart_type = _clean_text(region.chart_type)
    block.chart_data = [
        point.model_copy(
            update={
                "label": _clean_text(point.label) or "",
                "value": _clean_text(point.value) or "",
                "series": _clean_text(point.series),
            }
        )
        for point in region.chart_data
    ]
    block.atoms = atoms
    if invalid_table_confidence or invalid_atom_confidence:
        block.verification = VerificationState.NEEDS_REVIEW
        block.verification_reason = INVALID_CONFIDENCE_EVIDENCE_REASON
        return False
    block.verification_reason = None
    return True


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
        elif _apply_correction(
            block,
            decision.corrected_region,
            page_number,
            preserve_layout=preserve_layout,
        ):
            block.verification = VerificationState.VERIFIED
    elif decision.action is InspectionAction.REJECT:
        block.verification = VerificationState.REJECTED
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


def _visible_region_text(region: RegionDraft) -> str:
    values = [region.text]
    values.extend(cell.text for cell in region.table_cells)
    if region.form is not None:
        values.extend(
            [region.form.label, region.form.value or "", region.form.hint or ""]
        )
    values.extend((region.checkbox_group or "", region.checkbox_option or ""))
    values.extend((region.caption or "", region.figure_description or ""))
    return " ".join(
        " ".join(value.split()) for value in values if value
    ).casefold()


def _box_overlap(left: BoundingBox, right: BoundingBox) -> float:
    width = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    height = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    intersection = width * height
    left_area = (left.x1 - left.x0) * (left.y1 - left.y0)
    right_area = (right.x1 - right.x0) * (right.y1 - right.y0)
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _matching_addition_blocks(region: RegionDraft, blocks: list[Block]) -> list[Block]:
    text = _visible_region_text(region)
    bbox = _bbox(region.bbox)
    matches: list[Block] = []
    for block in blocks:
        existing = " ".join(semantic_text(block).split()).casefold()
        exact_text = bool(text and text == existing)
        strong_overlap = (
            bbox is not None
            and block.bbox is not None
            and block.type is region.type
            and _box_overlap(bbox, block.bbox) >= 0.8
        )
        if exact_text or strong_overlap:
            matches.append(block)
    return matches


def _proactive_crop_priority(block: Block) -> int | None:
    searchable = "\n".join(
        value
        for value in (block.text, block.caption, block.figure_description)
        if value
    )
    if AMBIGUOUS_LITERAL_PATTERN.search(searchable):
        return 1
    return None


def _has_excessive_order_movement(
    supplied: list[str], original_ids: list[str]
) -> bool:
    proposed_existing = [region_id for region_id in supplied if region_id in original_ids]
    positions = {region_id: index for index, region_id in enumerate(proposed_existing)}
    maximum_movement = max(3, len(original_ids) // 4)
    return any(
        abs(positions[region_id] - original_index) > maximum_movement
        for original_index, region_id in enumerate(original_ids)
    )


def _canonical_decision(decision: InspectionDecision) -> tuple[str, str]:
    corrected = (
        decision.corrected_region.model_dump(mode="json")
        if decision.corrected_region is not None
        else None
    )
    return (
        decision.action.value,
        json.dumps(corrected, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


def _canonical_addition(addition: InspectionRegionAddition) -> str:
    return json.dumps(
        addition.region.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _addition_issue(
    addition: InspectionRegionAddition,
    region_id: str | None = None,
    *,
    source: str = "Verification",
) -> str | None:
    if region_id is not None and addition.region_id != region_id:
        return f"{source} returned a different additional region ID"
    if _bbox(addition.region.bbox) is None:
        return f"{source} addition contained an invalid bounding box"
    return None


def _same_addition_target(
    left: InspectionRegionAddition,
    right: InspectionRegionAddition,
) -> bool:
    if left.region_id == right.region_id:
        return True
    left_box = _bbox(left.region.bbox)
    right_box = _bbox(right.region.bbox)
    if left_box is None or right_box is None:
        return False
    width = max(0.0, min(left_box.x1, right_box.x1) - max(left_box.x0, right_box.x0))
    height = max(0.0, min(left_box.y1, right_box.y1) - max(left_box.y0, right_box.y0))
    intersection = width * height
    smaller = min(
        (left_box.x1 - left_box.x0) * (left_box.y1 - left_box.y0),
        (right_box.x1 - right_box.x0) * (right_box.y1 - right_box.y0),
    )
    return bool(smaller and intersection / smaller >= 0.5)


def _cluster_addition_opinions(
    opinions: list[SpecialistAdditionOpinion],
) -> list[list[SpecialistAdditionOpinion]]:
    remaining = list(opinions)
    clusters: list[list[SpecialistAdditionOpinion]] = []
    while remaining:
        cluster = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            for opinion in list(remaining):
                if any(
                    _same_addition_target(opinion.addition, item.addition)
                    for item in cluster
                ):
                    cluster.append(opinion)
                    remaining.remove(opinion)
                    changed = True
        clusters.append(cluster)
    return clusters


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
        if _bbox(decision.corrected_region.bbox) is None:
            return (
                f"{source} correction contained an invalid bounding box"
                if source == "Arbitration"
                else "Correction contained an invalid bounding box"
            )
    elif decision.corrected_region is not None:
        return f"{source} returned a correction for a non-correct decision"
    return None


def _hierarchy(blocks: list[Block], inherited_sections: list[str]) -> tuple[list[Block], list[str]]:
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


@dataclass(frozen=True, slots=True)
class _TaggedInspection:
    inspection: PageInspection
    reviewer: str
    model: str
    timestamp: datetime
    target_ids: list[str]


class DocumentParser:
    def __init__(
        self,
        config: ParserConfig | None = None,
        *,
        gateway_factory: Callable[[ParserConfig], object] = OpenAIDocumentGateway,
    ) -> None:
        self.config = config or ParserConfig.from_env()
        self.gateway_factory = gateway_factory

    def _process_page(
        self,
        source: IngestedDocument,
        page: PageEvidence,
        workdir: Path,
        total: int,
        progress_callback: ProgressCallback | None,
    ) -> _ProcessedPage:
        gateway = self.gateway_factory(self.config)
        warnings: list[str] = []
        _emit(progress_callback, "draft", page.number, total, f"Reading page {page.number}")
        draft = gateway.draft_page(page)
        blocks = [_block(region, page.number, index) for index, region in enumerate(draft.regions)]
        all_region_ids = [block.id for block in blocks]
        warnings.extend(f"Page {page.number}: {item}" for item in draft.warnings)
        risky = [
            (region, block)
            for region, block in zip(draft.regions, blocks, strict=True)
            if _needs_verification(region, block)
        ]
        decisions: dict[str, InspectionDecision] = {}
        resolution_failures: dict[str, str] = {}
        specialist_audit = SpecialistAudit()
        ordering_conflict = False
        inspection = None
        if risky:
            _emit(progress_callback, "verify", page.number, total, f"Verifying page {page.number}")
            risky_ids = [block.id for _region, block in risky]
            inspections: list[_TaggedInspection] = []
            manager_flow = callable(getattr(gateway, "plan_page", None))
            if manager_flow:
                prior_inspections: list[dict] = []
                for repair_round in range(1, 3):
                    try:
                        plan = gateway.plan_page(
                            page,
                            draft,
                            region_ids=all_region_ids,
                            target_region_ids=risky_ids,
                            repair_round=repair_round,
                            prior_inspections=list(prior_inspections),
                        )
                    except Exception as exc:  # noqa: BLE001 - manager failure is isolated
                        warnings.append(
                            f"Page {page.number}: manager round {repair_round} failed: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        break
                    for delegation in plan.delegations[:2]:
                        targets = [
                            region_id
                            for region_id in delegation.target_region_ids
                            if region_id in all_region_ids
                        ]
                        if not targets:
                            continue
                        use_terra = delegation.use_terra and any(
                            region_id in risky_ids for region_id in targets
                        )
                        _emit(
                            progress_callback,
                            "delegate",
                            page.number,
                            total,
                            f"{delegation.role.value} reviewing page {page.number}",
                        )
                        try:
                            delegated_inspection = gateway.inspect_page(
                                page,
                                draft,
                                region_ids=all_region_ids,
                                target_region_ids=targets,
                                agent_role=delegation.role,
                                use_terra=use_terra,
                            )
                            inspections.append(
                                _TaggedInspection(
                                    inspection=delegated_inspection,
                                    reviewer=delegation.role.value,
                                    model=(
                                        self.config.terra_model
                                        if use_terra
                                        else self.config.luna_model
                                    ),
                                    timestamp=datetime.now(UTC),
                                    target_ids=targets,
                                )
                            )
                            prior_inspections.append(
                                delegated_inspection.model_dump(mode="json")
                            )
                        except Exception as exc:  # noqa: BLE001 - subagent failure is isolated
                            warnings.append(
                                f"Page {page.number}: {delegation.role.value} failed: "
                                f"{type(exc).__name__}: {exc}"
                            )
                    if plan.finish:
                        break
            else:
                try:
                    delegated_inspection = gateway.inspect_page(
                        page,
                        draft,
                        region_ids=all_region_ids,
                        target_region_ids=risky_ids,
                    )
                    inspections.append(
                        _TaggedInspection(
                            inspection=delegated_inspection,
                            reviewer=AgentRole.EVIDENCE_CRITIC.value,
                            model=self.config.luna_model,
                            timestamp=datetime.now(UTC),
                            target_ids=risky_ids,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - verification is best-effort
                    reason = f"Verification failed: {type(exc).__name__}: {exc}"
                    for _region, block in risky:
                        block.verification = VerificationState.NEEDS_REVIEW
                        block.verification_reason = block.verification_reason or reason

            if inspections:
                additions = []
                ordered_region_ids: list[str] = []
                inspection_warnings: list[str] = []
                opinions_by_region: dict[str, list[SpecialistOpinion]] = {}
                addition_opinions: list[SpecialistAdditionOpinion] = []
                for tagged in inspections:
                    item = tagged.inspection
                    inspection_warnings.extend(item.warnings)
                    for addition in item.additional_regions:
                        addition_opinion = SpecialistAdditionOpinion(
                            reviewer=tagged.reviewer,
                            model=tagged.model,
                            timestamp=tagged.timestamp,
                            addition=addition,
                        )
                        specialist_audit.addition_opinions.append(addition_opinion)
                        addition_opinions.append(addition_opinion)
                    for decision in item.decisions:
                        opinion = SpecialistOpinion(
                            reviewer=tagged.reviewer,
                            model=tagged.model,
                            timestamp=tagged.timestamp,
                            decision=decision,
                            confidence=decision.confidence,
                            reasoning=decision.reason,
                        )
                        specialist_audit.opinions.append(opinion)
                        if (
                            decision.region_id not in all_region_ids
                            or decision.region_id not in tagged.target_ids
                        ):
                            inspection_warnings.append(
                                f"ignored {tagged.reviewer} decision for unexpected region ID "
                                f"{decision.region_id}"
                            )
                            continue
                        opinions_by_region.setdefault(decision.region_id, []).append(opinion)
                    if item.ordered_region_ids:
                        specialist_audit.ordering_opinions.append(
                            SpecialistOrderingOpinion(
                                reviewer=tagged.reviewer,
                                model=tagged.model,
                                timestamp=tagged.timestamp,
                                ordered_region_ids=item.ordered_region_ids,
                            )
                        )

                conflicting_ids: list[str] = []
                resolutions: dict[str, SpecialistResolution] = {}
                for region_id in risky_ids:
                    opinions = opinions_by_region.get(region_id, [])
                    if not opinions:
                        reason = "No verification decision"
                        resolution_failures[region_id] = reason
                        resolutions[region_id] = SpecialistResolution(
                            region_id=region_id,
                            outcome="needs_review",
                            reasoning=reason,
                        )
                        continue
                    issue = next(
                        (
                            issue
                            for opinion in opinions
                            if (
                                issue := _decision_issue(
                                    opinion.decision,
                                    region_id,
                                )
                            )
                        ),
                        None,
                    )
                    canonical = {
                        _canonical_decision(opinion.decision) for opinion in opinions
                    }
                    if issue is not None:
                        resolution_failures[region_id] = issue
                        resolutions[region_id] = SpecialistResolution(
                            region_id=region_id,
                            outcome="needs_review",
                            reasoning=issue,
                        )
                    elif len(canonical) == 1:
                        final_decision = opinions[0].decision
                        decisions[region_id] = final_decision
                        resolutions[region_id] = SpecialistResolution(
                            region_id=region_id,
                            outcome="consensus" if len(opinions) > 1 else "single",
                            final_decision=final_decision,
                            reasoning=(
                                "Specialists agreed on action and corrected payload"
                                if len(opinions) > 1
                                else "Single specialist opinion"
                            ),
                        )
                    else:
                        conflicting_ids.append(region_id)

                if conflicting_ids and manager_flow:
                    arbitration_reason: str | None = None
                    try:
                        arbitration = gateway.inspect_page(
                            page,
                            draft,
                            region_ids=all_region_ids,
                            target_region_ids=conflicting_ids,
                            agent_role=AgentRole.EVIDENCE_CRITIC,
                            use_terra=True,
                        )
                    except Exception as exc:  # noqa: BLE001 - arbitration fails closed
                        arbitration_reason = (
                            f"Arbitration failed: {type(exc).__name__}: {exc}"
                        )
                        arbitration_decisions: dict[str, list[InspectionDecision]] = {}
                    else:
                        arbitration_timestamp = datetime.now(UTC)
                        arbitration_decisions = {}
                        unexpected_ids: list[str] = []
                        for decision in arbitration.decisions:
                            specialist_audit.opinions.append(
                                SpecialistOpinion(
                                    reviewer=AgentRole.EVIDENCE_CRITIC.value,
                                    model=self.config.terra_model,
                                    timestamp=arbitration_timestamp,
                                    decision=decision,
                                    confidence=decision.confidence,
                                    reasoning=decision.reason,
                                )
                            )
                            if decision.region_id not in conflicting_ids:
                                unexpected_ids.append(decision.region_id)
                            else:
                                arbitration_decisions.setdefault(
                                    decision.region_id, []
                                ).append(decision)
                        if unexpected_ids:
                            arbitration_reason = (
                                "Arbitration returned a different region ID: "
                                + ", ".join(unexpected_ids)
                            )

                    for region_id in conflicting_ids:
                        candidates = arbitration_decisions.get(region_id, [])
                        issue = arbitration_reason
                        if issue is None and len(candidates) != 1:
                            issue = (
                                "Arbitration did not return exactly one decision for "
                                f"{region_id}"
                            )
                        if issue is None:
                            issue = _decision_issue(
                                candidates[0],
                                region_id,
                                source="Arbitration",
                            )
                        if issue is not None:
                            resolution_failures[region_id] = issue
                            resolutions[region_id] = SpecialistResolution(
                                region_id=region_id,
                                outcome="needs_review",
                                reasoning=issue,
                            )
                            inspection_warnings.append(issue)
                        else:
                            decisions[region_id] = candidates[0]
                            resolutions[region_id] = SpecialistResolution(
                                region_id=region_id,
                                outcome="arbitrated",
                                final_decision=candidates[0],
                                reasoning=candidates[0].reason,
                            )
                else:
                    for region_id in conflicting_ids:
                        reason = "Unresolved conflicting specialist opinions"
                        resolution_failures[region_id] = reason
                        resolutions[region_id] = SpecialistResolution(
                            region_id=region_id,
                            outcome="needs_review",
                            reasoning=reason,
                        )
                        inspection_warnings.append(reason)

                addition_clusters = _cluster_addition_opinions(addition_opinions)
                addition_conflicts: dict[
                    str, list[SpecialistAdditionOpinion]
                ] = {}
                addition_resolutions: dict[str, SpecialistAdditionResolution] = {}
                addition_cluster_order: list[str] = []
                for opinions in addition_clusters:
                    proposal_region_ids = list(
                        dict.fromkeys(
                            opinion.addition.region_id for opinion in opinions
                        )
                    )
                    region_id = proposal_region_ids[0]
                    addition_cluster_order.append(region_id)
                    issue = next(
                        (
                            issue
                            for opinion in opinions
                            if (issue := _addition_issue(opinion.addition))
                        ),
                        None,
                    )
                    canonical = {
                        _canonical_addition(opinion.addition) for opinion in opinions
                    }
                    if issue is not None:
                        addition_resolutions[region_id] = SpecialistAdditionResolution(
                            region_id=region_id,
                            outcome="needs_review",
                            proposal_region_ids=proposal_region_ids,
                            reasoning=issue,
                        )
                        inspection_warnings.append(issue)
                    elif len(canonical) == 1:
                        final_addition = opinions[0].addition
                        additions.append(final_addition)
                        addition_resolutions[region_id] = SpecialistAdditionResolution(
                            region_id=region_id,
                            outcome="consensus" if len(opinions) > 1 else "single",
                            proposal_region_ids=proposal_region_ids,
                            final_addition=final_addition,
                            reasoning=(
                                "Specialists supplied an identical additional region"
                                if len(opinions) > 1
                                else "Single specialist addition proposal"
                            ),
                        )
                    else:
                        addition_conflicts[region_id] = opinions

                if addition_conflicts and manager_flow:
                    arbitration_reason: str | None = None
                    addition_conflict_payloads = [
                        {
                            "cluster_id": region_id,
                            "proposals": [
                                opinion.addition.model_dump(mode="json")
                                for opinion in opinions
                            ],
                        }
                        for region_id, opinions in addition_conflicts.items()
                    ]
                    try:
                        addition_arbitration = gateway.inspect_page(
                            page,
                            draft,
                            region_ids=all_region_ids,
                            target_region_ids=list(addition_conflicts),
                            agent_role=AgentRole.EVIDENCE_CRITIC,
                            use_terra=True,
                            addition_conflicts=addition_conflict_payloads,
                        )
                    except Exception as exc:  # noqa: BLE001 - arbitration fails closed
                        arbitration_reason = (
                            f"Addition arbitration failed: {type(exc).__name__}: {exc}"
                        )
                        arbitration_additions = {}
                    else:
                        arbitration_additions: dict[
                            str, list[InspectionRegionAddition]
                        ] = {}
                        arbitration_timestamp = datetime.now(UTC)
                        unexpected_ids: list[str] = []
                        for addition in addition_arbitration.additional_regions:
                            specialist_audit.addition_opinions.append(
                                SpecialistAdditionOpinion(
                                    reviewer=AgentRole.EVIDENCE_CRITIC.value,
                                    model=self.config.terra_model,
                                    timestamp=arbitration_timestamp,
                                    addition=addition,
                                )
                            )
                            if addition.region_id not in addition_conflicts:
                                unexpected_ids.append(addition.region_id)
                            else:
                                arbitration_additions.setdefault(
                                    addition.region_id, []
                                ).append(addition)
                        if unexpected_ids:
                            arbitration_reason = (
                                "Addition arbitration returned a different region ID: "
                                + ", ".join(unexpected_ids)
                            )

                    for region_id, opinions in addition_conflicts.items():
                        proposal_region_ids = list(
                            dict.fromkeys(
                                opinion.addition.region_id for opinion in opinions
                            )
                        )
                        candidates = arbitration_additions.get(region_id, [])
                        issue = arbitration_reason
                        if issue is None and len(candidates) != 1:
                            issue = (
                                "Addition arbitration did not return exactly one proposal for "
                                f"{region_id}"
                            )
                        if issue is None:
                            issue = _addition_issue(
                                candidates[0],
                                region_id,
                                source="Addition arbitration",
                            )
                        if issue is None and _canonical_addition(
                            candidates[0]
                        ) not in {
                            _canonical_addition(opinion.addition)
                            for opinion in opinions
                        }:
                            issue = (
                                "Addition arbitration returned a region payload outside "
                                f"the competing proposals for {region_id}"
                            )
                        if issue is not None:
                            addition_resolutions[region_id] = (
                                SpecialistAdditionResolution(
                                    region_id=region_id,
                                    outcome="needs_review",
                                    proposal_region_ids=proposal_region_ids,
                                    reasoning=issue,
                                )
                            )
                            inspection_warnings.append(issue)
                        else:
                            additions.append(candidates[0])
                            addition_resolutions[region_id] = (
                                SpecialistAdditionResolution(
                                    region_id=region_id,
                                    outcome="arbitrated",
                                    proposal_region_ids=proposal_region_ids,
                                    final_addition=candidates[0],
                                    reasoning=candidates[0].reason,
                                )
                            )
                else:
                    for region_id, opinions in addition_conflicts.items():
                        reason = "Unresolved conflicting additional-region proposals"
                        addition_resolutions[region_id] = SpecialistAdditionResolution(
                            region_id=region_id,
                            outcome="needs_review",
                            proposal_region_ids=list(
                                dict.fromkeys(
                                    opinion.addition.region_id for opinion in opinions
                                )
                            ),
                            reasoning=reason,
                        )
                        inspection_warnings.append(reason)

                specialist_audit.addition_resolutions = [
                    addition_resolutions[region_id]
                    for region_id in addition_cluster_order
                    if region_id in addition_resolutions
                ]

                specialist_audit.resolutions = [
                    resolutions[region_id]
                    for region_id in risky_ids
                    if region_id in resolutions
                ]
                ordering_values = {
                    tuple(opinion.ordered_region_ids)
                    for opinion in specialist_audit.ordering_opinions
                }
                if len(ordering_values) == 1:
                    ordered_region_ids = list(next(iter(ordering_values)))
                    specialist_audit.ordering_resolution = (
                        SpecialistOrderingResolution(
                            outcome=(
                                "consensus"
                                if len(specialist_audit.ordering_opinions) > 1
                                else "single"
                            ),
                            ordered_region_ids=ordered_region_ids,
                            reasoning="Specialists supplied the same complete order",
                        )
                    )
                elif len(ordering_values) > 1:
                    ordering_conflict = True
                    warning = "ignored conflicting ordered_region_ids"
                    inspection_warnings.append(warning)
                    specialist_audit.ordering_resolution = (
                        SpecialistOrderingResolution(
                            outcome="needs_review",
                            reasoning=warning,
                        )
                    )
                inspection = PageInspection(
                    decisions=list(decisions.values()),
                    additional_regions=additions,
                    ordered_region_ids=ordered_region_ids,
                    warnings=inspection_warnings,
                )
                warnings.extend(
                    f"Page {page.number}: {item}" for item in inspection_warnings
                )

        explicit_crop_ids: set[str] = set()
        candidate_pairs = [
            (region, block)
            for region, block in zip(draft.regions, blocks, strict=True)
            if block.id in decisions or any(block.id == risky_block.id for _, risky_block in risky)
        ]
        for _region, block in candidate_pairs:
            decision = decisions.get(block.id)
            if decision is None:
                block.verification = VerificationState.NEEDS_REVIEW
                block.verification_reason = block.verification_reason or resolution_failures.get(
                    block.id, "No verification decision"
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

        addition_ids: dict[str, str] = {}
        if inspection is not None:
            for addition in inspection.additional_regions:
                if _bbox(addition.region.bbox) is None:
                    warnings.append(
                        f"Page {page.number}: skipped added region "
                        f"{addition.region_id} with invalid bounding box"
                    )
                    continue
                matches = _matching_addition_blocks(addition.region, blocks)
                active_matches = [
                    block
                    for block in matches
                    if block.verification is not VerificationState.REJECTED
                ]
                if active_matches:
                    warnings.append(
                        f"Page {page.number}: skipped duplicate added region "
                        f"{addition.region_id}"
                    )
                    continue
                rejected_matches = [
                    block
                    for block in matches
                    if block.verification is VerificationState.REJECTED
                ]
                reason = addition.reason or "Added by page coverage inspection"
                if len(rejected_matches) == 1:
                    predecessor = rejected_matches[0]
                    previous_state = predecessor.verification
                    _apply_correction(predecessor, addition.region, page.number)
                    predecessor.verification = VerificationState.VERIFIED
                    predecessor.verification_reason = reason
                    predecessor.correction_lineage.append(
                        CorrectionLineage(
                            original_id=predecessor.id,
                            replacement_id=predecessor.id,
                            provider_id=addition.region_id,
                            reason=reason,
                            previous_state=previous_state,
                            final_state=predecessor.verification,
                        )
                    )
                    addition_ids[addition.region_id] = predecessor.id
                    continue
                added = _block(addition.region, page.number, len(blocks))
                if rejected_matches:
                    added.verification = VerificationState.NEEDS_REVIEW
                    predecessor_ids = ", ".join(block.id for block in rejected_matches)
                    added.verification_reason = (
                        f"{reason}; ambiguous rejected predecessor matches: "
                        f"{predecessor_ids}"
                    )
                    added.correction_lineage.extend(
                        CorrectionLineage(
                            original_id=predecessor.id,
                            replacement_id=added.id,
                            provider_id=addition.region_id,
                            reason=reason,
                            previous_state=predecessor.verification,
                            final_state=added.verification,
                        )
                        for predecessor in rejected_matches
                    )
                    warnings.append(
                        f"Page {page.number}: added region {addition.region_id} "
                        f"matched multiple rejected predecessors: {predecessor_ids}"
                    )
                else:
                    added.verification = VerificationState.VERIFIED
                    added.verification_reason = reason
                blocks.append(added)
                addition_ids[addition.region_id] = added.id

            if inspection.ordered_region_ids:
                expected = all_region_ids + list(addition_ids)
                supplied = inspection.ordered_region_ids
                valid_order = (
                    len(supplied) == len(expected)
                    and set(supplied) == set(expected)
                )
                if not valid_order:
                    warnings.append(
                        f"Page {page.number}: ignored invalid ordered_region_ids"
                    )
                    if specialist_audit.ordering_resolution is not None:
                        specialist_audit.ordering_resolution = (
                            SpecialistOrderingResolution(
                                outcome="needs_review",
                                reasoning="ignored invalid ordered_region_ids",
                            )
                        )
                elif _has_excessive_order_movement(supplied, all_region_ids):
                    warnings.append(
                        f"Page {page.number}: ignored ordered_region_ids "
                        "with excessive block movement"
                    )
                    if specialist_audit.ordering_resolution is not None:
                        specialist_audit.ordering_resolution = (
                            SpecialistOrderingResolution(
                                outcome="needs_review",
                                reasoning=(
                                    "ignored ordered_region_ids with excessive block movement"
                                ),
                            )
                        )
                else:
                    by_id = {block.id: block for block in blocks}
                    for order, provider_id in enumerate(supplied):
                        block_id = addition_ids.get(provider_id, provider_id)
                        by_id[block_id].reading_order = order

        nonvisual_candidates: dict[str, tuple[int, Block]] = {
            block.id: (0, block)
            for block in blocks
            if block.id in explicit_crop_ids
            and block.type not in VISUAL_REGION_TYPES
        }
        for block in blocks:
            if block.verification is VerificationState.REJECTED or block.bbox is None:
                continue
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
            key=lambda item: (item[0], item[1].confidence),
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
            if block.bbox is not None:
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
                crop_requests.append(CropInspectionRequest(
                    crop_path=str(crop_path),
                    region_id=block.id,
                    candidate_region=_region_from_block(block),
                    evidence_ref=f"page:{page.number}:{block.id}",
                ))
                crop_blocks.append(block)
        for batch_start in range(0, len(crop_requests), MAX_CROPS_PER_PAGE):
            batch_requests = crop_requests[
                batch_start : batch_start + MAX_CROPS_PER_PAGE
            ]
            batch_blocks = crop_blocks[
                batch_start : batch_start + MAX_CROPS_PER_PAGE
            ]
            try:
                crop_inspection = gateway.inspect_crops(batch_requests)
            except Exception as exc:  # noqa: BLE001 - verification is best-effort
                reason = f"Crop verification failed: {type(exc).__name__}: {exc}"
                for block in batch_blocks:
                    block.verification = VerificationState.NEEDS_REVIEW
                    block.verification_reason = reason
            else:
                crop_decisions = {
                    item.region_id: item for item in crop_inspection.decisions
                }
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

        quality_inspector = getattr(gateway, "inspect_quality_crops", None)
        if callable(quality_inspector):
            recovery_blocks: list[Block] = []
            native_recovery_blocks: list[Block] = []
            scan_probe_blocks: list[Block] = []
            for region in find_missing_source_regions(page, blocks):
                recovered = _block(region, page.number, len(blocks))
                recovered.verification = VerificationState.NEEDS_REVIEW
                if page.scanned and not region.text:
                    recovered.verification_reason = (
                        "Scan omission probe awaiting high-resolution quality inspection"
                    )
                    scan_probe_blocks.append(recovered)
                else:
                    recovered.verification_reason = "Native source recovery awaiting quality inspection"
                    native_recovery_blocks.append(recovered)
                blocks.append(recovered)
                recovery_blocks.append(recovered)

            scan_probe_ids = {block.id for block in scan_probe_blocks}
            grounded_corrections: list[Block] = []

            selected: list[Block] = []
            selected_ids: set[str] = set()
            for block in recovery_blocks + select_repair_blocks(page, blocks, warnings):
                if block.id not in selected_ids:
                    selected.append(block)
                    selected_ids.add(block.id)

            quality_requests: list[CropInspectionRequest] = []
            quality_blocks: list[Block] = []
            original_verification = {
                block.id: block.verification for block in selected
            }
            original_reasons = {
                block.id: block.verification_reason for block in selected
            }
            for block in selected:
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
                        block.verification_reason = (
                            f"Quality crop rendering failed: {type(exc).__name__}: {exc}"
                        )
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
                    )
                )
                quality_blocks.append(block)

            if quality_requests:
                pending = list(zip(quality_requests, quality_blocks, strict=True))
                rejection_counts: dict[str, int] = {}
                geometry_rejection_counts: dict[str, int] = {}
                for repair_round in range(1, 3):
                    next_pending: list[tuple[CropInspectionRequest, Block]] = []
                    for batch_start in range(0, len(pending), MAX_REPAIR_BLOCKS):
                        batch = pending[batch_start : batch_start + MAX_REPAIR_BLOCKS]
                        batch_requests = [request for request, _block_item in batch]
                        try:
                            quality_inspection = quality_inspector(
                                batch_requests,
                                page_number=page.number,
                            )
                        except Exception as exc:  # noqa: BLE001 - review failure is auditable
                            fallback_reason = (
                                f"Quality verification failed: {type(exc).__name__}: {exc}"
                            )
                            quality_decisions = {}
                        else:
                            fallback_reason = "No conclusive quality verification decision"
                            quality_decisions = {
                                item.region_id: item
                                for item in quality_inspection.decisions
                            }
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
                            if decision is not None and decision.action is InspectionAction.REJECT:
                                rejection_counts[block.id] = (
                                    rejection_counts.get(block.id, 0) + 1
                                )
                                if decision.geometry_only:
                                    geometry_rejection_counts[block.id] = (
                                        geometry_rejection_counts.get(block.id, 0) + 1
                                    )
                            if repair_round == 1:
                                block.verification = VerificationState.NEEDS_REVIEW
                                block.verification_reason = reason
                                next_pending.append((request, block))
                                continue

                            if rejection_counts.get(block.id, 0) == 2:
                                if geometry_rejection_counts.get(block.id, 0) == 2:
                                    block.verification = VerificationState.NEEDS_REVIEW
                                    block.verification_reason = (
                                        "Geometry remained unresolved after two quality "
                                        f"repair rounds: {reason}"
                                    )
                                else:
                                    _apply_decision(
                                        block,
                                        decision,
                                        page.number,
                                        preserve_layout=True,
                                    )
                            elif original_verification[block.id] is VerificationState.REJECTED:
                                block.verification = VerificationState.REJECTED
                                block.verification_reason = original_reasons[block.id]
                            else:
                                block.verification = VerificationState.NEEDS_REVIEW
                                block.verification_reason = (
                                    f"Scan omission probe unresolved: {reason}"
                                    if block.id in scan_probe_ids
                                    else reason
                                )
                            warnings.append(
                                f"Page {page.number}: quality gate unresolved block {block.id}"
                            )
                    pending = next_pending
                    if not pending:
                        break

            if native_recovery_blocks:
                warnings.append(
                    f"Page {page.number}: queued {len(native_recovery_blocks)} native "
                    "source recovery regions for high-resolution quality review"
                )
            if scan_probe_blocks:
                warnings.append(
                    f"Page {page.number}: created {len(scan_probe_blocks)} scan omission probes"
                )
            if grounded_corrections:
                warnings.append(
                    f"Page {page.number}: recovered {len(grounded_corrections)} "
                    "grounded quality corrections"
                )
        elif page.scanned:
            for region in find_missing_source_regions(page, blocks):
                if region.text:
                    continue
                probe = _block(region, page.number, len(blocks))
                probe.verification = VerificationState.NEEDS_REVIEW
                probe.verification_reason = "Scan omission probe was not inspected"
                blocks.append(probe)
                warnings.append(
                    f"Page {page.number}: quality gate unresolved block {probe.id}; "
                    "high-resolution inspection unavailable"
                )

        if ordering_conflict:
            for block in blocks:
                if block.verification is VerificationState.REJECTED:
                    continue
                block.verification = VerificationState.NEEDS_REVIEW
                block.verification_reason = "Conflicting specialist reading-order opinions"

        blocks, normalization_warnings = normalize_page_blocks(blocks)
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
                specialist_audit=specialist_audit,
                warnings=warnings,
            ),
            warnings=warnings,
            usage=usage,
            trace=list(getattr(gateway, "trace", [])),
        )

    def parse(
        self,
        data: bytes,
        filename: str,
        progress_callback: ProgressCallback | None = None,
    ) -> ParseResult:
        started = time.perf_counter()
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
            pages: list[Page] = []
            warnings: list[str] = []
            sections: list[str] = []
            usage = RunUsage()
            trace: list[AgentTraceEvent] = []
            total = len(source.pages)
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

            with ThreadPoolExecutor(
                max_workers=min(self.config.max_page_concurrency, total),
                thread_name_prefix="docparse-page",
            ) as executor:
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
                    futures = {
                        executor.submit(
                            self._process_page,
                            source,
                            page,
                            workdir,
                            total,
                            queue_progress if progress_callback is not None else None,
                        ): page.number
                        for page in batch
                    }
                    pending = set(futures)
                    processed: list[_ProcessedPage] = []
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
                                specialist_audit=result.page.specialist_audit,
                                warnings=result.page.warnings,
                                quality=result.page.quality,
                            )
                        )
                        warnings.extend(result.warnings)
                        usage.calls.extend(result.usage.calls)
                        trace.extend(result.trace)

            document = Document(
                source_name=source.name,
                source_sha256=source.sha256,
                pages=pages,
                warnings=warnings,
            )
            materialize_document_quality(document)
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            rendered = render_agentic_document(
                document,
                usage=usage,
                trace=trace,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            return ParseResult(
                document=document,
                markdown=rendered.markdown,
                json=rendered.json,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                annotated_pdf=render_annotated_pdf(data, source.name, document),
                legacy_json=render_json(document),
                usage=usage,
                trace=trace,
            )
