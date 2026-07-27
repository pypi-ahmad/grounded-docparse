import json

import pytest

from grounded_docparse.extraction import validate_extraction_schema
from grounded_docparse.models import (
    AgentTraceEvent,
    AgentUsage,
    AtomicEvidence,
    Block,
    BoundingBox,
    CheckboxState,
    CorrectionLineage,
    Document,
    Page,
    RunUsage,
    TableCell,
    TableData,
    VerificationState,
)
from grounded_docparse.render import render_agentic_document, render_json


def test_agentic_document_maps_blocks_and_lines_to_canonical_markdown() -> None:
    block = Block(
        id="p1-b1",
        type="paragraph",
        text="Alpha line\nBeta line",
        bbox=BoundingBox(x0=0.1, y0=0.2, x1=0.9, y1=0.4),
        reading_order=0,
        confidence=0.97,
        verification=VerificationState.VERIFIED,
    )
    document = Document(
        source_name="sample.pdf",
        source_sha256="a" * 64,
        pages=[Page(number=1, width=612, height=792, blocks=[block])],
    )
    usage = RunUsage(
        calls=[
            AgentUsage(
                agent="draft_parser",
                model="gpt-5.6-luna",
                input_tokens=120,
                output_tokens=30,
            )
        ]
    )
    trace = [
        AgentTraceEvent(
            agent="document_manager",
            model="gpt-5.6-luna",
            action="finish_page",
            page=1,
            status="completed",
        )
    ]

    rendered = render_agentic_document(
        document,
        usage=usage,
        trace=trace,
        duration_ms=25,
    )
    payload = json.loads(rendered.json)

    assert rendered.markdown == "Alpha line\nBeta line\n"
    assert payload["schema_version"] == "2.0.0"
    assert payload["metadata"]["range_units"] == "unicode_codepoints"
    assert payload["metadata"]["usage"]["input_tokens"] == 120
    assert payload["metadata"]["usage"]["output_tokens"] == 30
    assert payload["metadata"]["trace"][0]["action"] == "finish_page"

    node = payload["document"]["pages"][0]["blocks"][0]
    start, end = node["source"]["span"].values()
    assert rendered.markdown[start:end] == "Alpha line\nBeta line"
    assert [atom["text"] for atom in node["atoms"]] == ["Alpha line", "Beta line"]
    for atom in node["atoms"]:
        atom_start, atom_end = atom["source"]["span"].values()
        assert rendered.markdown[atom_start:atom_end] == atom["text"]
        assert atom["source"]["bbox"]["unit"] == "normalized"

    assert json.loads(render_json(document))["schema_version"] == "1.3.0"


def test_extraction_schema_requires_nullable_closed_objects() -> None:
    schema = {
        "type": "object",
        "properties": {
            "invoice_number": {
                "type": ["string", "null"],
                "description": "Literal invoice number",
            }
        },
        "required": ["invoice_number"],
        "additionalProperties": False,
    }

    validate_extraction_schema(schema)

    non_nullable = {
        **schema,
        "properties": {
            "invoice_number": {"type": "string"},
        },
    }
    with pytest.raises(ValueError, match="nullable"):
        validate_extraction_schema(non_nullable)


def test_extraction_schema_rejects_unsupported_keywords() -> None:
    schema = {
        "type": "object",
        "properties": {
            "invoice_number": {
                "type": ["string", "null"],
                "pattern": "^INV-",
            }
        },
        "required": ["invoice_number"],
        "additionalProperties": False,
    }

    with pytest.raises(ValueError, match="pattern"):
        validate_extraction_schema(schema)


def test_provider_line_grounding_is_preserved_in_v2_atoms() -> None:
    block = Block(
        id="p2-b1",
        type="paragraph",
        text="First\nSecond",
        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.4),
        reading_order=0,
        verification=VerificationState.VERIFIED,
        atoms=[
            AtomicEvidence(
                kind="line",
                text="First",
                bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
            ),
            AtomicEvidence(
                kind="line",
                text="Second",
                bbox=BoundingBox(x0=0.1, y0=0.25, x1=0.9, y1=0.4),
            ),
        ],
    )
    document = Document(
        source_name="page-two.pdf",
        source_sha256="b" * 64,
        pages=[Page(number=2, width=100, height=100, blocks=[block])],
    )

    payload = json.loads(render_agentic_document(document).json)
    atoms = payload["document"]["pages"][0]["blocks"][0]["atoms"]

    assert atoms[0]["source"]["page"] == 2
    assert atoms[0]["source"]["bbox"]["y1"] == 0.2
    assert atoms[1]["source"]["bbox"]["y0"] == 0.25


