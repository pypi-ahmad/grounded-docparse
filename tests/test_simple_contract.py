import io

import pymupdf
import pytest
from PIL import Image

from grounded_docparse import render as document_render
from grounded_docparse.models import (
    Block,
    BoundingBox,
    Citation,
    Document,
    Element,
    FormData,
    Page,
    PageDraft,
    RegionDraft,
    TableCell,
    TableData,
    VerificationState,
)
from grounded_docparse.render import (
    render_agentic_document,
    render_markdown,
    sanitize_markdown_preview,
)


def test_annotated_pdf_draws_nested_audit_boxes(simple_pdf: bytes) -> None:
    child = Block(
        id="p1-b2",
        type="paragraph",
        text="Visible source text.",
        bbox=BoundingBox(x0=0.1, y0=0.25, x1=0.9, y1=0.4),
        reading_order=1,
        confidence=0.95,
        verification=VerificationState.NEEDS_REVIEW,
    )
    document = Document(
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
                        type="heading",
                        text="Water quality",
                        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
                        reading_order=0,
                        confidence=0.98,
                        verification=VerificationState.VERIFIED,
                        children=[child],
                    )
                ],
            )
        ],
    )
    renderer = getattr(document_render, "render_annotated_pdf", None)

    assert callable(renderer), "render_annotated_pdf is missing"
    annotated = renderer(
        simple_pdf,
        "notice.pdf",
        document,
        recovered_element_ids={"p1-b2"},
    )

    with pymupdf.open(stream=annotated, filetype="pdf") as rendered:
        assert rendered.page_count == 1
        drawings = rendered[0].get_drawings()
        assert len(drawings) == 5
        assert any(drawing["dashes"] != "[] 0" for drawing in drawings)
        labels = rendered[0].get_text()
    assert labels.splitlines()[-2:] == ["1", "2"]


def test_annotated_pdf_converts_multiframe_image() -> None:
    first = Image.new("RGB", (40, 20), "white")
    second = Image.new("RGB", (30, 50), "white")
    source = io.BytesIO()
    first.save(source, format="TIFF", save_all=True, append_images=[second])
    document = Document(
        source_name="scan.tiff",
        source_sha256="b" * 64,
        pages=[
            Page(number=1, width=40, height=20),
            Page(number=2, width=30, height=50),
        ],
    )

    annotated = document_render.render_annotated_pdf(
        source.getvalue(), "scan.tiff", document
    )

    with pymupdf.open(stream=annotated, filetype="pdf") as rendered:
        assert rendered.page_count == 2
        assert rendered[0].rect == pymupdf.Rect(0, 0, 40, 20)
        assert rendered[1].rect == pymupdf.Rect(0, 0, 30, 50)


def test_annotated_pdf_rejects_page_count_mismatch(simple_pdf: bytes) -> None:
    document = Document(
        source_name="notice.pdf",
        source_sha256="c" * 64,
        pages=[],
    )

    with pytest.raises(ValueError, match="page counts do not match"):
        document_render.render_annotated_pdf(simple_pdf, "notice.pdf", document)


def test_annotated_pdf_supports_semantic_labels_and_selected_overlay(
    simple_pdf: bytes,
) -> None:
    element = Element(
        id="table-1",
        type="table",
        page=1,
        bbox=(0.1, 0.1, 0.9, 0.4),
        text="A table",
        reading_order=1,
        confidence=0.9,
    )

    annotated = document_render.render_annotated_pdf(
        simple_pdf,
        "notice.pdf",
        [element],
        page_count=1,
        show_reading_order=False,
        selected_element_id="table-1",
    )

    with pymupdf.open(stream=annotated, filetype="pdf") as rendered:
        drawings = rendered[0].get_drawings()
        labels = rendered[0].get_text()
    assert len(drawings) == 3
    assert drawings[0]["color"] == pytest.approx((0.086, 0.639, 0.29), abs=0.01)
    assert drawings[1]["color"] == pytest.approx((0.98, 0.76, 0.08), abs=0.01)
    assert labels.splitlines()[-1] == "Table"


def test_nested_document_renders_layout_aware_markdown_and_json() -> None:
    heading = Block(
        id="p1-b1",
        type="heading",
        text="Water quality",
        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
        reading_order=0,
        confidence=0.98,
        verification=VerificationState.VERIFIED,
        citation=Citation(page=1, bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)),
        children=[
            Block(
                id="p1-b2",
                type="paragraph",
                text="Visible source text.",
                bbox=BoundingBox(x0=0.1, y0=0.25, x1=0.9, y1=0.4),
                reading_order=1,
                confidence=0.95,
                verification=VerificationState.VERIFIED,
                citation=Citation(page=1, bbox=BoundingBox(x0=0.1, y0=0.25, x1=0.9, y1=0.4)),
                section_path=["Water quality"],
            )
        ],
    )
    document = Document(
        source_name="notice.pdf",
        source_sha256="a" * 64,
        pages=[Page(number=1, width=612, height=792, blocks=[heading])],
    )

    markdown = render_markdown(document)
    json_text = render_agentic_document(document).json

    assert "# Water quality" in markdown
    assert "Visible source text." in markdown
    assert "page=1" not in markdown
    assert "<!-- source" not in markdown
    assert '"children"' in json_text


