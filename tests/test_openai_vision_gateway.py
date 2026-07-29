import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.lib._pydantic import to_strict_json_schema

from grounded_docparse.config import ParserConfig
from grounded_docparse.gateways import OpenAIDocumentGateway
from grounded_docparse.ingest import PageEvidence
from grounded_docparse.models import (
    AgentRole,
    ChatAnswerWire,
    CropInspectionRequest,
    DocumentClassification,
    InspectionAction,
    InspectionDecision,
    MarkdownPresentationPlan,
    PageDraft,
    PageInspection,
    PagePresentationPlan,
    PresentationDirective,
    RegionDraft,
    SchemaProposalWire,
    SpanRepairAction,
    SpanRepairDecision,
    SpanRepairInspection,
    SpanRepairRequest,
    SpanRepairTarget,
    TableOfContents,
)


class RecordingResponses:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_parsed=self.parsed,
            output=[],
            usage=SimpleNamespace(input_tokens=10, output_tokens=4),
            id="response-1",
            model=kwargs["model"],
        )


class RecordingCreateResponses(RecordingResponses):
    def __init__(self, payload: dict) -> None:
        super().__init__(PageDraft())
        self.payload = payload

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(self.payload),
            output=[],
            usage=SimpleNamespace(input_tokens=14, output_tokens=6),
            id="response-2",
            model=kwargs["model"],
        )


class RepairingResponses(RecordingResponses):
    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("response failed schema validation")
        return SimpleNamespace(
            output_parsed=self.parsed,
            output=[],
            usage=SimpleNamespace(input_tokens=10, output_tokens=4),
            id="response-repaired",
            model=kwargs["model"],
        )


class RepairingCreateResponses(RecordingResponses):
    def __init__(self, payload: dict) -> None:
        super().__init__(PageDraft())
        self.payload = payload

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        output = "not json" if len(self.calls) == 1 else json.dumps(self.payload)
        return SimpleNamespace(
            output_text=output,
            output=[],
            usage=SimpleNamespace(input_tokens=14, output_tokens=6),
            id="response-repaired",
            model=kwargs["model"],
        )


