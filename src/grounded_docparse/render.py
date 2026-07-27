from __future__ import annotations

import io
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence

from .models import (
    AgentTraceEvent,
    Block,
    Document,
    NodeType,
    RunUsage,
    VerificationState,
)

ANNOTATION_COLORS = {
    VerificationState.VERIFIED: (0.0, 0.55, 0.2),
    VerificationState.NEEDS_REVIEW: (1.0, 0.55, 0.0),
    VerificationState.REJECTED: (0.85, 0.1, 0.1),
    VerificationState.NOT_CHECKED: (0.1, 0.35, 0.85),
}

SEMANTIC_COVERAGE_THRESHOLD = 1.0


def _checkbox_marker(block: Block) -> str:
    return {"checked": "[x]", "unchecked": "[ ]"}.get(
        str(block.checkbox_state), "[?]"
    )


def _has_equivalent_leading_marker(text: str, marker: str) -> bool:
    return bool(
        re.match(rf"^{re.escape(marker)}(?=\s|$)", text.lstrip(), re.IGNORECASE)
    )


def _residual_lines(text: str, represented: list[str]) -> list[str]:
    residuals: list[str] = []
    for line in text.splitlines():
        residual = line
        for value in represented:
            if value:
                residual = residual.replace(value.replace("\r", " ").replace("\n", " "), "", 1)
        residual = residual.strip(" \t|")
        if any(character not in ":()-[]" for character in residual):
            residuals.append(residual)
    return residuals


def _table(block: Block) -> str:
    if block.table is None or not block.table.cells:
        return block.text
    rows: dict[int, list] = {}
    for cell in block.table.cells:
        rows.setdefault(cell.row, []).append(cell)
    lines: list[str] = []
    for row_index in sorted(rows):
        cells = sorted(rows[row_index], key=lambda item: item.column)
        values = [cell.text.replace("\r", " ").replace("\n", " ").replace("|", r"\|") for cell in cells]
        lines.append("| " + " | ".join(values) + " |")
        if row_index == min(rows):
            lines.append("| " + " | ".join("---" for _ in cells) + " |")
    residuals = _residual_lines(
        block.text,
        [cell.text for cell in block.table.cells],
    )
    if residuals:
        lines.extend(["", *residuals])
    return "\n".join(lines)


def _visual(block: Block) -> str:
    values: list[tuple[str, str]] = []
    if block.text:
        values.append(("text", block.text))
    if block.caption:
        values.append(("caption", block.caption))
    if block.figure_description:
        values.append(("description", block.figure_description))

    parts: list[str] = []
    seen: set[str] = set()
    multiple = len({value for _kind, value in values}) > 1
    for kind, value in values:
        if value in seen:
            continue
        seen.add(value)
        if multiple and kind != "text":
            parts.append(f"{kind.title()}: {value}")
        else:
            parts.append(value)
    for atom in block.atoms:
        if atom.text and atom.text not in seen:
            seen.add(atom.text)
            label = atom.kind.replace("_", " ").title()
            parts.append(f"{label}: {atom.text}")
    if block.chart_type:
        parts.append(f"Chart type: {block.chart_type}")
    for point in block.chart_data:
        prefix = f"{point.series} — " if point.series else ""
        parts.append(f"{prefix}{point.label}: {point.value}")
    content = "\n\n".join(parts)
    return f"<figure>{content}</figure>" if parts else ""


def _body(block: Block) -> str:
    if block.verification is VerificationState.REJECTED:
        return ""
    text = block.text
    if block.type is NodeType.HEADING:
        return f"{'#' * (block.heading_level or 1)} {text}"
    if block.type is NodeType.TABLE:
        return _table(block)
    if block.type is NodeType.CHECKBOX:
        return f"{_checkbox_marker(block)} {text}"
    if block.type is NodeType.LIST_ITEM:
        marker = block.list_marker or "-"
        return text if _has_equivalent_leading_marker(text, marker) else f"{marker} {text}"
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
        residuals = _residual_lines(
            block.text,
            [block.form.label, value or "", hint or ""],
        )
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

    def finish(self) -> str:
        return "".join(self.parts).rstrip() + "\n"


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
                options = " ".join(
                    f"{_checkbox_marker(item)} {_checkbox_text(item)}"
                    for item in members
                )
                builder.append_body(f"**{group}:** {options}", members)
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


