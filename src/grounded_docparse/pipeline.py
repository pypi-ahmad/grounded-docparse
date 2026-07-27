from __future__ import annotations

import re
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from queue import Empty, SimpleQueue

from .config import ParserConfig
from .gateways import OpenAIDocumentGateway
from .ingest import IngestedDocument, PageEvidence, ingest_document, render_region_crop
from .models import (
    AgentTraceEvent,
    AgentUsage,
    AtomicDraft,
    AtomicEvidence,
    Block,
    BoundingBox,
    Citation,
    CropInspectionRequest,
    Document,
    DraftBoundingBox,
    FormData,
    InspectionAction,
    InspectionDecision,
    NodeType,
    Page,
    PageInspection,
    ParseResult,
    ProgressCallback,
    ProgressEvent,
    RegionDraft,
    RunUsage,
    TableCell,
    TableCellDraft,
    TableData,
    VerificationState,
)
from .render import render_agentic_document, render_annotated_pdf, render_json

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
REPEATED_LABEL_PATTERN = re.compile(
    r"^(?P<label>[^\n–—]{1,80}?)(?P<separator>\s+[–—-]\s+)(?P=label)(?P=separator)"
)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.translate({ord("\u00ad"): None, ord("\u200b"): None, ord("\ufeff"): None})


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


def _table(region: RegionDraft) -> TableData | None:
    if region.type is not NodeType.TABLE:
        return None
    return TableData(
        cells=[
            TableCell(
                row=cell.row_index,
                column=cell.column_index,
                text=_clean_text(cell.text) or "",
                row_span=cell.row_span,
                column_span=cell.column_span,
                header=cell.header,
                bbox=_bbox(cell.bbox),
            )
            for cell in region.table_cells
        ]
    )


def _atoms(region: RegionDraft) -> list[AtomicEvidence]:
    return [
        AtomicEvidence(
            kind=atom.kind,
            text=_clean_text(atom.text) or "",
            bbox=_bbox(atom.bbox),
        )
        for atom in region.atoms
    ]


def _block(region: RegionDraft, page_number: int, index: int) -> Block:
    block_id = f"p{page_number}-b{index + 1}"
    bbox = _bbox(region.bbox)
    block = Block(
        id=block_id,
        type=region.type,
        text=_clean_text(region.text) or "",
        bbox=bbox,
        reading_order=region.reading_order,
        confidence=region.confidence,
        citation=Citation(page=page_number, bbox=bbox),
        heading_level=region.heading_level,
        list_marker=region.list_marker,
        table=_table(region),
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
        atoms=_atoms(region),
    )
    if region.bbox is not None and bbox is None:
        block.verification = VerificationState.NEEDS_REVIEW
        block.verification_reason = "Invalid bounding box"
    return block


def _needs_verification(region: RegionDraft) -> bool:
    return (
        region.confidence < VERIFICATION_CONFIDENCE_THRESHOLD
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
    block.confidence = region.confidence
    if not preserve_layout:
        block.citation = Citation(page=page_number, bbox=bbox)
    block.heading_level = region.heading_level
    block.list_marker = region.list_marker
    block.table = _table(region)
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
    block.atoms = _atoms(region)
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
            )
            for atom in block.atoms
        ],
    )


def _visible_region_text(region: RegionDraft) -> str:
    values = [region.text, region.caption or "", region.figure_description or ""]
    if region.form is not None:
        values.extend(
            [region.form.label, region.form.value or "", region.form.hint or ""]
        )
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


def _is_duplicate_addition(region: RegionDraft, blocks: list[Block]) -> bool:
    text = _visible_region_text(region)
    bbox = _bbox(region.bbox)
    for block in blocks:
        existing = _visible_region_text(_region_from_block(block))
        if text and text == existing:
            return True
        if (
            bbox is not None
            and block.bbox is not None
            and block.type is region.type
            and _box_overlap(bbox, block.bbox) >= 0.8
        ):
            return True
    return False


def _clean_repeated_content(blocks: list[Block]) -> None:
    ordered = sorted(blocks, key=lambda item: item.reading_order)
    for block in ordered:
        block.text = "\n".join(
            REPEATED_LABEL_PATTERN.sub(
                lambda match: f"{match.group('label')}{match.group('separator')}",
                line,
            )
            for line in block.text.splitlines()
        )
    for previous, current in pairwise(ordered):
        if previous.type is not NodeType.HEADING or not current.text:
            continue
        lines = current.text.splitlines()
        if not lines:
            continue
        heading = previous.text.strip().removesuffix(":").casefold()
        first_line = lines[0].strip().removesuffix(":").casefold()
        if heading and heading == first_line:
            current.text = "\n".join(lines[1:]).lstrip()


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
            if _needs_verification(region)
        ]
        decisions: dict[str, InspectionDecision] = {}
        inspection = None
        if risky:
            _emit(progress_callback, "verify", page.number, total, f"Verifying page {page.number}")
            risky_ids = [block.id for _region, block in risky]
            inspections: list[PageInspection] = []
            if callable(getattr(gateway, "plan_page", None)):
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
                            inspections.append(delegated_inspection)
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
                    inspections.append(
                        gateway.inspect_page(
                            page,
                            draft,
                            region_ids=all_region_ids,
                            target_region_ids=risky_ids,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - verification is best-effort
                    reason = f"Verification failed: {type(exc).__name__}: {exc}"
                    for _region, block in risky:
                        block.verification = VerificationState.NEEDS_REVIEW
                        block.verification_reason = block.verification_reason or reason

            if inspections:
                merged_decisions: dict[str, InspectionDecision] = {}
                additions = []
                ordered_region_ids: list[str] = []
                inspection_warnings: list[str] = []
                for item in inspections:
                    merged_decisions.update(
                        (decision.region_id, decision) for decision in item.decisions
                    )
                    additions.extend(item.additional_regions)
                    if item.ordered_region_ids:
                        ordered_region_ids = item.ordered_region_ids
                    inspection_warnings.extend(item.warnings)
                inspection = PageInspection(
                    decisions=list(merged_decisions.values()),
                    additional_regions=additions,
                    ordered_region_ids=ordered_region_ids,
                    warnings=inspection_warnings,
                )
                decisions = merged_decisions
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
                block.verification_reason = block.verification_reason or "No verification decision"
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
                if _is_duplicate_addition(addition.region, blocks):
                    warnings.append(
                        f"Page {page.number}: skipped duplicate added region "
                        f"{addition.region_id}"
                    )
                    continue
                added = _block(addition.region, page.number, len(blocks))
                added.verification = VerificationState.VERIFIED
                added.verification_reason = addition.reason or "Added by page coverage inspection"
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
                elif _has_excessive_order_movement(supplied, all_region_ids):
                    warnings.append(
                        f"Page {page.number}: ignored ordered_region_ids "
                        "with excessive block movement"
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

        _clean_repeated_content(blocks)
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