def test_only_rejected_blocks_are_suppressed_without_warning_callouts() -> None:
    block = Block(
        id="p1-b1",
        type="paragraph",
        text="Unsupported model text",
        reading_order=0,
        verification=VerificationState.REJECTED,
        verification_reason="Not visible",
    )
    document = Document(
        source_name="scan.png",
        source_sha256="b" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    markdown = render_markdown(document)

    assert "Unsupported model text" not in markdown
    assert "[UNRESOLVED" not in markdown


def test_needs_review_text_remains_readable_and_auditable() -> None:
    block = Block(
        id="p1-b1",
        type="paragraph",
        text="Readable draft text",
        reading_order=0,
        verification=VerificationState.NEEDS_REVIEW,
        verification_reason="No verification decision",
    )
    document = Document(
        source_name="scan.png",
        source_sha256="d" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    assert render_markdown(document) == "Readable draft text\n"
    payload = render_agentic_document(document).json
    assert '"status": "needs_review"' in payload
    assert '"verification_reason": "No verification decision"' in payload


def test_semantic_html_table_keeps_original_layout_in_markdown() -> None:
    source = '<table><tr><td colspan="2">[?] Participating</td></tr></table>'
    block = Block(
        id="p1-b1",
        type="table",
        text=source,
        reading_order=0,
        table=TableData(
            cells=[TableCell(row=0, column=0, column_span=2, text="[?] Participating")]
        ),
    )
    document = Document(
        source_name="form.pdf",
        source_sha256="f" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    assert render_markdown(document) == f"{source}\n"


def test_markdown_preview_preserves_markdown_and_sanitizes_supported_html() -> None:
    source = (
        "# Heading\n\n> Quoted text\n\n"
        "`<code-tag>` [link](https://example.com/?a=1&b=2)\n\n"
        '<table border="1" onclick="alert(1)"><tr>'
        '<td colspan="2" onmouseover="alert(2)">'
        "<script>alert(3)</script>Cell</td></tr></table>\n\n"
        '<figure><div style="text-align: center;">'
        '<img src="imgs/page-2.jpg" alt="Image" width="22%" '
        'onerror="alert(4)"></div>Text</figure>\n\n'
        '<figure><img src="https://example.com/tracker.jpg"></figure>\n\n'
        '<div style="text-align: center;">Specialty: PAIN MEDICINE</div>\n\n'
        '<img src="x" onerror="alert(5)">'
    )

    preview = sanitize_markdown_preview(source)

    assert "# Heading\n\n> Quoted text" in preview
    assert "`&lt;code-tag&gt;` [link](https://example.com/?a=1&b=2)" in preview
    assert '<table border="1">' in preview
    assert '<td colspan="2">alert(3)Cell</td>' in preview
    assert "onclick" not in preview
    assert "onmouseover" not in preview
    assert "<script" not in preview
    assert "alert(3)" in preview
    assert (
        '<figure><div style="text-align:center">'
        '<img src="imgs/page-2.jpg" alt="Image" width="22%">'
        "</div>Text</figure>"
    ) in preview
    assert '<div style="text-align:center">Specialty: PAIN MEDICINE</div>' in preview
    assert "alert(4)" not in preview
    assert '<figure><img></figure>' in preview
    assert '<img src="x">' in preview
    assert "alert(5)" not in preview


def test_provider_draft_accepts_unordered_coordinates_for_local_validation() -> None:
    draft = PageDraft.model_validate(
        {
            "regions": [
                {
                    "type": "paragraph",
                    "reading_order": 0,
                    "text": "Visible",
                    "bbox": {"x0": 0.8, "y0": 0.1, "x1": 0.2, "y1": 0.3},
                }
            ]
        }
    )

    assert isinstance(draft.regions[0], RegionDraft)


def test_markdown_escapes_source_name_and_table_cells() -> None:
    block = Block(
        id="p1-b1",
        type="table",
        text="",
        reading_order=0,
        verification=VerificationState.VERIFIED,
        table=TableData(
            cells=[TableCell(row=0, column=0, text="Name | value\ncontinued")]
        ),
    )
    document = Document(
        source_name='report\nmalicious: true.pdf',
        source_sha256="c" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    markdown = render_markdown(document)

    assert "source:" not in markdown
    assert "Name \\| value continued" in markdown


def test_clean_markdown_renders_document_elements_and_exact_page_break() -> None:
    blocks = [
        Block(id="h", type="header", text="Agency header", reading_order=0),
        Block(id="p", type="paragraph", text="Body paragraph.", reading_order=1),
        Block(id="l1", type="list_item", text="First", list_marker="1.", reading_order=2),
        Block(id="l2", type="list_item", text="Second", list_marker="a.", reading_order=3),
        Block(
            id="f",
            type="form_field",
            text="Account: 123",
            form=FormData(label="Account", value="123"),
            reading_order=4,
        ),
        Block(
            id="c1",
            type="checkbox",
            text="Yes",
            checkbox_group="Evidence of Tampering",
            checkbox_option="Yes",
            checkbox_state="unchecked",
            reading_order=5,
        ),
        Block(
            id="c2",
            type="checkbox",
            text="No",
            checkbox_group="Evidence of Tampering",
            checkbox_option="No",
            checkbox_state="checked",
            reading_order=6,
        ),
        Block(
            id="t",
            type="table",
            reading_order=7,
            table=TableData(cells=[TableCell(row=0, column=0, text="Office")]),
        ),
        Block(
            id="g",
            type="figure",
            text="",
            figure_description="Bottle fill line",
            reading_order=8,
        ),
        Block(id="z", type="footer", text="Page footer", reading_order=9),
    ]
    document = Document(
        source_name="guide.pdf",
        source_sha256="e" * 64,
        pages=[
            Page(number=1, width=100, height=100, blocks=blocks),
            Page(number=2, width=100, height=100, blocks=[]),
        ],
    )

    markdown = render_markdown(document)

    assert markdown.count("<!-- PAGE BREAK -->") == 1
    assert "Agency header" in markdown and "Page footer" in markdown
    assert "1. First" in markdown and "a. Second" in markdown
    assert "**Account:** 123" in markdown
    assert "**Evidence of Tampering:** [ ] Yes [x] No" in markdown
    assert markdown.count("Evidence of Tampering") == 1
    assert "| Office |" in markdown
    assert "<figure>Bottle fill line</figure>" in markdown
    assert not markdown.startswith("---\n")


def test_markdown_does_not_duplicate_equivalent_list_marker_in_item_text() -> None:
    document = Document(
        source_name="steps.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(id="alpha", type="list_item", text="a. Preserve case.", list_marker="A.", reading_order=0),
                    Block(id="roman", type="list_item", text="(iv) Archive the record.", list_marker="(IV)", reading_order=1),
                ],
            )
        ],
    )

    assert render_markdown(document) == "a. Preserve case.\n\n(iv) Archive the record.\n"


def test_schema_version_and_list_marker_are_preserved_in_json() -> None:
    block = Block(id="item", type="list_item", text="Step", list_marker="1.", reading_order=0)
    document = Document(
        source_name="steps.pdf",
        source_sha256="f" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    json_text = render_agentic_document(document).json

    assert '"schema_version": "4.4.0"' in json_text
    assert '"list_marker": "1."' in json_text


def test_unchecked_high_confidence_content_has_truthful_audit_state() -> None:
    block = Block(id="body", type="paragraph", text="Literal text", reading_order=0)

    assert block.verification is VerificationState.NOT_CHECKED
    assert '"status": "not_checked"' in render_agentic_document(
        Document(
            source_name="scan.pdf",
            source_sha256="a" * 64,
            pages=[Page(number=1, width=100, height=100, blocks=[block])],
        )
    ).json


def test_provider_draft_accepts_explicit_form_and_checkbox_fields() -> None:
    draft = PageDraft.model_validate(
        {
            "regions": [
                {
                    "type": "form_field",
                    "reading_order": 0,
                    "text": "Collected Date: yyyy-mm-dd",
                    "form": {"label": "Collected Date", "value": "yyyy-mm-dd"},
                },
                {
                    "type": "checkbox",
                    "reading_order": 1,
                    "text": "Yes",
                    "checkbox_group": "Evidence of Cooling",
                    "checkbox_option": "Yes",
                    "checkbox_state": "unchecked",
                },
            ]
        }
    )

    assert draft.regions[0].form == FormData(label="Collected Date", value="yyyy-mm-dd")
    assert draft.regions[1].checkbox_group == "Evidence of Cooling"


def test_form_label_with_source_colon_renders_one_colon() -> None:
    document = Document(
        source_name="form.pdf",
        source_sha256="b" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="field",
                        type="form_field",
                        text="REPORT TO: 65",
                        form=FormData(label="REPORT TO:", value="65"),
                        reading_order=0,
                    )
                ],
            )
        ],
    )

    assert render_markdown(document) == "**REPORT TO:** 65\n"


def test_form_hint_remains_visible_and_structured_in_json() -> None:
    document = Document(
        source_name="form.pdf",
        source_sha256="c" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="pws",
                        type="form_field",
                        text="PWS Id: MO1010001\nMO######",
                        form=FormData(
                            label="PWS Id",
                            value="MO1010001",
                            hint="MO######",
                        ),
                        reading_order=0,
                    ),
                    Block(
                        id="date",
                        type="form_field",
                        text="Collected Date:\nyyyy-mm-dd",
                        form=FormData(
                            label="Collected Date",
                            hint="yyyy-mm-dd",
                        ),
                        reading_order=1,
                    ),
                ],
            )
        ],
    )

    markdown = render_markdown(document)
    json_text = render_agentic_document(document).json

    assert "**PWS Id:** MO1010001 (MO######)" in markdown
    assert "**Collected Date:** yyyy-mm-dd" in markdown
    assert '"hint": "MO######"' in json_text
