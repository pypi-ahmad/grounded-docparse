import json

import pytest

from grounded_docparse.extraction import DocumentExtractor
from grounded_docparse.models import (
    AgentUsage,
    Block,
    BoundingBox,
    Document,
    Page,
    ParseResult,
    RunUsage,
    VerificationState,
)
from grounded_docparse.render import render_agentic_document, render_json

SCHEMA = {
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


def _parse_result() -> ParseResult:
    document = Document(
        source_name="invoice.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=612,
                height=792,
                blocks=[
                    Block(
                        id="p1-b1",
                        type="form_field",
                        text="Invoice number: INV-7",
                        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.7, y1=0.2),
                        reading_order=0,
                        confidence=0.99,
                        verification=VerificationState.VERIFIED,
                    )
                ],
            )
        ],
    )
    rendered = render_agentic_document(document)
    return ParseResult(
        document=document,
        markdown=rendered.markdown,
        json=rendered.json,
        legacy_json=render_json(document),
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"",
    )


class ExtractionGateway:
    def __init__(self) -> None:
        self.usage = RunUsage()
        self.trace = []
        self.extract_calls = []

    def propose_schema(self, instruction, _parse_payload):
        assert instruction == "Extract the invoice number"
        self.usage.calls.append(
            AgentUsage(
                agent="schema_architect",
                model="gpt-5.6-luna",
                input_tokens=10,
                output_tokens=5,
            )
        )
        return {"schema_json": json.dumps(SCHEMA)}

    def extract_document(self, _parse_payload, schema, *, use_terra, issues=None):
        self.extract_calls.append((use_terra, issues))
        assert schema == SCHEMA
        self.usage.calls.append(
            AgentUsage(
                agent="extractor" if not use_terra else "extraction_critic",
                model="gpt-5.6-terra" if use_terra else "gpt-5.6-luna",
                input_tokens=20,
                output_tokens=8,
            )
        )
        return {
            "data": {"invoice_number": "INV-7"},
            "evidence": [
                {
                    "pointer": "/invoice_number",
                    "block_ids": ["p1-b1"],
                    "atom_ids": ["p1-b1-a1"],
                }
            ],
        }


def test_schema_architect_returns_valid_editable_schema() -> None:
    gateway = ExtractionGateway()
    extractor = DocumentExtractor(gateway_factory=lambda _config: gateway)

    proposal = extractor.propose_schema(
        "Extract the invoice number",
        _parse_result(),
    )

    assert proposal.json_schema == SCHEMA
    assert proposal.instruction == "Extract the invoice number"
    assert proposal.usage.input_tokens == 10


def test_extract_returns_schema_data_with_resolved_evidence() -> None:
    gateway = ExtractionGateway()
    extractor = DocumentExtractor(gateway_factory=lambda _config: gateway)

    result = extractor.extract(_parse_result(), SCHEMA)

    assert result.data == {"invoice_number": "INV-7"}
    citation = result.evidence["/invoice_number"][0]
    assert citation["block_id"] == "p1-b1"
    assert citation["atom_id"] == "p1-b1-a1"
    assert citation["page"] == 1
    assert citation["bbox"]["unit"] == "normalized"
    assert gateway.extract_calls == [(False, None)]
    assert result.input_tokens == 20
    assert result.output_tokens == 8
    assert json.loads(result.json)["data"] == result.data


class RepairingExtractionGateway(ExtractionGateway):
    def extract_document(self, parse_payload, schema, *, use_terra, issues=None):
        if not use_terra:
            self.extract_calls.append((use_terra, issues))
            return {
                "data": {"invoice_number": "INV-7"},
                "evidence": [],
            }
        assert issues and "missing evidence" in issues[0]
        return super().extract_document(
            parse_payload,
            schema,
            use_terra=use_terra,
            issues=issues,
        )


def test_missing_evidence_gets_one_terra_repair() -> None:
    gateway = RepairingExtractionGateway()
    extractor = DocumentExtractor(gateway_factory=lambda _config: gateway)

    result = extractor.extract(_parse_result(), SCHEMA)

    assert result.data["invoice_number"] == "INV-7"
    assert [use_terra for use_terra, _issues in gateway.extract_calls] == [False, True]
    assert result.warnings == []


class RejectedEvidenceGateway(ExtractionGateway):
    def extract_document(self, _parse_payload, _schema, *, use_terra, issues=None):
        self.extract_calls.append((use_terra, issues))
        return {
            "data": {"invoice_number": "UNSUPPORTED-9"},
            "evidence": [
                {
                    "pointer": "/invoice_number",
                    "block_ids": ["rejected"],
                    "atom_ids": [],
                }
            ],
        }


