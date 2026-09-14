"""AI Markdown presentation refinement: chunk a document for the provider, then re-apply its plan.

Builds `EnhancementChunk`s (anchored markdown + layout) bounded by
MAX_CHUNK_PAGES/MAX_CHUNK_CHARACTERS, and applies a returned
`MarkdownPresentationPlan` back onto the original blocks in `render_chunk_plan`.

Must not: let the plan change block identity, membership, or reading order,
or recast a non-text block (table, figure, form, checkbox, etc.) into a text
role - `render_chunk_plan` validates the plan against the original block set
before rendering anything, and `_compatible` gates which types may be
recast at all. This is presentation only; it never touches evidence.

Next: render.py, which owns the block model and the base rendering this
module composes (`_body`, `_render_with_emissions`, `render_markdown`).
"""

import json
from dataclasses import dataclass

from .models import (
    Block,
    Document,
    MarkdownPresentationPlan,
    NodeType,
    Page,
    VerificationState,
)
from .render import _body, _render_with_emissions, render_markdown

MAX_CHUNK_PAGES = 8
MAX_CHUNK_CHARACTERS = 48_000
_TEXT_TYPES = {
    NodeType.HEADING,
    NodeType.PARAGRAPH,
    NodeType.LIST,
    NodeType.LIST_ITEM,
    NodeType.CAPTION,
    NodeType.FOOTNOTE,
    NodeType.REFERENCE,
    NodeType.HEADER,
    NodeType.FOOTER,
}


@dataclass(frozen=True, slots=True)
class EnhancementChunk:
    index: int
    page_numbers: tuple[int, ...]
    anchored_markdown: str
    layout: list[dict]


def _walk(blocks: list[Block]):
    for block in sorted(blocks, key=lambda item: item.reading_order):
        yield block
        yield from _walk(block.children)


def _page_input(page: Page) -> tuple[str, list[dict]]:
    single = Document(
        source_name="enhancement",
        source_sha256="0" * 64,
        pages=[page.model_copy(deep=True)],
    )
    markdown, emissions = _render_with_emissions(single)
    # Insert markers back-to-front (highest offset first) so inserting one
    # marker never shifts the character offsets still to be used for the
    # markers before it.
    insertions = sorted(
        ((emission.start, block_id) for block_id, emission in emissions.items()),
        reverse=True,
    )
    for offset, block_id in insertions:
        markdown = markdown[:offset] + f"<!-- element:{block_id} -->\n" + markdown[offset:]
    layout = []
    for block in _walk(page.blocks):
        if block.verification is VerificationState.REJECTED:
            continue
        layout.append(
            {
                "id": block.id,
                "page": page.number,
                "type": block.type.value,
                "reading_order": block.reading_order,
                "bbox": block.bbox.model_dump(mode="json") if block.bbox else None,
            }
        )
    return markdown, layout


def build_enhancement_chunks(
    document: Document,
) -> tuple[list[EnhancementChunk], list[int]]:
    chunks: list[EnhancementChunk] = []
    skipped: list[int] = []
    pending: list[tuple[int, str, list[dict]]] = []
    pending_size = 0

    def flush() -> None:
        nonlocal pending, pending_size
        if not pending:
            return
        chunks.append(
            EnhancementChunk(
                index=len(chunks),
                page_numbers=tuple(item[0] for item in pending),
                anchored_markdown="\n<!-- PAGE BREAK -->\n".join(
                    item[1] for item in pending
                ),
                layout=[record for item in pending for record in item[2]],
            )
        )
        pending = []
        pending_size = 0

    for page in document.pages:
        markdown, layout = _page_input(page)
        serialized = json.dumps(layout, ensure_ascii=False, separators=(",", ":"))
        size = len(markdown) + len(serialized)
        if not layout:
            continue
        if size > MAX_CHUNK_CHARACTERS:
            # Unlike agentic.py's context packing, a single page too large
            # to fit one chunk is skipped rather than split further:
            # presentation refinement is optional, so giving up on that page
            # (its original rendering is kept, see combine_page_markdown) is
            # preferable to a chunk boundary that cuts through one page.
            flush()
            skipped.append(page.number)
            continue
        if pending and (
            len(pending) >= MAX_CHUNK_PAGES
            or pending_size + size > MAX_CHUNK_CHARACTERS
        ):
            flush()
        pending.append((page.number, markdown, layout))
        pending_size += size
    flush()
    return chunks, skipped


def _compatible(block: Block, render_as: str) -> bool:
    # "source" (no recast) is always allowed; any other target role is only
    # allowed for blocks already in _TEXT_TYPES - a table, figure, form
    # field, or checkbox can never be recast into a text role, regardless of
    # what the plan requests.
    return render_as == "source" or (
        block.type in _TEXT_TYPES
        and render_as in {"heading", "paragraph", "list_item", "caption"}
    )


def render_chunk_plan(
    document: Document,
    chunk: EnhancementChunk,
    plan: MarkdownPresentationPlan,
) -> dict[int, str]:
    pages = {page.number: page for page in document.pages}
    planned_pages = {page.page: page for page in plan.pages}
    # Trust boundary for the provider's presentation plan: page coverage,
    # element membership/uniqueness, and element order are all validated
    # against the original block set before any directive is applied. A
    # plan may only choose how to render existing blocks, never add,
    # drop, duplicate, or reorder them.
    if set(planned_pages) != set(chunk.page_numbers):
        raise ValueError("Luna plan must contain every chunk page exactly once")

    rendered: dict[int, str] = {}
    role_types = {
        "heading": NodeType.HEADING,
        "paragraph": NodeType.PARAGRAPH,
        "list_item": NodeType.LIST_ITEM,
        "caption": NodeType.CAPTION,
    }
    for page_number in chunk.page_numbers:
        page = pages[page_number]
        blocks = {
            block.id: block
            for block in _walk(page.blocks)
            if block.verification is not VerificationState.REJECTED
        }
        directives = planned_pages[page_number].elements
        ids = [directive.element_id for directive in directives]
        if len(ids) != len(set(ids)) or set(ids) != set(blocks):
            raise ValueError("Luna plan must contain each eligible element exactly once")
        if ids != list(blocks):
            raise ValueError("Luna plan must preserve GLM element order")
        parts: list[str] = []
        for directive in directives:
            source = blocks[directive.element_id]
            compatible = _compatible(source, directive.render_as)
            block = source.model_copy(deep=True)
            block.children = []
            if compatible and directive.render_as != "source":
                block.type = role_types[directive.render_as]
            if compatible and directive.heading_level is not None:
                block.heading_level = directive.heading_level
            body = _body(block)
            if compatible and directive.list_depth:
                body = "\n".join(
                    f"{'  ' * directive.list_depth}{line}" for line in body.splitlines()
                )
            if not body:
                continue
            if compatible and directive.group_with_previous and parts:
                parts[-1] = f"{parts[-1].rstrip()} {body.lstrip()}"
            else:
                parts.append(body)
        rendered[page_number] = "\n\n".join(parts).rstrip() + "\n"
    return rendered


def combine_page_markdown(document: Document, refined: dict[int, str]) -> str:
    pages = []
    for page in document.pages:
        pages.append(
            refined.get(
                page.number,
                render_markdown(
                    Document(
                        source_name=document.source_name,
                        source_sha256=document.source_sha256,
                        pages=[page.model_copy(deep=True)],
                    )
                ),
            ).rstrip()
        )
    return "\n\n<!-- PAGE BREAK -->\n\n".join(pages).rstrip() + "\n"
