from __future__ import annotations

import html
import io
import json
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import nh3
import pymupdf
from PIL import Image, ImageOps, ImageSequence

from .models import (
    AgenticAnalysis,
    AgentTraceEvent,
    Block,
    Document,
    Element,
    ExtractionResult,
    FormClassificationResult,
    NodeType,
    PageQuality,
    ParseMetadata,
    ParseResult,
    RoutedExtractionResult,
    RuntimeDiagnostics,
    RunUsage,
    VerificationState,
    VisualRecoveryResult,
)
from .quality import WORD_PATTERN, incomplete_table, semantic_text

ANNOTATION_COLORS = {
    "text": (0.376, 0.647, 0.98),
    "heading": (0.114, 0.306, 0.847),
    "table": (0.086, 0.639, 0.29),
    "figure": (0.976, 0.451, 0.086),
    "formula": (0.576, 0.2, 0.918),
    "seal": (0.863, 0.149, 0.149),
}
RECOVERY_ANNOTATION_COLOR = (1.0, 0.55, 0.0)

SEMANTIC_COVERAGE_THRESHOLD = 1.0
_MARKDOWN_TABLE_PATTERN = re.compile(
    r"<table\b[^>]*>.*?</table\s*>", re.IGNORECASE | re.DOTALL
)
_RAW_HTML_PATTERN = re.compile(
    r"<!--.*?-->|</?[A-Za-z][^>]*>", re.IGNORECASE | re.DOTALL
)
_PREVIEW_TABLE_TAGS = {
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    "br",
}
_PREVIEW_TABLE_ATTRIBUTES = {
    "table": {"border"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
    "col": {"span"},
}
_PREVIEW_REMOVE_CONTENT_TAGS = {"script", "style", "iframe", "object", "svg", "math"}


def _checkbox_marker(block: Block) -> str:
    return {"checked": "[x]", "unchecked": "[ ]"}.get(str(block.checkbox_state), "[?]")


def _has_equivalent_leading_marker(text: str, marker: str) -> bool:
    return bool(
        re.match(rf"^{re.escape(marker)}(?=\s|$)", text.lstrip(), re.IGNORECASE)
    )


def _line_key(value: str) -> str:
    parts = [" ".join(part.split()) for part in value.strip(" |").split("|")]
    return "|".join(parts)


def _table_structure_lines(block: Block) -> Counter[str]:
    if block.table is None:
        return Counter()
    cell_lines: Counter[str] = Counter()
    flattened_cells: Counter[str] = Counter()
    row_lines: Counter[str] = Counter()
    rows: dict[int, list] = {}
    for cell in block.table.cells:
        rows.setdefault(cell.row, []).append(cell)
        source_lines = [line for line in cell.text.splitlines() if line.strip()]
        cell_lines.update(_line_key(line) for line in source_lines)
        if len(source_lines) > 1:
            flattened_cells[_line_key(" ".join(source_lines))] += 1
    for cells in rows.values():
        ordered = sorted(cells, key=lambda item: item.column)
        row_text = " | ".join(
            " ".join(cell.text.replace("\r", " ").splitlines()) for cell in ordered
        )
        row_lines[_line_key(row_text)] += 1
    return cell_lines | flattened_cells | row_lines


def _table_residual_lines(block: Block) -> list[str]:
    represented = _table_structure_lines(block)
    residuals: list[str] = []
    for line in block.text.splitlines():
        key = _line_key(line)
        if represented[key]:
            represented[key] -= 1
        elif line.strip():
            residuals.append(line.strip())
    return residuals


def _form_structure_lines(block: Block) -> Counter[str]:
    if block.form is None:
        return Counter()
    fields = [
        block.form.label,
        block.form.value or "",
        block.form.hint or "",
    ]
    individual: Counter[str] = Counter(
        _line_key(line)
        for field in fields
        for line in field.splitlines()
        if line.strip()
    )
    combined: Counter[str] = Counter()
    label = block.form.label.rstrip().removesuffix(":")
    combined[_line_key(f"{label}:")] += 1
    if block.form.value:
        combined[_line_key(f"{block.form.label} {block.form.value}")] += 1
        combined[_line_key(f"{label}: {block.form.value}")] += 1
    if block.form.hint:
        combined[_line_key(f"{block.form.label} {block.form.hint}")] += 1
        combined[_line_key(f"{label}: {block.form.hint}")] += 1
    if block.form.value and block.form.hint:
        combined[
            _line_key(f"{block.form.label} {block.form.value} ({block.form.hint})")
        ] += 1
        combined[_line_key(f"{label}: {block.form.value} ({block.form.hint})")] += 1
    return individual | combined


def _form_residual_lines(block: Block) -> list[str]:
    represented = _form_structure_lines(block)
    residuals: list[str] = []
    for line in block.text.splitlines():
        key = _line_key(line)
        if represented[key]:
            represented[key] -= 1
        elif line.strip():
            residuals.append(line.strip())
    return residuals


def _table(block: Block) -> str:
    if re.match(r"\s*<table\b", block.text, re.IGNORECASE):
        return block.text
    if block.table is None or not block.table.cells:
        return block.text
    rows: dict[int, list] = {}
    for cell in block.table.cells:
        rows.setdefault(cell.row, []).append(cell)
    lines: list[str] = []
    for row_index in sorted(rows):
        cells = sorted(rows[row_index], key=lambda item: item.column)
        values = [
            cell.text.replace("\r", " ").replace("\n", " ").replace("|", r"\|")
            for cell in cells
        ]
        lines.append("| " + " | ".join(values) + " |")
        if row_index == min(rows):
            lines.append("| " + " | ".join("---" for _ in cells) + " |")
    residuals = _table_residual_lines(block)
    if residuals:
        lines.extend(["", *residuals])
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _VisualSegment:
    kind: str
    raw_text: str
    rendered_text: str
    bbox: object
    origin: str
    provider: bool = False
    evidence: object | None = None


def _visual_segments(block: Block) -> list[_VisualSegment]:
    values: list[tuple[str, str]] = []
    if block.text:
        values.append(("text", block.text))
    if block.caption:
        values.append(("caption", block.caption))
    if block.figure_description:
        values.append(("description", block.figure_description))

    segments: list[_VisualSegment] = []
    seen: set[tuple] = set()
    multiple = len(values) > 1
    for kind, value in values:
        segment_kind = {
            "text": "visual_text",
            "caption": "caption",
            "description": "visual_description",
        }[kind]
        origin = "generated_description" if kind == "description" else "literal"
        key = (segment_kind, value, origin, _bbox_key(block.bbox))
        if key in seen:
            continue
        seen.add(key)
        if multiple and kind != "text":
            rendered = f"{kind.title()}: {value}"
        else:
            rendered = value
        segments.append(
            _VisualSegment(
                kind=segment_kind,
                raw_text=value,
                rendered_text=rendered,
                bbox=block.bbox,
                origin=origin,
            )
        )
    for atom in block.atoms:
        bbox = atom.bbox or block.bbox
        key = (atom.kind, atom.text, "literal", _bbox_key(bbox))
        if atom.text and key not in seen:
            seen.add(key)
            label = atom.kind.replace("_", " ").title()
            segments.append(
                _VisualSegment(
                    kind=atom.kind,
                    raw_text=atom.text,
                    rendered_text=f"{label}: {atom.text}",
                    bbox=bbox,
                    origin="literal",
                    provider=True,
                    evidence=atom,
                )
            )
    if block.chart_type:
        segments.append(
            _VisualSegment(
                kind="chart_type",
                raw_text=block.chart_type,
                rendered_text=f"Chart type: {block.chart_type}",
                bbox=block.bbox,
                origin="literal",
            )
        )
    for point in block.chart_data:
        prefix = f"{point.series} — " if point.series else ""
        rendered = f"{prefix}{point.label}: {point.value}"
        segments.append(
            _VisualSegment(
                kind="chart_point",
                raw_text=rendered,
                rendered_text=rendered,
                bbox=block.bbox,
                origin="literal",
            )
        )
    return segments


def _visual(block: Block) -> str:
    segments = _visual_segments(block)
    content = "\n\n".join(segment.rendered_text for segment in segments)
    return f"<figure>{content}</figure>" if segments else ""


def _bbox_key(bbox) -> tuple | None:
    if bbox is None:
        return None
    return (bbox.x0, bbox.y0, bbox.x1, bbox.y1, bbox.unit)


def _body(block: Block) -> str:
    if block.verification is VerificationState.REJECTED:
        return ""
    text = block.text
    if block.type is NodeType.HEADING:
        return f"{'#' * (block.heading_level or 1)} {text}"
    if block.type is NodeType.TABLE:
        return _table(block)
    if block.type is NodeType.CHECKBOX:
        return f"{_checkbox_marker(block)} {_checkbox_text(block)}"
    if block.type is NodeType.LIST_ITEM:
        marker = block.list_marker or "-"
        return (
            text if _has_equivalent_leading_marker(text, marker) else f"{marker} {text}"
        )
    if block.type is NodeType.FORM_FIELD and block.form is not None:
        label = block.form.label.rstrip().removesuffix(":")
        value = block.form.value
        hint = block.form.hint
        if value is not None and hint is not None:
            body = f"**{label}:** {value} ({hint})"
        elif value is not None:
            body = f"**{label}:** {value}"
        elif hint is not None:
            body = f"**{label}:** {hint}"
        else:
            body = f"**{label}:**"
        residuals = _form_residual_lines(block)
        return "\n".join([body, *residuals])
    if block.type in {NodeType.HEADER, NodeType.FOOTER}:
        return text
    if block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        return _visual(block)
    return text


@dataclass(frozen=True, slots=True)
class _Emission:
    start: int
    end: int
    body: str
    coverage_body: str | None = None
    checkbox_group_span: tuple[int, int] | None = None


class _MarkdownBuilder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.emissions: dict[str, _Emission] = {}

    def append_raw(self, value: str) -> None:
        self.parts.append(value)
        self.length += len(value)

    def append_body(self, body: str, blocks: list[Block]) -> None:
        if not body:
            return
        start = self.length
        self.append_raw(body)
        end = self.length
        for block in blocks:
            self.emissions[block.id] = _Emission(start=start, end=end, body=body)
        self.append_raw("\n\n")

    def append_checkbox_group(self, group: str, members: list[Block]) -> None:
        prefix = f"**{group}:** "
        options = [
            f"{_checkbox_marker(item)} {_checkbox_text(item)}" for item in members
        ]
        start = self.length
        self.append_raw(prefix + " ".join(options))
        group_span = (start + len("**"), start + len("**") + len(group))
        cursor = start + len(prefix)
        for member, option in zip(members, options, strict=True):
            end = cursor + len(option)
            self.emissions[member.id] = _Emission(
                start=cursor,
                end=end,
                body=option,
                coverage_body=prefix + option,
                checkbox_group_span=group_span,
            )
            cursor = end + 1
        self.append_raw("\n\n")

    def finish(self) -> str:
        value = "".join(self.parts)
        if value.endswith("\n\n"):
            return value[:-1]
        return value if value.endswith("\n") else value + "\n"


def _checkbox_text(block: Block) -> str:
    option = block.checkbox_option or block.text
    if block.checkbox_option and block.text and block.checkbox_option != block.text:
        return f"{block.checkbox_option}: {block.text}"
    return option


def _render_block(block: Block, builder: _MarkdownBuilder) -> None:
    builder.append_body(_body(block), [block])
    _render_blocks(block.children, builder)


def _render_blocks(blocks: list[Block], builder: _MarkdownBuilder) -> None:
    ordered = sorted(blocks, key=lambda item: item.reading_order)
    index = 0
    while index < len(ordered):
        block = ordered[index]
        if block.type is NodeType.CHECKBOX and block.checkbox_group:
            group = block.checkbox_group
            members: list[Block] = []
            while (
                index < len(ordered)
                and ordered[index].type is NodeType.CHECKBOX
                and ordered[index].checkbox_group == group
            ):
                if ordered[index].verification is not VerificationState.REJECTED:
                    members.append(ordered[index])
                index += 1
            if members:
                builder.append_checkbox_group(group, members)
            for member in members:
                _render_blocks(member.children, builder)
            continue
        _render_block(block, builder)
        index += 1


def _render_with_emissions(document: Document) -> tuple[str, dict[str, _Emission]]:
    builder = _MarkdownBuilder()
    for page_index, page in enumerate(document.pages):
        if page_index:
            builder.append_raw("<!-- PAGE BREAK -->\n\n")
        _render_blocks(page.blocks, builder)
    return builder.finish(), builder.emissions


def render_markdown(document: Document) -> str:
    markdown, _emissions = _render_with_emissions(document)
    return markdown


def sanitize_markdown_preview(markdown: str) -> str:
    """Allow safe table HTML without changing the surrounding Markdown."""

    def safe_text(value: str) -> str:
        def replace(match: re.Match[str]) -> str:
            raw = match.group(0)
            return "" if raw.startswith("<!--") else html.escape(raw, quote=False)

        return _RAW_HTML_PATTERN.sub(replace, value)

    parts: list[str] = []
    cursor = 0
    for match in _MARKDOWN_TABLE_PATTERN.finditer(markdown):
        parts.append(safe_text(markdown[cursor : match.start()]))
        parts.append(
            nh3.clean(
                match.group(0),
                tags=_PREVIEW_TABLE_TAGS,
                clean_content_tags=_PREVIEW_REMOVE_CONTENT_TAGS,
                attributes=_PREVIEW_TABLE_ATTRIBUTES,
                strip_comments=True,
            )
        )
        cursor = match.end()
    parts.append(safe_text(markdown[cursor:]))
    return "".join(parts)


@dataclass(frozen=True, slots=True)
class RenderedAgenticDocument:
    markdown: str
    json: str


def build_elements(
    document: Document,
    recovered_element_ids: set[str] | None = None,
) -> list[Element]:
    """Flatten the canonical document into the public engine-neutral contract."""

    elements: list[Element] = []
    for page in document.pages:
        for order, block in enumerate(_walk_blocks(page.blocks), start=1):
            bbox = (
                (block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1)
                if block.bbox is not None
                else None
            )
            elements.append(
                Element(
                    id=block.id,
                    type=block.type.value,
                    page=page.number,
                    bbox=bbox,
                    text=semantic_text(block),
                    reading_order=order,
                    confidence=block.confidence,
                    source=(
                        "luna-recovery"
                        if block.id in (recovered_element_ids or set())
                        else "glm-ocr"
                    ),
                )
            )
    return elements


def _semantic_fragments(block: Block) -> list[str]:
    fragments: list[str] = []
    if block.type is NodeType.TABLE and block.table is not None and block.table.cells:
        fragments.extend(
            " ".join(cell.text.replace("\r", " ").splitlines())
            for cell in block.table.cells
        )
        represented = _table_structure_lines(block)
        for line in block.text.splitlines():
            key = _line_key(line)
            if represented[key]:
                represented[key] -= 1
            elif line.strip():
                fragments.append(line.strip())
    elif block.type is NodeType.FORM_FIELD and block.form is not None:
        fragments.extend(
            [
                block.form.label.rstrip().removesuffix(":"),
                block.form.value or "",
                block.form.hint or "",
            ]
        )
        fragments.extend(_form_residual_lines(block))
    elif block.type is NodeType.CHECKBOX:
        fragments.extend(
            [
                _checkbox_marker(block),
                block.checkbox_group or "",
                block.checkbox_option or "",
                block.text,
            ]
        )
    elif block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        fragments.extend(
            [
                block.text,
                block.caption or "",
                block.figure_description or "",
                block.chart_type or "",
            ]
        )
        for point in block.chart_data:
            fragments.extend([point.series or "", point.label, point.value])
        fragments.extend(atom.text for atom in block.atoms)
    else:
        fragments.append(block.text)
        if block.type is NodeType.LIST_ITEM:
            fragments.append(block.list_marker or "-")

    return list(dict.fromkeys(fragment for fragment in fragments if fragment))


def _token_counts(value: str) -> Counter[str]:
    return Counter(WORD_PATTERN.findall(value.casefold()))


def _sum_token_counts(values) -> Counter[str]:
    total: Counter[str] = Counter()
    for value in values:
        total += _token_counts(value)
    return total


def _semantic_tokens(block: Block) -> Counter[str]:
    if block.type is NodeType.TABLE and block.table is not None:
        cells = _sum_token_counts(cell.text for cell in block.table.cells)
        return _token_counts(block.text) | cells
    if block.type is NodeType.FORM_FIELD and block.form is not None:
        structured = _sum_token_counts(
            [
                block.form.label,
                block.form.value or "",
                block.form.hint or "",
            ]
        )
        return _token_counts(block.text) | structured
    if block.type is NodeType.CHECKBOX:
        group = _token_counts(block.checkbox_group or "")
        option = block.checkbox_option or ""
        content = (
            _token_counts(block.text) | _token_counts(option)
            if block.text == option
            else _sum_token_counts([block.text, option])
        )
        return group + content + _token_counts(_checkbox_marker(block))
    if block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        expected = _sum_token_counts(
            [
                block.text,
                block.caption or "",
                block.figure_description or "",
                block.chart_type or "",
            ]
        )
        expected += _sum_token_counts(
            value
            for point in block.chart_data
            for value in (point.series or "", point.label, point.value)
        )
        seen_atoms: set[tuple] = set()
        if block.text:
            seen_atoms.add(
                ("visual_text", block.text, "literal", _bbox_key(block.bbox))
            )
        if block.caption:
            seen_atoms.add(("caption", block.caption, "literal", _bbox_key(block.bbox)))
        if block.figure_description:
            seen_atoms.add(
                (
                    "visual_description",
                    block.figure_description,
                    "generated_description",
                    _bbox_key(block.bbox),
                )
            )
        for atom in block.atoms:
            key = (atom.kind, atom.text, "literal", _bbox_key(atom.bbox or block.bbox))
            if key not in seen_atoms:
                seen_atoms.add(key)
                expected += _token_counts(atom.text)
        return expected
    expected = _token_counts(block.text)
    if block.type is NodeType.LIST_ITEM:
        marker = block.list_marker or "-"
        if not _has_equivalent_leading_marker(block.text, marker):
            expected += _token_counts(marker)
    return expected


def _incomplete_structure(block: Block) -> bool:
    if block.type is NodeType.TABLE:
        return incomplete_table(block)
    if block.type is NodeType.FORM_FIELD:
        return block.form is None or not block.form.label.strip()
    if block.type is NodeType.CHECKBOX:
        return block.checkbox_state is None or not (block.checkbox_option or block.text)
    if block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        return not _semantic_fragments(block)
    if block.type is NodeType.LIST:
        return not block.text and not block.children
    return False


def _semantic_coverage(block: Block, body: str) -> float:
    if block.verification is VerificationState.REJECTED:
        return 0.0
    if _incomplete_structure(block):
        return 0.0
    expected = _semantic_tokens(block)
    if not expected:
        return 1.0
    rendered = Counter(WORD_PATTERN.findall(body.replace(r"\|", "|").casefold()))
    covered = sum((expected & rendered).values())
    return round(covered / sum(expected.values()), 6)


def _page_quality_reasons(
    page,
    blocks: list[Block],
    coverages: list[float],
) -> list[str]:
    reasons = list(page.quality.needs_review_reasons)

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if any(block.verification is VerificationState.REJECTED for block in blocks):
        add("rejected_content")
    lineage = [item for block in blocks for item in block.correction_lineage]
    if any(item.previous_state is VerificationState.REJECTED for item in lineage):
        add("rejected_content")
    if any("skip" in item.reason.casefold() for item in lineage):
        add("skipped_correction")
    if any(block.verification is VerificationState.NEEDS_REVIEW for block in blocks):
        add("block_needs_review")
    if any(_incomplete_structure(block) for block in blocks):
        add("incomplete_structure")
    if any(coverage < SEMANTIC_COVERAGE_THRESHOLD for coverage in coverages):
        add("semantic_coverage_loss")
    if any(block.bbox is None for block in blocks):
        add("geometry_loss")

    warning_text = "\n".join(page.warnings).casefold()
    if "skipped" in warning_text:
        add("skipped_correction")
    if any(term in warning_text for term in ("probe", "recovery", "quality gate")) and (
        "unresolved" in warning_text
        or "not inspected" in warning_text
        or "unavailable" in warning_text
        or "skipped" in warning_text
    ):
        add("unresolved_recovery")
    if any(
        term in warning_text
        for term in ("unresolved", "failed", "invalid", "ignored", "ambiguous")
    ):
        add("unresolved_warning")

    block_reasons = "\n".join(
        block.verification_reason or "" for block in blocks
    ).casefold()
    if "probe" in block_reasons or "recovery" in block_reasons:
        add("unresolved_recovery")
    return reasons


def _computed_page_quality(page, emissions: dict[str, _Emission]) -> PageQuality:
    blocks = list(_walk_blocks(page.blocks))
    coverages: list[float] = []
    for block in blocks:
        emission = emissions.get(block.id)
        body = (emission.coverage_body or emission.body) if emission else ""
        coverages.append(_semantic_coverage(block, body))
    coverage = (
        round(sum(coverages) / len(coverages), 6)
        if coverages
        else page.quality.semantic_coverage
    )
    return PageQuality(
        semantic_coverage=coverage,
        coverage_threshold=SEMANTIC_COVERAGE_THRESHOLD,
        needs_review_reasons=_page_quality_reasons(page, blocks, coverages),
    )


def materialize_document_quality(document: Document) -> Document:
    """Populate canonical page quality before serializing any document format."""

    _markdown, emissions = _render_with_emissions(document)
    for page in document.pages:
        page.quality = _computed_page_quality(page, emissions)
    return document


def render_agentic_document(
    document: Document,
    *,
    usage: RunUsage | None = None,
    trace: list[AgentTraceEvent] | None = None,
    runtime_diagnostics: RuntimeDiagnostics | None = None,
    duration_ms: int = 0,
    elements: list[Element] | None = None,
    parse_metadata: ParseMetadata | None = None,
    markdown_override: str | None = None,
    recovery_log: list[VisualRecoveryResult] | None = None,
) -> RenderedAgenticDocument:
    """Render canonical Markdown together with its grounded v4 envelope."""

    base_markdown, emissions = _render_with_emissions(document)
    markdown = markdown_override if markdown_override is not None else base_markdown
    pages: list[dict] = []
    for page in document.pages:
        page_nodes: list[dict] = []
        page_start: int | None = None
        page_end: int | None = None
        page_blocks = list(_walk_blocks(page.blocks))
        coverages: list[float] = []
        for block in page_blocks:
            emission = emissions.get(block.id)
            rendered = emission is not None
            body = emission.body if emission is not None else ""
            coverage_body = (
                emission.coverage_body or body if emission is not None else ""
            )
            start = emission.start if emission is not None else None
            end = emission.end if emission is not None else None
            coverage = _semantic_coverage(block, coverage_body)
            coverages.append(coverage)
            status = block.verification
            if status is VerificationState.VERIFIED and (
                coverage < SEMANTIC_COVERAGE_THRESHOLD or _incomplete_structure(block)
            ):
                status = VerificationState.NEEDS_REVIEW
            if start is not None and end is not None:
                page_start = start if page_start is None else min(page_start, start)
                page_end = end if page_end is None else max(page_end, end)
            atoms = (
                _agentic_atoms(
                    block,
                    base_markdown,
                    start,
                    end,
                    page.number,
                    checkbox_group_span=emission.checkbox_group_span,
                )
                if rendered
                else []
            )
            for atom in atoms:
                atom_span = atom["source"]["span"]
                if atom_span is None:
                    continue
                page_start = (
                    atom_span["start"]
                    if page_start is None
                    else min(page_start, atom_span["start"])
                )
                page_end = (
                    atom_span["end"]
                    if page_end is None
                    else max(page_end, atom_span["end"])
                )
            page_nodes.append(
                {
                    "id": block.id,
                    "type": block.type.value,
                    "status": status.value,
                    "reading_order": len(page_nodes),
                    "confidence": block.confidence,
                    "text": block.text,
                    "source": _source(page.number, start, end, block.bbox),
                    "atoms": atoms,
                    "semantic": _semantic_payload(block),
                    "children": [child.id for child in block.children],
                    "rendered": rendered,
                    "reason": block.verification_reason
                    or (None if rendered else "No renderable semantic content"),
                    "verification_reason": block.verification_reason,
                    "semantic_coverage": coverage,
                    "coverage_threshold": SEMANTIC_COVERAGE_THRESHOLD,
                    "correction_lineage": [
                        item.model_dump(mode="json")
                        for item in block.correction_lineage
                    ],
                }
            )
        computed_quality = _computed_page_quality(page, emissions)
        quality_reasons = computed_quality.needs_review_reasons
        pages.append(
            {
                "id": f"page-{page.number}",
                "number": page.number,
                "status": "needs_review"
                if quality_reasons
                or any(
                    node["status"]
                    in {
                        VerificationState.NEEDS_REVIEW.value,
                        VerificationState.REJECTED.value,
                    }
                    for node in page_nodes
                )
                else "ok",
                "width": page.width,
                "height": page.height,
                "source": _source(
                    page.number,
                    page_start,
                    page_end,
                    None,
                ),
                "blocks": page_nodes,
                "warnings": page.warnings,
                "quality": computed_quality.model_dump(mode="json"),
                "analysis": page.analysis.model_dump(mode="json")
                if page.analysis
                else None,
            }
        )

    run_usage = usage or RunUsage()
    public_elements = elements if elements is not None else build_elements(document)
    metadata = parse_metadata or ParseMetadata(
        pages=len(document.pages),
        processing_time=duration_ms / 1000,
    )
    payload = {
        "schema_version": "4.4.0",
        "markdown": markdown,
        "base_markdown": base_markdown,
        "document_type": None,
        "sections": [],
        "extracted_fields": {},
        "recovery_log": [
            item.model_dump(mode="json") for item in (recovery_log or [])
        ],
        "metadata": {
            **metadata.model_dump(mode="json"),
            "source_name": document.source_name,
            "source_sha256": document.source_sha256,
            "page_count": len(document.pages),
            "failed_pages": [],
            "duration_ms": duration_ms,
            "range_units": "unicode_codepoints",
            "range_target": "base_markdown",
            "usage": run_usage.model_dump(mode="json"),
            "trace": [event.model_dump(mode="json") for event in (trace or [])],
            "runtime": (
                runtime_diagnostics.model_dump(mode="json")
                if runtime_diagnostics is not None
                else None
            ),
            "warnings": document.warnings,
        },
        "elements": [element.model_dump(mode="json") for element in public_elements],
        "document": {"id": "document", "pages": pages},
    }
    return RenderedAgenticDocument(
        markdown=markdown,
        json=json.dumps(payload, ensure_ascii=False, indent=2),
    )


def render_combined_result(
    parse_result: ParseResult,
    analysis: AgenticAnalysis | None = None,
    extraction: ExtractionResult | None = None,
    *,
    custom_classification: FormClassificationResult | None = None,
    routed_extraction: RoutedExtractionResult | None = None,
) -> str:
    """Flatten optional agentic results into the canonical v4.5 envelope."""

    payload = parse_result.structured_json
    payload["schema_version"] = "4.5.0"
    payload["document_type"] = (
        analysis.classification.model_dump(mode="json")
        if analysis and analysis.classification
        else None
    )
    payload["sections"] = (
        [item.model_dump(mode="json") for item in analysis.toc.sections]
        if analysis and analysis.toc
        else []
    )
    payload["extracted_fields"] = (
        {
            name: field.model_dump(mode="json")
            for name, field in extraction.fields.items()
        }
        if extraction
        else {}
    )
    routing = routed_extraction.classification if routed_extraction else custom_classification
    payload["custom_classification"] = (
        routing.model_dump(mode="json") if routing is not None else None
    )
    payload["form_extractions"] = (
        [
            {
                "segment_id": item.segment_id,
                "category": item.category,
                "start_page": item.start_page,
                "end_page": item.end_page,
                "schema_name": item.schema_name,
                "status": item.status,
                "error": item.error,
                "data": item.extraction.data if item.extraction else None,
                "evidence": item.extraction.evidence if item.extraction else {},
                "fields": (
                    {
                        name: field.model_dump(mode="json")
                        for name, field in item.extraction.fields.items()
                    }
                    if item.extraction
                    else {}
                ),
                "warnings": item.extraction.warnings if item.extraction else [],
            }
            for item in routed_extraction.forms
        ]
        if routed_extraction
        else []
    )
    payload["recovery_log"] = [
        item.model_dump(mode="json") for item in parse_result.recovery_log
    ]

    metadata = payload["metadata"]
    routing_traces = (
        routed_extraction.trace
        if routed_extraction is not None
        else custom_classification.trace
        if custom_classification is not None
        else []
    )
    routing_usage = (
        routed_extraction.usage.calls
        if routed_extraction is not None
        else custom_classification.usage.calls
        if custom_classification is not None
        else []
    )
    extra_traces = [
        *(analysis.trace if analysis else []),
        *(extraction.trace if extraction else []),
        *routing_traces,
    ]
    extra_usage = [
        *(analysis.usage.calls if analysis else []),
        *(extraction.usage.calls if extraction else []),
        *routing_usage,
    ]
    extra_recovery_time = sum(
        item.duration_ms for item in extra_traces if item.image_count
    ) / 1000
    extra_agentic_time = sum(
        item.duration_ms for item in extra_traces if not item.image_count
    ) / 1000
    metadata["luna_recovery_time"] = (
        parse_result.metadata.luna_recovery_time + extra_recovery_time
    )
    metadata["luna_agentic_time"] = (
        parse_result.metadata.luna_agentic_time + extra_agentic_time
    )
    metadata["luna_time"] = (
        metadata["luna_recovery_time"] + metadata["luna_agentic_time"]
    )
    metadata["engine"] = (
        "glm-ocr + gpt-5.6-luna"
        if parse_result.trace or extra_traces
        else "glm-ocr"
    )
    metadata["feature_statuses"] = (
        {
            name: feature.model_dump(mode="json")
            for name, feature in analysis.features.items()
        }
        if analysis
        else {}
    )
    combined_usage = RunUsage(
        calls=[*(parse_result.usage or RunUsage()).calls, *extra_usage]
    )
    metadata["usage"] = combined_usage.model_dump(mode="json")
    metadata["trace"].extend(
        item.model_dump(mode="json") for item in extra_traces
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _source(page: int, start: int | None, end: int | None, bbox) -> dict:
    return {
        "page": page,
        "span": {"start": start, "end": end}
        if start is not None and end is not None
        else None,
        "bbox": bbox.model_dump(mode="json") if bbox is not None else None,
    }


def _atom_values(block: Block) -> list[tuple[str, str, object, str, object | None]]:
    if block.atoms and block.type not in {
        NodeType.FIGURE,
        NodeType.IMAGE,
        NodeType.CHART,
    }:
        return [
            (atom.kind, atom.text, atom.bbox or block.bbox, "literal", atom)
            for atom in block.atoms
        ]
    if block.type is NodeType.TABLE and block.table is not None:
        values = [
            (
                "table_cell",
                _table_cell_atom_text(cell.text),
                cell.bbox or block.bbox,
                "literal",
                cell,
            )
            for cell in block.table.cells
        ]
        values.extend(
            ("table_residual", text, block.bbox, "literal", None)
            for text in _table_residual_lines(block)
        )
        return values
    if block.type is NodeType.CHECKBOX:
        values = []
        if block.checkbox_group:
            values.append(
                ("checkbox_group", block.checkbox_group, block.bbox, "literal", None)
            )
        values.append(
            ("checkbox_marker", _checkbox_marker(block), block.bbox, "literal", None)
        )
        option = _checkbox_text(block)
        if option:
            values.append(("checkbox_option", option, block.bbox, "literal", None))
        return values
    visible = block.text or _body(block)
    return [
        ("line", line, block.bbox, "literal", None)
        for line in visible.splitlines()
        if line
    ]


def _table_cell_atom_text(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ")


def _emitted_confidence_spans(
    evidence: object | None,
    owner_text: str,
    emitted_text: str,
) -> list[dict[str, object]]:
    if evidence is None or not evidence.low_confidence_spans:
        return []
    source_text = evidence.text
    if owner_text == source_text:
        normalize = lambda value: value
    elif owner_text == _table_cell_atom_text(source_text):
        normalize = _table_cell_atom_text
    else:
        return []
    escaped_owner = owner_text.replace("|", r"\|")
    if emitted_text == owner_text:
        render = lambda value: value
        prefix_length = 0
    elif emitted_text == escaped_owner:
        render = lambda value: value.replace("|", r"\|")
        prefix_length = 0
    elif emitted_text.endswith(escaped_owner):
        render = lambda value: value.replace("|", r"\|")
        prefix_length = len(emitted_text) - len(escaped_owner)
    else:
        return []
    emitted: list[dict[str, object]] = []
    for span in evidence.low_confidence_spans:
        start = prefix_length + len(render(normalize(source_text[: span.start])))
        end = prefix_length + len(render(normalize(source_text[: span.end])))
        item: dict[str, object] = {
            "start": start,
            "end": end,
            "text": emitted_text[start:end],
            "confidence": (
                span.confidence
                if span.confidence is not None
                else evidence.confidence
                if evidence.confidence is not None
                else 0.5
            ),
            "source": span.source or "unknown",
        }
        bbox = span.bbox or evidence.bbox
        if bbox is not None:
            item["bbox"] = bbox.model_dump(mode="json")
        emitted.append(item)
    return emitted


def _visual_agentic_atoms(
    block: Block,
    start: int,
    page_number: int,
) -> list[dict]:
    positioned: list[tuple[_VisualSegment, int, int]] = []
    cursor = start + len("<figure>")
    for segment in _visual_segments(block):
        end = cursor + len(segment.rendered_text)
        positioned.append((segment, cursor, end))
        cursor = end + len("\n\n")
    ordered = [item for item in positioned if item[0].provider]
    ordered.extend(item for item in positioned if not item[0].provider)
    atoms = []
    for index, (segment, atom_start, atom_end) in enumerate(ordered, start=1):
        item = {
            "id": f"{block.id}-a{index}",
            "kind": segment.kind,
            "text": segment.rendered_text,
            "origin": segment.origin,
            "source": _source(
                block.citation.page if block.citation is not None else page_number,
                atom_start,
                atom_end,
                segment.bbox,
            ),
        }
        if segment.evidence is not None:
            if segment.evidence.confidence is not None:
                item["confidence"] = segment.evidence.confidence
            spans = _emitted_confidence_spans(
                segment.evidence,
                segment.raw_text,
                segment.rendered_text,
            )
            if spans:
                item["low_confidence_spans"] = spans
        atoms.append(item)
    return atoms


def _agentic_atoms(
    block: Block,
    markdown: str,
    start: int,
    end: int,
    page_number: int,
    *,
    checkbox_group_span: tuple[int, int] | None = None,
) -> list[dict]:
    if block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        return _visual_agentic_atoms(block, start, page_number)
    atoms: list[dict] = []
    atom_cursor = start
    for kind, text, bbox, origin, evidence in _atom_values(block):
        if kind == "checkbox_group":
            if checkbox_group_span is None:
                continue
            atom_start, atom_end = checkbox_group_span
            rendered_text = markdown[atom_start:atom_end]
            if rendered_text != text:
                continue
        else:
            candidates = [text]
            escaped = text.replace("|", r"\|")
            if escaped != text:
                candidates.append(escaped)
            matches = [
                (markdown.find(candidate, atom_cursor, end), candidate)
                for candidate in candidates
            ]
            matches = [match for match in matches if match[0] >= 0]
            if not matches:
                matches = [
                    (markdown.find(candidate, start, end), candidate)
                    for candidate in candidates
                ]
                matches = [match for match in matches if match[0] >= 0]
            if not matches:
                continue
            atom_start, rendered_text = min(matches, key=lambda match: match[0])
            atom_end = atom_start + len(rendered_text)
            atom_cursor = atom_end
        index = len(atoms) + 1
        item = {
            "id": f"{block.id}-a{index}",
            "kind": kind,
            "text": markdown[atom_start:atom_end],
            "origin": origin,
            "source": _source(
                block.citation.page if block.citation is not None else page_number,
                atom_start,
                atom_end,
                bbox,
            ),
        }
        if evidence is not None:
            if evidence.confidence is not None:
                item["confidence"] = evidence.confidence
            spans = _emitted_confidence_spans(evidence, text, rendered_text)
            if spans:
                item["low_confidence_spans"] = spans
        atoms.append(item)
    return atoms


def _semantic_payload(block: Block) -> dict:
    table = block.table.model_dump(mode="json") if block.table is not None else None
    if table is not None and block.table is not None:
        for cell, payload in zip(block.table.cells, table["cells"], strict=True):
            payload["low_confidence_spans"] = [
                {
                    "start": span.start,
                    "end": span.end,
                    "text": cell.text[span.start : span.end],
                    "confidence": (
                        span.confidence
                        if span.confidence is not None
                        else cell.confidence
                        if cell.confidence is not None
                        else block.confidence
                    ),
                    "source": span.source or "unknown",
                    "bbox": (
                        (span.bbox or cell.bbox).model_dump(mode="json")
                        if span.bbox is not None or cell.bbox is not None
                        else None
                    ),
                }
                for span in cell.low_confidence_spans
            ]
    return {
        "heading_level": block.heading_level,
        "list_marker": block.list_marker,
        "table": table,
        "form": block.form.model_dump(mode="json") if block.form is not None else None,
        "checkbox_state": block.checkbox_state.value if block.checkbox_state else None,
        "checkbox_group": block.checkbox_group,
        "checkbox_option": block.checkbox_option,
        "caption": block.caption,
        "figure_description": block.figure_description,
        "chart_type": block.chart_type,
        "chart_data": [point.model_dump(mode="json") for point in block.chart_data],
    }


def _as_pdf(data: bytes, filename: str) -> bytes:
    if Path(filename).suffix.casefold() == ".pdf":
        return data
    with pymupdf.open() as output:
        with Image.open(io.BytesIO(data)) as image:
            for frame in ImageSequence.Iterator(image):
                rgb = ImageOps.exif_transpose(frame).convert("RGB")
                buffer = io.BytesIO()
                rgb.save(buffer, "PNG")
                page = output.new_page(width=rgb.width, height=rgb.height)
                page.insert_image(page.rect, stream=buffer.getvalue())
        return output.tobytes()


def _walk_blocks(blocks: list[Block]) -> Iterator[Block]:
    for block in blocks:
        yield block
        yield from _walk_blocks(block.children)


def _annotation_group(element_type: str) -> str:
    if element_type in {"heading", "title"}:
        return "heading"
    if element_type in {"table", "form_field", "checkbox"}:
        return "table"
    if element_type in {"figure", "image", "chart"}:
        return "figure"
    if element_type == "formula":
        return "formula"
    if element_type in {"seal", "signature"}:
        return "seal"
    return "text"


def _annotation_label(element: Element, show_reading_order: bool) -> str:
    group = _annotation_group(element.type)
    names = {
        "heading": "Title",
        "table": "Form" if element.type in {"form_field", "checkbox"} else "Table",
        "figure": "Figure",
        "formula": "Formula",
        "seal": "Seal" if element.type == "seal" else "Signature",
        "text": "Text",
    }
    if show_reading_order:
        return (
            str(element.reading_order)
            if group in {"text", "heading"}
            else f"{names[group]} {element.reading_order}"
        )
    return names[group]


def render_annotated_pdf(
    data: bytes,
    filename: str,
    content: Document | list[Element],
    *,
    page_count: int | None = None,
    show_reading_order: bool = True,
    selected_element_id: str | None = None,
    recovered_element_ids: set[str] | None = None,
) -> bytes:
    source = _as_pdf(data, filename)
    if isinstance(content, Document):
        elements = build_elements(content)
        expected_pages = len(content.pages)
    else:
        elements = content
        expected_pages = page_count
    recovered_ids = recovered_element_ids or set()
    with pymupdf.open(stream=source, filetype="pdf") as output:
        if expected_pages is not None and output.page_count != expected_pages:
            raise ValueError("source and extracted document page counts do not match")
        for element in elements:
            if element.bbox is None or not 1 <= element.page <= output.page_count:
                continue
            page = output[element.page - 1]
            x0, y0, x1, y1 = element.bbox
            rect = pymupdf.Rect(
                x0 * page.rect.width,
                y0 * page.rect.height,
                x1 * page.rect.width,
                y1 * page.rect.height,
            )
            color = ANNOTATION_COLORS[_annotation_group(element.type)]
            page.draw_rect(rect, color=color, width=1.25, overlay=True)
            if element.id in recovered_ids:
                page.draw_rect(
                    rect,
                    color=RECOVERY_ANNOTATION_COLOR,
                    dashes="[4 2]",
                    width=2,
                    overlay=True,
                )
            if element.id == selected_element_id:
                halo = pymupdf.Rect(rect)
                halo.x0 = max(0, halo.x0 - 2)
                halo.y0 = max(0, halo.y0 - 2)
                halo.x1 = min(page.rect.width, halo.x1 + 2)
                halo.y1 = min(page.rect.height, halo.y1 + 2)
                page.draw_rect(
                    halo,
                    color=(0.98, 0.76, 0.08),
                    width=3,
                    overlay=True,
                )

            label = _annotation_label(element, show_reading_order)
            font_size = 6
            padding = 1.5
            label_width = pymupdf.get_text_length(
                label, fontname="helv", fontsize=font_size
            )
            box_width = label_width + padding * 2
            box_height = font_size + padding * 2
            x = min(max(1.0, rect.x0), max(1.0, page.rect.width - box_width - 1))
            y0_label = rect.y0 - box_height if rect.y0 >= box_height + 1 else rect.y0
            label_rect = pymupdf.Rect(x, y0_label, x + box_width, y0_label + box_height)
            page.draw_rect(
                label_rect,
                color=color,
                fill=color,
                width=0.5,
                overlay=True,
            )
            page.insert_text(
                pymupdf.Point(x + padding, y0_label + font_size + padding / 2),
                label,
                fontname="helv",
                fontsize=font_size,
                color=(1, 1, 1),
                overlay=True,
            )
        return output.tobytes(garbage=3, deflate=True)
