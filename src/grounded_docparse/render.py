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


def _checkbox_marker(block: Block) -> str:
    return {"checked": "[x]", "unchecked": "[ ]"}.get(
        str(block.checkbox_state), "[?]"
    )


def _has_equivalent_leading_marker(text: str, marker: str) -> bool:
    return bool(
        re.match(rf"^{re.escape(marker)}(?=\s|$)", text.lstrip(), re.IGNORECASE)
    )


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
    return "\n".join(lines)


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
            return f"**{label}:** {value} ({hint})"
        if value is not None:
            return f"**{label}:** {value}"
        if hint is not None:
            return f"**{label}:** {hint}"
        return f"**{label}:**"
    if block.type in {NodeType.HEADER, NodeType.FOOTER}:
        return text
    if block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        description = block.figure_description or block.caption or text
        return f"<figure>{description}</figure>" if description else ""
    return text


def _render_block(block: Block, lines: list[str]) -> None:
    body = _body(block)
    if body:
        lines.extend([body, ""])
    for child in sorted(block.children, key=lambda item: item.reading_order):
        _render_block(child, lines)


def _render_blocks(blocks: list[Block], lines: list[str]) -> None:
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
                    f"{_checkbox_marker(item)} {item.checkbox_option or item.text}"
                    for item in members
                )
                lines.extend([f"**{group}:** {options}", ""])
            for member in members:
                _render_blocks(member.children, lines)
            continue
        _render_block(block, lines)
        index += 1


def render_markdown(document: Document) -> str:
    lines: list[str] = []
    for page_index, page in enumerate(document.pages):
        if page_index:
            lines.extend(["<!-- PAGE BREAK -->", ""])
        _render_blocks(page.blocks, lines)
    return "\n".join(lines).rstrip() + "\n"


def render_json(document: Document) -> str:
    return document.model_dump_json(indent=2)


@dataclass(frozen=True, slots=True)
class RenderedAgenticDocument:
    markdown: str
    json: str


def render_agentic_document(
    document: Document,
    *,
    usage: RunUsage | None = None,
    trace: list[AgentTraceEvent] | None = None,
    duration_ms: int = 0,
) -> RenderedAgenticDocument:
    """Render canonical Markdown together with its grounded v2 envelope."""

    markdown = render_markdown(document)
    cursor = 0
    pages: list[dict] = []
    for page in document.pages:
        page_nodes: list[dict] = []
        page_start: int | None = None
        page_end: int | None = None
        for block in _walk_blocks(page.blocks):
            if block.verification is VerificationState.REJECTED:
                continue
            body = _body(block)
            if not body:
                continue
            start = markdown.find(body, cursor)
            if start < 0:
                start = markdown.find(body)
            if start < 0:
                continue
            end = start + len(body)
            cursor = end
            page_start = start if page_start is None else min(page_start, start)
            page_end = end if page_end is None else max(page_end, end)
            atoms = _agentic_atoms(block, body, markdown, start, end, page.number)
            page_nodes.append(
                {
                    "id": block.id,
                    "type": block.type.value,
                    "status": block.verification.value,
                    "reading_order": len(page_nodes),
                    "confidence": block.confidence,
                    "text": block.text,
                    "source": _source(page.number, start, end, block.bbox),
                    "atoms": atoms,
                    "semantic": _semantic_payload(block),
                    "children": [child.id for child in block.children],
                }
            )
        pages.append(
            {
                "id": f"page-{page.number}",
                "number": page.number,
                "status": "needs_review"
                if any(node["status"] == VerificationState.NEEDS_REVIEW.value for node in page_nodes)
                else "ok",
                "width": page.width,
                "height": page.height,
                "source": _source(
                    page.number,
                    page_start or 0,
                    page_end or (page_start or 0),
                    None,
                ),
                "blocks": page_nodes,
                "specialist_audit": page.specialist_audit.model_dump(mode="json"),
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


def _source(page: int, start: int, end: int, bbox) -> dict:
    return {
        "page": page,
        "span": {"start": start, "end": end},
        "bbox": bbox.model_dump(mode="json") if bbox is not None else None,
    }


def _agentic_atoms(
    block: Block, body: str, markdown: str, start: int, end: int, page_number: int
) -> list[dict]:
    if block.atoms:
        values = [(atom.kind, atom.text, atom.bbox or block.bbox) for atom in block.atoms]
    elif block.type is NodeType.TABLE and block.table is not None:
        values = [("table_cell", cell.text, cell.bbox or block.bbox) for cell in block.table.cells]
    elif block.type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
        values = [("visual_region", body, block.bbox)]
    else:
        visible = block.text or body
        values = [("line", line, block.bbox) for line in visible.splitlines() if line]

    atoms: list[dict] = []
    atom_cursor = start
    for index, (kind, text, bbox) in enumerate(values, start=1):
        atom_start = markdown.find(text, atom_cursor, end)
        if atom_start < 0:
            atom_start = start
            atom_end = end
        else:
            atom_end = atom_start + len(text)
            atom_cursor = atom_end
        atoms.append(
            {
                "id": f"{block.id}-a{index}",
                "kind": kind,
                "text": markdown[atom_start:atom_end],
                "origin": "generated_description"
                if kind == "visual_region"
                else "literal",
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