def render_json(document: Document) -> str:
    return document.model_dump_json(indent=2)


@dataclass(frozen=True, slots=True)
class RenderedAgenticDocument:
    markdown: str
    json: str


def _semantic_fragments(block: Block) -> list[str]:
    fragments: list[str] = []
    if block.type is NodeType.TABLE and block.table is not None and block.table.cells:
        fragments.extend(cell.text for cell in block.table.cells)
        fragments.extend(
            _residual_lines(block.text, [cell.text for cell in block.table.cells])
        )
    elif block.type is NodeType.FORM_FIELD and block.form is not None:
        fragments.extend(
            [
                block.form.label.rstrip().removesuffix(":"),
                block.form.value or "",
                block.form.hint or "",
            ]
        )
        fragments.extend(
            _residual_lines(
                block.text,
                [block.form.label, block.form.value or "", block.form.hint or ""],
            )
        )
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


def _incomplete_structure(block: Block) -> bool:
    if block.type is NodeType.TABLE:
        return block.table is None or not block.table.cells
    if block.type is NodeType.FORM_FIELD:
        return block.form is None or not block.form.label.strip()
    if block.type is NodeType.CHECKBOX:
        return block.checkbox_state is None or not (
            block.checkbox_option or block.text
        )
    if block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        return not _semantic_fragments(block)
    if block.type is NodeType.LIST:
        return not block.text and not block.children
    return False


def _semantic_coverage(block: Block, body: str) -> float:
    if block.verification is VerificationState.REJECTED:
        return 0.0
    fragments = _semantic_fragments(block)
    if not fragments:
        return 0.0 if _incomplete_structure(block) else 1.0
    searchable = body.replace(r"\|", "|")
    total = sum(len(fragment) for fragment in fragments)
    covered = sum(len(fragment) for fragment in fragments if fragment in searchable)
    return round(covered / total, 6) if total else 1.0


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
    if any(block.verification is VerificationState.NEEDS_REVIEW for block in blocks):
        add("block_needs_review")
    if any(_incomplete_structure(block) for block in blocks):
        add("incomplete_structure")
    if any(coverage < SEMANTIC_COVERAGE_THRESHOLD for coverage in coverages):
        add("semantic_coverage_loss")
    if any(block.bbox is None for block in blocks):
        add("geometry_loss")

    ordering = page.specialist_audit.ordering_resolution
    if ordering is not None and ordering.outcome == "needs_review":
        add("ordering_failure")
    if any(
        resolution.outcome == "needs_review"
        for resolution in page.specialist_audit.resolutions
    ):
        add("specialist_conflict")

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


def render_agentic_document(
    document: Document,
    *,
    usage: RunUsage | None = None,
    trace: list[AgentTraceEvent] | None = None,
    duration_ms: int = 0,
) -> RenderedAgenticDocument:
    """Render canonical Markdown together with its grounded v2 envelope."""

    markdown, emissions = _render_with_emissions(document)
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
            start = emission.start if emission is not None else None
            end = emission.end if emission is not None else None
            coverage = _semantic_coverage(block, body)
            coverages.append(coverage)
            status = block.verification
            if (
                status is VerificationState.VERIFIED
                and coverage < SEMANTIC_COVERAGE_THRESHOLD
            ):
                status = VerificationState.NEEDS_REVIEW
            if start is not None and end is not None:
                page_start = start if page_start is None else min(page_start, start)
                page_end = end if page_end is None else max(page_end, end)
            atoms = (
                _agentic_atoms(block, markdown, start, end, page.number)
                if rendered
                else []
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
        quality_reasons = _page_quality_reasons(page, page_blocks, coverages)
        page_coverage = (
            round(sum(coverages) / len(coverages), 6)
            if coverages
            else page.quality.semantic_coverage
        )
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
                "specialist_audit": page.specialist_audit.model_dump(mode="json"),
                "warnings": page.warnings,
                "quality": {
                    "semantic_coverage": page_coverage,
                    "coverage_threshold": SEMANTIC_COVERAGE_THRESHOLD,
                    "needs_review_reasons": quality_reasons,
                },
            }
        )

    run_usage = usage or RunUsage()
    payload = {
        "schema_version": "2.0.0",
        "markdown": markdown,
        "metadata": {
            "source_name": document.source_name,
            "source_sha256": document.source_sha256,
            "page_count": len(document.pages),
            "failed_pages": [],
            "duration_ms": duration_ms,
            "range_units": "unicode_codepoints",
            "usage": run_usage.model_dump(mode="json"),
            "trace": [event.model_dump(mode="json") for event in (trace or [])],
            "warnings": document.warnings,
        },
        "document": {"id": "document", "pages": pages},
    }
    return RenderedAgenticDocument(
        markdown=markdown,
        json=json.dumps(payload, ensure_ascii=False, indent=2),
    )


