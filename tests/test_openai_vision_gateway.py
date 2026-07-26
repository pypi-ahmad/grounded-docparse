from pathlib import Path
from types import SimpleNamespace

from openai.lib._pydantic import to_strict_json_schema

from grounded_docparse.config import ParserConfig
from grounded_docparse.gateways import OpenAIDocumentGateway
from grounded_docparse.ingest import PageEvidence
from grounded_docparse.models import (
    InspectionAction,
    InspectionDecision,
    PageDraft,
    PageInspection,
    RegionDraft,
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


def _page(path: Path) -> PageEvidence:
    path.write_bytes(b"image")
    return PageEvidence(
        number=1,
        width=612,
        height=792,
        dpi=200,
        image_path=path,
        ocr_image_path=path,
        scanned=True,
    )


def test_luna_draft_uses_deterministic_structured_vision_request(tmp_path: Path) -> None:
    parsed = PageDraft(
        regions=[RegionDraft(type="Paragraph", reading_order=0, text="Visible")]
    )
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )

    draft, run = gateway.draft_page(_page(tmp_path / "page.png"))

    call = responses.calls[0]
    assert draft.regions[0].text == "Visible"
    assert call["model"] == "gpt-5.6-luna"
    assert call["temperature"] == 0.0
    assert call["reasoning"] == {"effort": "low"}
    assert call["store"] is False
    assert call["text_format"] is PageDraft
    assert call["prompt_cache_options"] == {"mode": "explicit", "ttl": "24h"}
    assert str(call["prompt_cache_key"]).startswith("docparse:luna-draft:")
    assert run.stage == "page_draft"


def test_page_draft_schema_has_no_free_form_model_output() -> None:
    schema = to_strict_json_schema(PageDraft)
    region = schema["$defs"]["RegionDraft"]

    assert "attributes" not in region["properties"]
    assert "table_cells" in region["properties"]
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


def test_terra_inspection_returns_fail_closed_decisions(tmp_path: Path) -> None:
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
        regions=[RegionDraft(type="Paragraph", reading_order=0, text="Candidate")]
    )

    inspection, run = gateway.inspect_page(
        _page(tmp_path / "page.png"), draft, region_ids=["region-1"]
    )

    call = responses.calls[0]
    assert inspection.decisions[0].action is InspectionAction.REJECT
    assert call["model"] == "gpt-5.6-terra"
    assert call["temperature"] == 0.0
    assert call["reasoning"] == {"effort": "low"}
    assert call["text_format"] is PageInspection
    assert run.stage == "page_inspection"


def test_terra_crop_inspection_uses_original_detail(tmp_path: Path) -> None:
    parsed = InspectionDecision(
        region_id="region-1",
        action=InspectionAction.ACCEPT,
        evidence_refs=["assets/inspection/region-1.png"],
    )
    responses = RecordingResponses(parsed)
    gateway = OpenAIDocumentGateway(
        ParserConfig(), client=SimpleNamespace(responses=responses)
    )
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"crop")

    decision, run = gateway.inspect_crop(
        crop,
        region_id="region-1",
        candidate_text="Visible text",
        evidence_ref="assets/inspection/region-1.png",
        attempt=1,
    )

    call = responses.calls[0]
    image = call["input"][1]["content"][1]
    assert decision.action is InspectionAction.ACCEPT
    assert image["detail"] == "original"
    assert call["model"] == "gpt-5.6-terra"
    assert call["text_format"] is InspectionDecision
    assert run.stage == "crop_inspection"