def _assert_no_prompt_cache(value: object) -> None:
    if isinstance(value, dict):
        assert "prompt_cache_key" not in value
        assert "prompt_cache_options" not in value
        assert "prompt_cache_breakpoint" not in value
        for child in value.values():
            _assert_no_prompt_cache(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_prompt_cache(child)


def _assert_no_image_payload(value: object) -> None:
    if isinstance(value, dict):
        assert "image_url" not in value
        assert value.get("type") != "input_image"
        for child in value.values():
            _assert_no_image_payload(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_image_payload(child)
    elif isinstance(value, str):
        assert "data:image/" not in value


def test_markdown_refinement_is_text_only() -> None:
    parsed = MarkdownPresentationPlan(
        pages=[
            PagePresentationPlan(
                page=1,
                elements=[PresentationDirective(element_id="p1-b1")],
            )
        ]
    )
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    result = gateway.refine_markdown(
        "<!-- element:p1-b1 -->\nVisible\n",
        [{"id": "p1-b1", "page": 1, "type": "paragraph"}],
    )

    assert result == parsed
    assert responses.calls[0]["model"] == "gpt-5.6-luna"
    _assert_no_image_payload(responses.calls[0])


@pytest.mark.parametrize(
    ("method", "parsed"),
    [
        (
            "classify_document",
            DocumentClassification(
                primary_type="Report",
                confidence=0.9,
                secondary_types=[],
                reasoning="Report structure",
            ),
        ),
        ("generate_toc", TableOfContents()),
    ],
)
def test_agentic_analysis_requests_are_structured_text_only(method, parsed) -> None:
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    getattr(gateway, method)(
        "Document text",
        [{"id": "p1-b1", "type": "paragraph", "page": 1, "order": 1, "text": "Document text"}],
    )

    call = responses.calls[0]
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "medium"}
    assert gateway.trace[0].reasoning_effort == "medium"
    assert call["store"] is False
    assert "layout_tree" in json.loads(call["input"][1]["content"])
    assert gateway.trace[0].prompt_version == "2026-07-29.4"
    _assert_no_image_payload(call)


def test_document_chat_request_is_structured_and_text_only() -> None:
    responses = RecordingResponses(ChatAnswerWire(answer="Grounded answer"))
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    gateway.chat_document(
        "Question?",
        "Document text",
        [{"id": "p1-b1", "type": "paragraph", "page": 1, "order": 1, "text": "Document text"}],
        [{"role": "user", "content": "Earlier"}],
    )

    call = responses.calls[0]
    assert call["reasoning"] == {"effort": "medium"}
    assert gateway.trace[0].reasoning_effort == "medium"
    assert call["store"] is False
    _assert_no_image_payload(call)


def test_structured_agentic_request_repairs_schema_failure_once() -> None:
    parsed = DocumentClassification(
        primary_type="Report",
        confidence=0.9,
        secondary_types=[],
        reasoning="Report structure",
    )
    responses = RepairingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    assert gateway.classify_document("Text", []).primary_type == "Report"
    assert len(responses.calls) == 2
    assert [event.status for event in gateway.trace] == [
        "schema_invalid",
        "completed",
    ]
    repair_prompt = responses.calls[1]["input"][0]["content"]
    assert "previous response" in repair_prompt.casefold()


def _page(path: Path) -> PageEvidence:
    path.write_bytes(b"image")
    return PageEvidence(
        number=1,
        width=612,
        height=792,
        dpi=200,
        image_path=path,
        scanned=True,
    )


def test_luna_draft_uses_deterministic_structured_vision_request(
    tmp_path: Path,
) -> None:
    parsed = PageDraft(
        regions=[RegionDraft(type="paragraph", reading_order=0, text="Visible")]
    )
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    draft = gateway.draft_page(_page(tmp_path / "page.png"))

    call = responses.calls[0]
    assert draft.regions[0].text == "Visible"
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "high"}
    assert "temperature" not in call
    assert gateway.trace[0].reasoning_effort == "high"
    assert call["store"] is False
    assert call["text_format"] is PageDraft
    assert call["max_output_tokens"] == 128_000
    assert call["input"][1]["content"][0]["detail"] == "original"
    _assert_no_prompt_cache(call)
    prompt = call["input"][0]["content"]
    assert "semantic reading order" in prompt
    assert "signatures" in prompt and "captions" in prompt
    assert "form.label" in prompt and "checkbox_group" in prompt
    assert "Join visual line wraps" in prompt
    assert "Do not correct spelling" in prompt
    assert "exact visible terminology" in prompt
    assert "one region per visible form field" in prompt
    assert "form.hint" in prompt
    assert "Form labels are not headings" in prompt
    assert "typographically distinct" in prompt
    assert "immediately beside its related procedure" in prompt


def test_gateway_accumulates_usage_across_requests(tmp_path: Path) -> None:
    responses = RecordingResponses(PageDraft())
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )
    page = _page(tmp_path / "page.png")

    gateway.draft_page(page)
    gateway.draft_page(page)

    assert getattr(gateway, "input_tokens", None) == 20
    assert getattr(gateway, "output_tokens", None) == 8


def test_incomplete_draft_reports_provider_context_before_schema_validation(
    tmp_path: Path,
) -> None:
    class IncompleteRawResponse:
        content = (
            b'{"status":"incomplete","incomplete_details":{"reason":"max_output_tokens"},'
            b'"usage":{"input_tokens":7,"output_tokens":3}}'
        )
        request_id = "req-incomplete"
        status_code = 200

        def parse(self) -> object:
            PageDraft.model_validate_json("{")
            raise AssertionError("unreachable")

    class RawResponses:
        with_raw_response: object

        def __init__(self) -> None:
            self.with_raw_response = self

        def parse(self, **_kwargs: object) -> object:
            return IncompleteRawResponse()

    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=RawResponses())
    )

    with pytest.raises(
        RuntimeError,
        match=("page_draft.*page 1.*gpt-5.6-luna.*max_output_tokens.*req-incomplete"),
    ):
        gateway.draft_page(_page(tmp_path / "page.png"))
    assert getattr(gateway, "input_tokens", None) == 7
    assert getattr(gateway, "output_tokens", None) == 3
    assert gateway.runtime.diagnostics().input_tokens == 7
    assert gateway.runtime.diagnostics().output_tokens == 3


