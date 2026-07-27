import json

import pytest

from grounded_docparse.extraction import validate_extraction_schema
from grounded_docparse.models import (
    AgentTraceEvent,
    AgentUsage,
    AtomicEvidence,
    Block,
    BoundingBox,
    Document,
    Page,
    RunUsage,
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
