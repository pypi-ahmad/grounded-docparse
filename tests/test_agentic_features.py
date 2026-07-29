from __future__ import annotations

import json
from typing import ClassVar

from grounded_docparse.agentic import DocumentAgent
from grounded_docparse.models import (
    Block,
    ChatAnswerWire,
    ChatCitationWire,
    Document,
    DocumentClassification,
    ExtractedField,
    ExtractionResult,
    Page,
    ParseResult,
    RunUsage,
    TableOfContents,
    TocSection,
    VerificationState,
)
from grounded_docparse.render import render_agentic_document, render_combined_result


def _result(page_count: int = 3) -> ParseResult:
    pages = [
        Page(
            number=number,
            width=100,
            height=100,
            blocks=[
                Block(
                    id=f"p{number}-heading",
                    type="heading",
                    text=f"Heading {number}",
                    reading_order=0,
                    heading_level=1,
                    verification=VerificationState.VERIFIED,
                ),
                Block(
                    id=f"p{number}-text",
                    type="paragraph",
                    text=f"Document detail {number}",
                    reading_order=1,
                    verification=VerificationState.VERIFIED,
                ),
            ],
        )
        for number in range(1, page_count + 1)
    ]
    document = Document(
        source_name="document.pdf",
        source_sha256="a" * 64,
        pages=pages,
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


class FeatureGateway:
    instances: ClassVar[list[FeatureGateway]] = []

    def __init__(self, _config) -> None:
        self.usage = RunUsage()
        self.trace = []
        self.classify_calls = []
        self.toc_calls = []
        self.chat_calls = []
        self.__class__.instances.append(self)

    def classify_document(self, markdown, layout):
        self.classify_calls.append((markdown, layout))
        return DocumentClassification(
            primary_type="Report",
            confidence=0.9,
            secondary_types=[],
            reasoning="Report structure",
        )

    def generate_toc(self, markdown, layout):
        self.toc_calls.append((markdown, layout))
        first = layout[0]
        return TableOfContents(
            sections=[
                TocSection(
                    title=first["text"],
                    level=1,
                    page=first["page"],
                    element_id=first["id"],
                )
            ]
        )

    def chat_document(self, question, markdown, layout, history):
        self.chat_calls.append((question, markdown, layout, history))
        return ChatAnswerWire(
            answer="The first detail is present.",
            citations=[ChatCitationWire(element_id="p1-text")],
        )


def test_agentic_context_contains_compact_text_layout() -> None:
    contexts = DocumentAgent.prepare(_result()).contexts

    assert [record["id"] for record in contexts[0].layout][:2] == [
        "p1-heading",
        "p1-text",
    ]
    assert contexts[0].layout[0] == {
        "id": "p1-heading",
        "type": "heading",
        "page": 1,
        "order": 1,
        "text": "Heading 1",
    }
    assert "bbox" not in contexts[0].layout[0]


def test_prepared_context_is_reusable_across_agentic_calls() -> None:
    result = _result()
    agent = DocumentAgent(gateway_factory=FeatureGateway)
    prepared = agent.prepare(result)

    assert prepared.page_markdown[1].startswith("# Heading 1")
    assert prepared.contexts[0].layout[0]["id"] == "p1-heading"
    analysis = agent.analyze(result, prepared_context=prepared)
    answer = agent.chat(
        result,
        "What is the first detail?",
        [],
        prepared_context=prepared,
    )

    assert analysis.classification.primary_type == "Report"
    assert answer.sources[0].element_id == "p1-text"


def test_analysis_classifies_first_two_pages_and_builds_grounded_toc() -> None:
    FeatureGateway.instances.clear()
    analysis = DocumentAgent(gateway_factory=FeatureGateway).analyze(_result())

    assert analysis.classification.primary_type == "Report"
    assert analysis.toc.sections[0].element_id == "p1-heading"
    classifier = next(item for item in FeatureGateway.instances if item.classify_calls)
    markdown, layout = classifier.classify_calls[0]
    assert "Heading 1" in markdown and "Heading 2" in markdown
    assert "Heading 3" not in markdown
    assert {item["page"] for item in layout} == {1, 2}


def test_chat_maps_only_element_ids_to_grounded_citations() -> None:
    answer = DocumentAgent(gateway_factory=FeatureGateway).chat(
        _result(),
        "What is the first detail?",
        [{"role": "user", "content": "Earlier question"}],
    )

    assert answer.sources[0].element_id == "p1-text"
    assert answer.sources[0].page == 1
    assert answer.sources[0].text == "Document detail 1"
    assert answer.confidence == "low"


def test_combined_result_uses_additive_flat_v44_contract() -> None:
    result = _result()
    analysis = DocumentAgent(gateway_factory=FeatureGateway).analyze(result)
    extraction = ExtractionResult(
        data={"detail": "Document detail 1"},
        evidence={},
        json="{}",
        warnings=[],
        input_tokens=0,
        output_tokens=0,
        usage=RunUsage(),
        trace=[],
        fields={
            "detail": ExtractedField(
                value="Document detail 1",
                page=1,
                element_id="p1-text",
                bbox=(0.1, 0.1, 0.9, 0.2),
                confidence="high",
                source_text="Document detail 1",
            )
        },
    )

    payload = json.loads(render_combined_result(result, analysis, extraction))

    assert payload["schema_version"] == "4.4.0"
    assert payload["document_type"]["primary_type"] == "Report"
    assert payload["sections"][0]["element_id"] == "p1-heading"
    assert payload["extracted_fields"]["detail"]["element_id"] == "p1-text"
    assert payload["metadata"]["luna_recovery_time"] == 0
    assert payload["metadata"]["luna_agentic_time"] == 0
    assert payload["metadata"]["luna_time"] == 0
    assert "annotated_pdf" not in payload