def test_rejected_audit_block_cannot_be_used_as_extraction_evidence() -> None:
    document = Document(
        source_name="rejected.pdf",
        source_sha256="b" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="rejected",
                        type="paragraph",
                        text="Invoice number: UNSUPPORTED-9",
                        reading_order=0,
                        verification=VerificationState.REJECTED,
                        verification_reason="Hallucinated",
                    )
                ],
            )
        ],
    )
    rendered = render_agentic_document(document)
    parse_result = ParseResult(
        document=document,
        markdown=rendered.markdown,
        json=rendered.json,
        legacy_json=render_json(document),
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"",
    )
    gateway = RejectedEvidenceGateway()

    result = DocumentExtractor(gateway_factory=lambda _config: gateway).extract(
        parse_result, SCHEMA
    )

    assert result.data == {"invoice_number": None}
    assert result.evidence == {}
    assert any("unknown block rejected" in warning for warning in result.warnings)
    assert [use_terra for use_terra, _issues in gateway.extract_calls] == [False, True]


class LaunderingEvidenceGateway(ExtractionGateway):
    def __init__(self) -> None:
        super().__init__()
        self.payloads = []

    def extract_document(self, _parse_payload, _schema, *, use_terra, issues=None):
        self.payloads.append(_parse_payload)
        self.extract_calls.append((use_terra, issues))
        return {
            "data": {"invoice_number": "REJECTED-ONLY-9"},
            "evidence": [
                {
                    "pointer": "/invoice_number",
                    "block_ids": ["accepted"],
                    "atom_ids": [],
                }
            ],
        }


def test_rejected_only_value_cannot_be_laundered_through_rendered_citation() -> None:
    document = Document(
        source_name="laundering.pdf",
        source_sha256="c" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="rejected",
                        type="paragraph",
                        text="Invoice: REJECTED-ONLY-9",
                        reading_order=0,
                        verification=VerificationState.REJECTED,
                        verification_reason="Unsupported",
                    ),
                    Block(
                        id="accepted",
                        type="paragraph",
                        text="Invoice: ACCEPTED-7",
                        reading_order=1,
                        verification=VerificationState.VERIFIED,
                    ),
                ],
            )
        ],
    )
    rendered = render_agentic_document(document)
    canonical_payload = json.loads(rendered.json)
    canonical_payload["metadata"]["trace"] = [
        {"summary": "Rejected audit echoed REJECTED-ONLY-9"}
    ]
    canonical_page = canonical_payload["document"]["pages"][0]
    canonical_page["specialist_audit"] = {
        "reason": "Rejected audit echoed REJECTED-ONLY-9"
    }
    accepted = next(
        block for block in canonical_page["blocks"] if block["id"] == "accepted"
    )
    accepted["correction_lineage"] = [
        {"reason": "Replaced rejected REJECTED-ONLY-9"}
    ]
    parse_result = ParseResult(
        document=document,
        markdown=rendered.markdown,
        json=json.dumps(canonical_payload),
        legacy_json=render_json(document),
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"",
    )
    gateway = LaunderingEvidenceGateway()

    result = DocumentExtractor(gateway_factory=lambda _config: gateway).extract(
        parse_result, SCHEMA
    )

    assert "REJECTED-ONLY-9" in parse_result.json
    assert all(
        "REJECTED-ONLY-9" not in json.dumps(payload)
        for payload in gateway.payloads
    )
    assert result.data == {"invoice_number": None}
    assert result.evidence == {}
    assert any("does not contain extracted value" in item for item in result.warnings)


class LiteralEvidenceGateway(ExtractionGateway):
    def __init__(self, value) -> None:
        super().__init__()
        self.value = value

    def extract_document(self, _parse_payload, _schema, *, use_terra, issues=None):
        self.extract_calls.append((use_terra, issues))
        return {
            "data": {"value": self.value},
            "evidence": [
                {
                    "pointer": "/value",
                    "block_ids": ["accepted"],
                    "atom_ids": [],
                }
            ],
        }


@pytest.mark.parametrize(
    ("kind", "value", "source_text"),
    [
        ("integer", 1234, "Total: 1,234"),
        ("number", 1234.5, "Amount: $1,234.50"),
        ("boolean", True, "[x] Approved"),
    ],
)
def test_scalar_grounding_accepts_deterministic_literal_normalization(
    kind: str,
    value,
    source_text: str,
) -> None:
    schema = {
        "type": "object",
        "properties": {"value": {"type": [kind, "null"]}},
        "required": ["value"],
        "additionalProperties": False,
    }
    document = Document(
        source_name="literal.pdf",
        source_sha256="d" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="accepted",
                        type="paragraph",
                        text=source_text,
                        reading_order=0,
                        verification=VerificationState.VERIFIED,
                    )
                ],
            )
        ],
    )
    rendered = render_agentic_document(document)
    parse_result = ParseResult(
        document=document,
        markdown=rendered.markdown,
        json=rendered.json,
        legacy_json=render_json(document),
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"",
    )
    gateway = LiteralEvidenceGateway(value)

    result = DocumentExtractor(gateway_factory=lambda _config: gateway).extract(
        parse_result, schema
    )

    assert result.data == {"value": value}
    assert result.warnings == []
    assert gateway.extract_calls == [(False, None)]
