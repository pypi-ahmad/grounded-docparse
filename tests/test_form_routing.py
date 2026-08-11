from __future__ import annotations

import json
from typing import ClassVar

from grounded_docparse.agentic import DocumentAgent
from grounded_docparse.models import (
    Block,
    ClassifierCategory,
    ClassifierProfile,
    Document,
    ExtractedField,
    ExtractionResult,
    FormSegmentationWire,
    Page,
    ParseResult,
    RunUsage,
    VerificationState,
)
from grounded_docparse.render import render_agentic_document, render_combined_result


def _result() -> ParseResult:
    document = Document(
        source_name="fax.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=number,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id=f"p{number}-form",
                        type="paragraph",
                        text="New authorization" if number == 1 else "Medical records",
                        reading_order=0,
                        verification=VerificationState.VERIFIED,
                    )
                ],
            )
            for number in (1, 2)
        ],
    )
    rendered = render_agentic_document(document)
    return ParseResult(
        document=document,
        markdown=rendered.markdown,
        base_markdown=rendered.markdown,
        json=rendered.json,
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"",
    )


def _profile() -> ClassifierProfile:
    return ClassifierProfile(
        name="Medical fax routing",
        categories=[
            ClassifierCategory(
                key="newauth",
                description="Initial authorization request",
                extract=True,
                schema_name="New Authorization",
            ),
            ClassifierCategory(
                key="medical_records",
                description="Medical records only",
            ),
        ],
    )


class RoutingGateway:
    instances: ClassVar[list[RoutingGateway]] = []

    def __init__(self, _config) -> None:
        self.calls = []
        self.usage = RunUsage()
        self.trace = []
        self.__class__.instances.append(self)

    def classify_forms(self, markdown, layout, profile, *, issues=None):
        self.calls.append((markdown, layout, profile, issues))
        return FormSegmentationWire.model_validate(
            {
                "segments": [
                    {
                        "start_page": 1,
                        "end_page": 1,
                        "category": "newauth",
                        "confidence": 0.91,
                        "reasoning": "New request heading",
                        "evidence_element_ids": ["p1-form"],
                    },
                    {
                        "start_page": 2,
                        "end_page": 2,
                        "category": "other",
                        "confidence": 0.7,
                        "reasoning": "No selected category",
                        "evidence_element_ids": [],
                    },
                ]
            }
        )


def test_custom_classification_gates_low_confidence_and_assigns_schema() -> None:
    RoutingGateway.instances.clear()
    classified = DocumentAgent(gateway_factory=RoutingGateway).classify_forms(
        _result(), _profile()
    )

    assert classified.segments[0].approved is True
    assert classified.segments[0].eligible is True
    assert classified.segments[0].schema_name == "New Authorization"
    assert classified.segments[1].approved is False
    assert classified.segments[1].eligible is False
    sent_profile = RoutingGateway.instances[0].calls[0][2]
    assert [item["key"] for item in sent_profile["categories"]] == [
        "newauth",
        "medical_records",
        "other",
    ]


def test_adjacent_same_category_forms_remain_separate_within_a_window() -> None:
    class SameCategoryGateway(RoutingGateway):
        def classify_forms(self, markdown, layout, profile, *, issues=None):
            del markdown, layout, profile, issues
            return FormSegmentationWire.model_validate(
                {
                    "segments": [
                        {
                            "start_page": 1,
                            "end_page": 1,
                            "category": "newauth",
                            "confidence": 0.9,
                            "evidence_element_ids": ["p1-form"],
                        },
                        {
                            "start_page": 2,
                            "end_page": 2,
                            "category": "newauth",
                            "confidence": 0.9,
                            "evidence_element_ids": ["p2-form"],
                        },
                    ]
                }
            )

    classified = DocumentAgent(gateway_factory=SameCategoryGateway).classify_forms(
        _result(), _profile()
    )

    assert [(item.start_page, item.end_page) for item in classified.segments] == [
        (1, 1),
        (2, 2),
    ]


def test_custom_classification_repairs_invalid_grounding_once() -> None:
    class RepairGateway(RoutingGateway):
        def classify_forms(self, markdown, layout, profile, *, issues=None):
            self.calls.append((markdown, layout, profile, issues))
            if issues is None:
                return FormSegmentationWire.model_validate(
                    {
                        "segments": [
                            {
                                "start_page": 1,
                                "end_page": 2,
                                "category": "unknown",
                                "confidence": 0.9,
                                "evidence_element_ids": ["missing"],
                            }
                        ]
                    }
                )
            return FormSegmentationWire.model_validate(
                {
                    "segments": [
                        {
                            "start_page": 1,
                            "end_page": 2,
                            "category": "newauth",
                            "confidence": 0.9,
                            "evidence_element_ids": ["p1-form"],
                        }
                    ]
                }
            )

    classified = DocumentAgent(gateway_factory=RepairGateway).classify_forms(
        _result(), _profile()
    )
    gateway = RepairGateway.instances[-1]

    assert len(gateway.calls) == 2
    assert gateway.calls[1][3]
    assert classified.segments[0].category == "newauth"


def test_routed_extraction_processes_only_approved_eligible_segments(monkeypatch) -> None:
    result = _result()
    classified = DocumentAgent(gateway_factory=RoutingGateway).classify_forms(
        result, _profile()
    )
    classified.segments[1].approved = True
    classified.segments[1].review_status = "user_confirmed"
    captured_pages = []

    def fake_extract(self, subset, schema, *, prepared_context=None):
        del self, schema, prepared_context
        captured_pages.append([page.number for page in subset.document.pages])
        field = ExtractedField(
            value="Jane Doe",
            page=1,
            element_id="p1-form",
            bbox=(0.1, 0.1, 0.9, 0.2),
            confidence="high",
            source_text="New authorization",
        )
        return ExtractionResult(
            data={"patient_name": "Jane Doe"},
            evidence={},
            json="{}",
            warnings=[],
            input_tokens=0,
            output_tokens=0,
            usage=RunUsage(),
            trace=[],
            fields={"patient_name": field},
        )

    monkeypatch.setattr(DocumentAgent, "extract", fake_extract)
    routed = DocumentAgent(gateway_factory=RoutingGateway).extract_forms(
        result,
        classified,
        {
            "New Authorization": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            }
        },
    )

    assert captured_pages == [[1]]
    assert len(routed.forms) == 1
    assert routed.forms[0].category == "newauth"
    assert json.loads(routed.json)["forms"][0]["data"] == {
        "patient_name": "Jane Doe"
    }

    combined = json.loads(
        render_combined_result(
            result,
            custom_classification=classified,
            routed_extraction=routed,
        )
    )
    assert combined["schema_version"] == "4.6.0"
    assert combined["custom_classification"]["profile"]["name"] == (
        "Medical fax routing"
    )
    assert combined["form_extractions"][0]["category"] == "newauth"
    assert combined["extracted_fields"] == {}
