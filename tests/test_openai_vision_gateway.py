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
    CropInspectionRequest,
    InspectionAction,
    InspectionDecision,
    PageDraft,
    PageInspection,
    PagePlan,
    RegionDraft,
    SchemaProposalWire,
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


def test_luna_draft_uses_deterministic_structured_vision_request(tmp_path: Path) -> None:
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
    assert "temperature" not in call
    assert call["reasoning"] == {"effort": "medium"}
    assert call["store"] is False
    assert call["text_format"] is PageDraft
    assert call["max_output_tokens"] == 128_000
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
        match=(
            "page_draft.*page 1.*gpt-5.6-luna.*max_output_tokens"
            ".*req-incomplete"
        ),
    ):
        gateway.draft_page(_page(tmp_path / "page.png"))
    assert getattr(gateway, "input_tokens", None) == 7
    assert getattr(gateway, "output_tokens", None) == 3


def test_page_draft_schema_has_no_free_form_model_output() -> None:
    schema = to_strict_json_schema(PageDraft)
    region = schema["$defs"]["RegionDraft"]

    assert "attributes" not in region["properties"]
    assert "table_cells" in region["properties"]
    assert "atoms" in region["properties"]
    assert region["additionalProperties"] is False
    assert all(
        value is not True
        for value in _additional_properties_values(schema)
    )


def _additional_properties_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "additionalProperties":
                yield child
            yield from _additional_properties_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _additional_properties_values(child)


def test_luna_inspection_returns_fail_closed_decisions(tmp_path: Path) -> None:
    parsed = PageInspection(
        decisions=[
            InspectionDecision(
                region_id="region-1",
                action=InspectionAction.REJECT,
                evidence_refs=["page:1"],
                reason="Not visible",
            )
        ]
    )
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )
    draft = PageDraft(
        regions=[
            RegionDraft(type="paragraph", reading_order=0, text="Certain context"),
            RegionDraft(type="paragraph", reading_order=1, text="Candidate"),
        ]
    )

    inspection = gateway.inspect_page(
        _page(tmp_path / "page.png"),
        draft,
        region_ids=["region-0", "region-1"],
        target_region_ids=["region-1"],
    )

    call = responses.calls[0]
    assert inspection.decisions[0].action is InspectionAction.REJECT
    assert call["model"] == "gpt-5.6-luna"
    assert "temperature" not in call
    assert call["reasoning"] == {"effort": "medium"}
    assert call["text_format"] is PageInspection
    prompt = call["input"][0]["content"]
    assert "complete corrected region" in prompt
    assert "type, text, bounding box, reading order" in prompt
    assert "generic synonyms" in prompt
    assert "Do not accept a figure" in prompt
    assert "nearby heading or label that identifies its subject" in prompt
    assert "omitted visible region" in prompt
    assert "ordered_region_ids" in prompt
    manifest = call["input"][1]["content"][0]["text"]
    assert '"region_id": "region-0"' in manifest
    assert '"target_region_ids": ["region-1"]' in manifest
    _assert_no_prompt_cache(call)


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
    images = [item for item in call["input"][1]["content"] if item["type"] == "input_image"]
    assert len(inspection.decisions) == 2
    assert len(images) == 2
    assert all(image["detail"] == "original" for image in images)
    assert call["model"] == "gpt-5.6-luna"
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


def test_quality_crop_inspection_uses_terra_and_records_page_targets(
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
    assert call["model"] == "gpt-5.6-terra"
    assert "Never invent" in prompt
    assert "identifiers, dates, measurements, phone numbers, emails, URLs" in prompt
    assert "NPIs, MRNs, dates, IDs, DOBs, tax IDs, policy numbers, and account numbers" in prompt
    assert "exact glyphs, punctuation, separators, and leading zeros" in prompt
    assert "Do not infer unclear digits" in prompt
    assert "illegible or inconclusive" in prompt
    assert "geometry_only=true only when rejection is exclusively caused" in prompt
    assert "false for semantic, unsupported, ambiguous, or mixed failures" in prompt
    assert gateway.usage.calls[0].agent == AgentRole.EVIDENCE_CRITIC.value
    assert gateway.trace[0].page == 7
    assert gateway.trace[0].target_ids == ["p7-b3"]


def test_manager_uses_luna_medium_and_returns_subagent_plan(tmp_path: Path) -> None:
    responses = RecordingResponses(PagePlan(finish=True, summary="Draft is grounded"))
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )
    draft = PageDraft(
        regions=[RegionDraft(type="paragraph", reading_order=0, text="Visible")]
    )

    plan = gateway.plan_page(
        _page(tmp_path / "page.png"),
        draft,
        region_ids=["p1-b1"],
        target_region_ids=["p1-b1"],
        repair_round=1,
    )

    call = responses.calls[0]
    assert plan.finish is True
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["text_format"] is PagePlan
    assert gateway.usage.calls[0].agent == "document_manager"


def test_inspection_escalates_to_terra_only_when_requested(tmp_path: Path) -> None:
    responses = RecordingResponses(PageInspection())
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )
    draft = PageDraft(
        regions=[RegionDraft(type="table", reading_order=0, text="A | B")]
    )

    gateway.inspect_page(
        _page(tmp_path / "page.png"),
        draft,
        region_ids=["p1-b1"],
        target_region_ids=["p1-b1"],
        agent_role=AgentRole.TABLE_FORM,
        use_terra=True,
    )

    call = responses.calls[0]
    assert call["model"] == "gpt-5.6-terra"
    assert call["reasoning"] == {"effort": "medium"}
    assert gateway.usage.calls[0].agent == AgentRole.TABLE_FORM.value


def test_schema_architect_uses_luna_medium() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": ["string", "null"]}},
        "required": ["name"],
        "additionalProperties": False,
    }
    responses = RecordingResponses(
        SchemaProposalWire(schema_text=json.dumps(schema))
    )
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


def test_dynamic_extractor_uses_user_schema_and_optional_terra() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": ["string", "null"]}},
        "required": ["name"],
        "additionalProperties": False,
    }
    payload = {
        "data": {"name": "Ada"},
        "evidence": [
            {"pointer": "/name", "block_ids": ["p1-b1"], "atom_ids": []}
        ],
    }
    responses = RecordingCreateResponses(payload)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    result = gateway.extract_document(
        {"markdown": "Name: Ada", "document": {"pages": []}},
        schema,
        use_terra=True,
        issues=["/name: missing evidence"],
    )

    call = responses.calls[0]
    assert result == payload
    assert call["model"] == "gpt-5.6-terra"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["text"]["format"]["schema"]["properties"]["data"] == schema
    assert call["text"]["format"]["strict"] is True
    assert call["store"] is False
    assert gateway.usage.calls[0].agent == "extraction_critic"