def test_agentic_reading_order_is_contiguous_after_rejected_blocks_are_removed() -> None:
    blocks = [
        Block(id="keep-1", type="paragraph", text="First", reading_order=0),
        Block(
            id="drop",
            type="paragraph",
            text="Unsupported",
            reading_order=1,
            verification=VerificationState.REJECTED,
        ),
        Block(id="keep-2", type="paragraph", text="Second", reading_order=2),
    ]
    document = Document(
        source_name="sample.pdf",
        source_sha256="c" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=blocks)],
    )

    payload = json.loads(render_agentic_document(document).json)

    blocks = payload["document"]["pages"][0]["blocks"]
    assert [block["reading_order"] for block in blocks] == [0, 1, 2]
    assert [block["rendered"] for block in blocks] == [True, False, True]


def test_agentic_render_preserves_table_residual_and_all_visual_semantics() -> None:
    blocks = [
        Block(
            id="table",
            type="table",
            text="Plan | Cost\nPrices include tax.",
            bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.4),
            reading_order=0,
            verification=VerificationState.VERIFIED,
            table=TableData(
                cells=[
                    TableCell(row=0, column=0, text="Plan", header=True),
                    TableCell(row=0, column=1, text="Cost", header=True),
                ]
            ),
        ),
        Block(
            id="visual",
            type="figure",
            text="Dial reads 42 psi.",
            caption="Pressure gauge",
            figure_description="A round analog gauge mounted on a pipe.",
            bbox=BoundingBox(x0=0.1, y0=0.5, x1=0.9, y1=0.9),
            reading_order=1,
            verification=VerificationState.VERIFIED,
            atoms=[AtomicEvidence(kind="transcription", text="Needle above green band")],
        ),
    ]
    document = Document(
        source_name="semantics.pdf",
        source_sha256="d" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=blocks)],
    )

    rendered = render_agentic_document(document)
    payload = json.loads(rendered.json)
    nodes = payload["document"]["pages"][0]["blocks"]

    assert "Prices include tax." in rendered.markdown
    assert "Dial reads 42 psi." in rendered.markdown
    assert "Pressure gauge" in rendered.markdown
    assert "A round analog gauge mounted on a pipe." in rendered.markdown
    assert "Needle above green band" in rendered.markdown
    assert [node["semantic_coverage"] for node in nodes] == [1.0, 1.0]
    assert all(node["rendered"] for node in nodes)
    for node in nodes:
        span = node["source"]["span"]
        assert span is not None
        assert rendered.markdown[span["start"] : span["end"]]

    visual_atoms = nodes[1]["atoms"]
    assert [atom["kind"] for atom in visual_atoms] == [
        "transcription",
        "visual_text",
        "caption",
        "visual_description",
    ]
    assert [atom["origin"] for atom in visual_atoms] == [
        "literal",
        "literal",
        "literal",
        "generated_description",
    ]
    assert [atom["text"] for atom in visual_atoms] == [
        "Needle above green band",
        "Dial reads 42 psi.",
        "Pressure gauge",
        "A round analog gauge mounted on a pipe.",
    ]


def test_table_residual_preserves_prose_and_does_not_duplicate_multiline_cells() -> None:
    blocks = [
        Block(
            id="prose",
            type="table",
            text="Plan | tax\nPrices include tax.",
            reading_order=0,
            verification=VerificationState.VERIFIED,
            table=TableData(
                cells=[
                    TableCell(row=0, column=0, text="Plan"),
                    TableCell(row=0, column=1, text="tax"),
                ]
            ),
        ),
        Block(
            id="multiline",
            type="table",
            text="Line one\nLine two\nFootnote remains.",
            reading_order=1,
            verification=VerificationState.VERIFIED,
            table=TableData(
                cells=[TableCell(row=0, column=0, text="Line one\nLine two")]
            ),
        ),
    ]
    document = Document(
        source_name="tables.pdf",
        source_sha256="2" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=blocks)],
    )

    rendered = render_agentic_document(document)
    nodes = json.loads(rendered.json)["document"]["pages"][0]["blocks"]

    assert "Prices include tax." in rendered.markdown
    assert "Prices include ." not in rendered.markdown
    assert rendered.markdown.count("Line one") == 1
    assert rendered.markdown.count("Line two") == 1
    assert "Footnote remains." in rendered.markdown
    assert [node["semantic_coverage"] for node in nodes] == [1.0, 1.0]


def test_grouped_checkboxes_have_distinct_exact_member_spans() -> None:
    document = Document(
        source_name="checkboxes.pdf",
        source_sha256="3" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="yes",
                        type="checkbox",
                        reading_order=0,
                        checkbox_group="Approved",
                        checkbox_option="Yes",
                        checkbox_state=CheckboxState.UNCHECKED,
                    ),
                    Block(
                        id="no",
                        type="checkbox",
                        reading_order=1,
                        checkbox_group="Approved",
                        checkbox_option="No",
                        checkbox_state=CheckboxState.CHECKED,
                    ),
                ],
            )
        ],
    )

    rendered = render_agentic_document(document)
    nodes = json.loads(rendered.json)["document"]["pages"][0]["blocks"]
    slices = [
        rendered.markdown[node["source"]["span"]["start"] : node["source"]["span"]["end"]]
        for node in nodes
    ]

    assert slices == ["[ ] Yes", "[x] No"]
    assert nodes[0]["source"]["span"] != nodes[1]["source"]["span"]