def test_page_draft_schema_has_no_free_form_model_output() -> None:
    schema = to_strict_json_schema(PageDraft)
    region = schema["$defs"]["RegionDraft"]

    assert "attributes" not in region["properties"]
    assert "table_cells" in region["properties"]
    assert "atoms" in region["properties"]
    assert region["additionalProperties"] is False
    assert all(value is not True for value in _additional_properties_values(schema))


def _additional_properties_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "additionalProperties":
                yield child
            yield from _additional_properties_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _additional_properties_values(child)


def test_luna_crop_inspection_batches_images_in_one_request(tmp_path: Path) -> None:
    parsed = PageInspection(
        decisions=[
            InspectionDecision(
                region_id=f"region-{index}",
                action=InspectionAction.ACCEPT,
                evidence_refs=[f"page:1:region-{index}"],
            )
            for index in (1, 2)
        ]
    )
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )
    crops = []
    for index in (1, 2):
        crop = tmp_path / f"crop-{index}.png"
        crop.write_bytes(b"crop")
        crops.append(
            CropInspectionRequest(
                crop_path=str(crop),
                region_id=f"region-{index}",
                candidate_region=RegionDraft(
                    type="paragraph",
                    reading_order=index,
                    text=f"Visible text {index}",
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                ),
                evidence_ref=f"page:1:region-{index}",
            )
        )

    inspection = gateway.inspect_crops(crops)

    call = responses.calls[0]
    images = [
        item for item in call["input"][1]["content"] if item["type"] == "input_image"
    ]
    assert len(inspection.decisions) == 2
    assert len(images) == 2
    assert all(image["detail"] == "original" for image in images)
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "high"}
    assert call["input"][1]["content"][1]["detail"] == "original"
    assert "temperature" not in call
    assert call["text_format"] is PageInspection
    prompt = call["input"][0]["content"]
    assert "spatial relationships" in prompt
    assert "arrows" in prompt and "numbered" in prompt
    assert "barcode" in prompt and "do not infer" in prompt
    assert "complete figure_description" in prompt
    assert "Do not repeat literal text already captured" in prompt
    assert "75 words" in prompt
    assert (
        "phone numbers, NPIs, MRNs, dates, IDs, DOBs, tax IDs, policy numbers, "
        "and account numbers" in prompt
    )
    assert "exact glyphs, punctuation, separators, and leading zeros" in prompt
    assert "Do not infer unclear digits" in prompt
    assert "illegible or inconclusive" in prompt
    assert "geometry_only=true only when rejection is exclusively caused" in prompt
    assert "false for semantic, unsupported, ambiguous, or mixed failures" in prompt
    manifest = call["input"][1]["content"][0]["text"]
    assert '"candidate_region"' in manifest
    _assert_no_prompt_cache(call)


def test_quality_crop_inspection_uses_luna_and_records_page_targets(
    tmp_path: Path,
) -> None:
    responses = RecordingResponses(PageInspection())
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )
    crop = tmp_path / "quality.png"
    crop.write_bytes(b"crop")
    request = CropInspectionRequest(
        crop_path=str(crop),
        region_id="p7-b3",
        candidate_region=RegionDraft(
            type="table",
            reading_order=2,
            text="Diabetes E11.9",
            bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.4},
        ),
        evidence_ref="page:7:p7-b3:quality",
    )

    gateway.inspect_quality_crops([request], page_number=7)

    call = responses.calls[0]
    prompt = call["input"][0]["content"]
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "high"}
    assert call["input"][1]["content"][1]["detail"] == "original"
    assert "Never invent" in prompt
    assert "identifiers, dates, measurements, phone numbers, emails, URLs" in prompt
    assert (
        "For critical literals—phone numbers, NPIs, MRNs, dates, IDs, DOBs, tax IDs, "
        "policy numbers, and account numbers—preserve exact glyphs, punctuation, "
        "separators, and leading zeros" in prompt
    )
    assert "Do not infer unclear digits" in prompt
    assert "illegible or inconclusive" in prompt
    assert "geometry_only=true only when rejection is exclusively caused" in prompt
    assert "false for semantic, unsupported, ambiguous, or mixed failures" in prompt
    assert gateway.usage.calls[0].agent == AgentRole.EVIDENCE_CRITIC.value
    assert gateway.trace[0].page == 7
    assert gateway.trace[0].target_ids == ["p7-b3"]