def _source(page: int, start: int | None, end: int | None, bbox) -> dict:
    return {
        "page": page,
        "span": {"start": start, "end": end}
        if start is not None and end is not None
        else None,
        "bbox": bbox.model_dump(mode="json") if bbox is not None else None,
    }


def _atom_values(block: Block) -> list[tuple[str, str, object, str]]:
    if block.atoms:
        return [
            (atom.kind, atom.text, atom.bbox or block.bbox, "literal")
            for atom in block.atoms
        ]
    if block.type is NodeType.TABLE and block.table is not None:
        values = [
            ("table_cell", cell.text, cell.bbox or block.bbox, "literal")
            for cell in block.table.cells
        ]
        values.extend(
            ("table_residual", text, block.bbox, "literal")
            for text in _residual_lines(
                block.text, [cell.text for cell in block.table.cells]
            )
        )
        return values
    if block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        values: list[tuple[str, str, object, str]] = []
        if block.text:
            values.append(("visual_text", block.text, block.bbox, "literal"))
        if block.caption:
            values.append(("caption", block.caption, block.bbox, "literal"))
        if block.figure_description:
            values.append(
                (
                    "visual_description",
                    block.figure_description,
                    block.bbox,
                    "generated_description",
                )
            )
        return values
    visible = block.text or _body(block)
    return [
        ("line", line, block.bbox, "literal")
        for line in visible.splitlines()
        if line
    ]


def _agentic_atoms(
    block: Block,
    markdown: str,
    start: int,
    end: int,
    page_number: int,
) -> list[dict]:
    atoms: list[dict] = []
    atom_cursor = start
    for kind, text, bbox, origin in _atom_values(block):
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
        atoms.append(
            {
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
        )
    return atoms


def _semantic_payload(block: Block) -> dict:
    return {
        "heading_level": block.heading_level,
        "list_marker": block.list_marker,
        "table": block.table.model_dump(mode="json") if block.table is not None else None,
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


def render_annotated_pdf(data: bytes, filename: str, document: Document) -> bytes:
    source = _as_pdf(data, filename)
    with pymupdf.open(stream=source, filetype="pdf") as output:
        if output.page_count != len(document.pages):
            raise ValueError("source and extracted document page counts do not match")
        for index, page_record in enumerate(document.pages):
            page = output[index]
            for block in _walk_blocks(page_record.blocks):
                if block.bbox is None:
                    continue
                rect = pymupdf.Rect(
                    block.bbox.x0 * page.rect.width,
                    block.bbox.y0 * page.rect.height,
                    block.bbox.x1 * page.rect.width,
                    block.bbox.y1 * page.rect.height,
                )
                color = ANNOTATION_COLORS[block.verification]
                page.draw_rect(rect, color=color, width=1, overlay=True)
                label = (
                    f"{block.id} {block.type.value} "
                    f"{block.confidence:.0%} {block.verification.value}"
                )[:80]
                label_width = pymupdf.get_text_length(
                    label, fontname="helv", fontsize=6
                )
                x = min(max(2.0, rect.x0), max(2.0, page.rect.width - label_width - 2))
                y = rect.y0 - 2 if rect.y0 >= 9 else min(page.rect.height - 2, rect.y0 + 8)
                page.insert_text(
                    pymupdf.Point(x, y),
                    label,
                    fontname="helv",
                    fontsize=6,
                    color=color,
                    overlay=True,
                )
        return output.tobytes(garbage=3, deflate=True)