def test_repeated_text_blocks_receive_distinct_exact_emission_spans() -> None:
    document = Document(
        source_name="repeated.pdf",
        source_sha256="e" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(id="first", type="paragraph", text="Same", reading_order=0),
                    Block(id="second", type="paragraph", text="Same", reading_order=1),
                ],
            )
        ],
    )

    rendered = render_agentic_document(document)
    nodes = json.loads(rendered.json)["document"]["pages"][0]["blocks"]
    spans = [node["source"]["span"] for node in nodes]

    assert spans[0] != spans[1]
    assert [
        rendered.markdown[span["start"] : span["end"]] for span in spans
    ] == ["Same", "Same"]


def test_rejected_and_empty_probe_history_remain_auditable_and_mark_page_review() -> None:
    rejected = Block(
        id="rejected",
        type="paragraph",
        text="Unsupported account 999",
        reading_order=0,
        verification=VerificationState.REJECTED,
        verification_reason="Not grounded in the source",
    )
    probe = Block(
        id="probe",
        type="image",
        reading_order=1,
        verification=VerificationState.NEEDS_REVIEW,
        verification_reason="Scan omission probe was not inspected",
    )
    corrected = Block(
        id="corrected",
        type="paragraph",
        text="Grounded account 123",
        bbox=BoundingBox(x0=0.1, y0=0.7, x1=0.9, y1=0.8),
        reading_order=2,
        verification=VerificationState.VERIFIED,
        correction_lineage=[
            CorrectionLineage(
                original_id="rejected",
                replacement_id="corrected",
                provider_id="addition-1",
                reason="Grounded quality correction",
                previous_state=VerificationState.REJECTED,
                final_state=VerificationState.VERIFIED,
            )
        ],
    )
    page = Page(
        number=1,
        width=100,
        height=100,
        blocks=[rejected, probe, corrected],
        warnings=["Page 1: skipped added region addition-2 with invalid bounding box"],
    )
    document = Document(
        source_name="history.pdf",
        source_sha256="f" * 64,
        pages=[page],
    )

    rendered = render_agentic_document(document)
    payload_page = json.loads(rendered.json)["document"]["pages"][0]
    nodes = {node["id"]: node for node in payload_page["blocks"]}

    assert "Unsupported account 999" not in rendered.markdown
    assert nodes["rejected"]["rendered"] is False
    assert nodes["rejected"]["reason"] == "Not grounded in the source"
    assert nodes["rejected"]["verification_reason"] == "Not grounded in the source"
    assert nodes["rejected"]["source"]["span"] is None
    assert nodes["rejected"]["atoms"] == []
    assert nodes["probe"]["rendered"] is False
    assert nodes["corrected"]["correction_lineage"][0]["original_id"] == "rejected"
    assert payload_page["status"] == "needs_review"
    assert set(payload_page["quality"]["needs_review_reasons"]) >= {
        "rejected_content",
        "skipped_correction",
        "unresolved_recovery",
        "geometry_loss",
    }


def test_verified_incomplete_structure_fails_full_semantic_coverage() -> None:
    block = Block(
        id="empty-table",
        type="table",
        reading_order=0,
        verification=VerificationState.VERIFIED,
        table=TableData(),
    )
    document = Document(
        source_name="incomplete.pdf",
        source_sha256="1" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    page = json.loads(render_agentic_document(document).json)["document"]["pages"][0]
    node = page["blocks"][0]

    assert node["semantic_coverage"] == 0.0
    assert node["status"] == "needs_review"
    assert set(page["quality"]["needs_review_reasons"]) >= {
        "incomplete_structure",
        "semantic_coverage_loss",
    }


def test_verified_replacement_preserves_rejected_lineage_in_page_status() -> None:
    replacement = Block(
        id="replacement",
        type="paragraph",
        text="Grounded replacement",
        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2),
        reading_order=0,
        verification=VerificationState.VERIFIED,
        correction_lineage=[
            CorrectionLineage(
                original_id="rejected-original",
                replacement_id="replacement",
                reason="Replaced unsupported predecessor",
                previous_state=VerificationState.REJECTED,
                final_state=VerificationState.VERIFIED,
            )
        ],
    )
    document = Document(
        source_name="lineage.pdf",
        source_sha256="4" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[replacement])],
    )

    page = json.loads(render_agentic_document(document).json)["document"]["pages"][0]

    assert page["status"] == "needs_review"
    assert "rejected_content" in page["quality"]["needs_review_reasons"]