def test_schema_architect_uses_luna_medium() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": ["string", "null"]}},
        "required": ["name"],
        "additionalProperties": False,
    }
    responses = RecordingResponses(SchemaProposalWire(schema_text=json.dumps(schema)))
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    proposal = gateway.propose_schema(
        "Extract the name",
        {"markdown": "Name: Ada"},
    )

    call = responses.calls[0]
    assert json.loads(proposal.schema_text) == schema
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "medium"}
    assert gateway.usage.calls[0].agent == "schema_architect"


def test_dynamic_extractor_uses_user_schema_and_luna_repair() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": ["string", "null"]}},
        "required": ["name"],
        "additionalProperties": False,
    }
    payload = {
        "data": {"name": "Ada"},
        "evidence": [{"pointer": "/name", "block_ids": ["p1-b1"], "atom_ids": []}],
    }
    responses = RecordingCreateResponses(payload)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    result = gateway.extract_document(
        {"markdown": "Name: Ada", "document": {"pages": []}},
        schema,
        repair=True,
        issues=["/name: missing evidence"],
    )

    call = responses.calls[0]
    assert result == payload
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["text"]["format"]["schema"]["properties"]["data"] == schema
    assert call["text"]["format"]["strict"] is True
    assert call["store"] is False
    assert gateway.usage.calls[0].agent == "extraction_critic"


def test_dynamic_extractor_repairs_invalid_json_once() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": ["string", "null"]}},
        "required": ["name"],
        "additionalProperties": False,
    }
    payload = {"data": {"name": None}, "evidence": []}
    responses = RepairingCreateResponses(payload)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    assert gateway.extract_document({}, schema) == payload
    assert len(responses.calls) == 2
    assert gateway.trace[0].status == "schema_invalid"
    assert gateway.trace[1].prompt_version == "2026-07-29.4"


def test_targeted_span_repair_sends_only_literal_context_and_crop(
    tmp_path: Path,
) -> None:
    crop = tmp_path / "span.png"
    crop.write_bytes(b"crop")
    target = SpanRepairTarget(
        target_id="p1-b1:atom:0:0",
        region_id="p1-b1",
        owner_kind="atom",
        owner_index=0,
        start=5,
        end=6,
        text="l",
        context_before="Acct ",
        context_after="23",
        confidence=0.4,
        source="gpt-5.6-luna",
        bbox={"x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2},
        evidence_ref="page:1:p1-b1:atom:0:0",
    )
    parsed = SpanRepairInspection(
        decisions=[
            SpanRepairDecision(
                target_id=target.target_id,
                action=SpanRepairAction.REPLACE,
                replacement_text="1",
                confidence=0.99,
                evidence_ref=target.evidence_ref,
            )
        ]
    )
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    result = gateway.repair_spans(
        [SpanRepairRequest(crop_path=str(crop), target=target)],
        page_number=1,
    )

    call = responses.calls[0]
    manifest = json.loads(call["input"][1]["content"][0]["text"])
    assert result.decisions[0].replacement_text == "1"
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "high"}
    assert call["text_format"] is SpanRepairInspection
    assert manifest[0]["text"] == "l"
    assert manifest[0]["context_before"] == "Acct "
    assert "candidate_region" not in manifest[0]
    assert len(call["input"][1]["content"]) == 2
    assert call["input"][1]["content"][1]["detail"] == "original"
