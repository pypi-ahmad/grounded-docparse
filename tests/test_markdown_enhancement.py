from __future__ import annotations

import pytest

from grounded_docparse.enhancement import (
    build_enhancement_chunks,
    combine_page_markdown,
    render_chunk_plan,
)
from grounded_docparse.models import (
    Block,
    Document,
    MarkdownPresentationPlan,
    Page,
    PagePresentationPlan,
    PresentationDirective,
)


def _document() -> Document:
    return Document(
        source_name="notice.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=612,
                height=792,
                blocks=[
                    Block(
                        id="p1-b1",
                        type="paragraph",
                        text="Public notice",
                        reading_order=0,
                    ),
                    Block(
                        id="p1-b2",
                        type="paragraph",
                        text="Visible body",
                        reading_order=1,
                    ),
                ],
            )
        ],
    )


def test_valid_plan_changes_presentation_without_mutating_document() -> None:
    document = _document()
    chunks, skipped = build_enhancement_chunks(document)
    plan = MarkdownPresentationPlan(
        pages=[
            PagePresentationPlan(
                page=1,
                elements=[
                    PresentationDirective(
                        element_id="p1-b1", render_as="heading", heading_level=1
                    ),
                    PresentationDirective(element_id="p1-b2"),
                ],
            )
        ]
    )

    refined = render_chunk_plan(document, chunks[0], plan)
    markdown = combine_page_markdown(document, refined)

    assert skipped == []
    assert markdown.startswith("# Public notice")
    assert document.pages[0].blocks[0].type.value == "paragraph"


def test_plan_with_missing_element_fails_closed() -> None:
    document = _document()
    chunks, _skipped = build_enhancement_chunks(document)
    plan = MarkdownPresentationPlan(
        pages=[
            PagePresentationPlan(
                page=1,
                elements=[PresentationDirective(element_id="p1-b1")],
            )
        ]
    )

    with pytest.raises(ValueError, match="each eligible element"):
        render_chunk_plan(document, chunks[0], plan)


def test_incompatible_nontext_role_preserves_source_without_failing_chunk() -> None:
    document = _document()
    document.pages[0].blocks.append(
        Block(
            id="p1-b3",
            type="checkbox",
            text="Letter sent to Michael S Rogers, MD",
            checkbox_state="checked",
            reading_order=2,
        )
    )
    chunks, _skipped = build_enhancement_chunks(document)
    plan = MarkdownPresentationPlan(
        pages=[
            PagePresentationPlan(
                page=1,
                elements=[
                    PresentationDirective(
                        element_id="p1-b1", render_as="heading", heading_level=1
                    ),
                    PresentationDirective(element_id="p1-b2"),
                    PresentationDirective(
                        element_id="p1-b3",
                        render_as="paragraph",
                        group_with_previous=True,
                    ),
                ],
            )
        ]
    )

    refined = render_chunk_plan(document, chunks[0], plan)

    assert refined[1].startswith("# Public notice")
    assert "\n\n[x] Letter sent to Michael S Rogers, MD\n" in refined[1]
