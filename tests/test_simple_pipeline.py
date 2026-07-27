import json

import pymupdf

from grounded_docparse.config import ParserConfig
from grounded_docparse.models import (
    AgentDelegation,
    AgentRole,
    InspectionAction,
    InspectionDecision,
    InspectionRegionAddition,
    NodeType,
    PageDraft,
    PageInspection,
    PagePlan,
    RegionDraft,
    VerificationState,
)
from grounded_docparse.pipeline import DocumentParser


class AcceptingGateway:
    inspected_region_ids = None
    input_tokens = 23
    output_tokens = 7

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.HEADING,
                    text="Public notice",
                    reading_order=0,
                    heading_level=1,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                ),
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Visible body",
                    reading_order=1,
                    bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.5},
                ),
            ]
        )

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        self.inspected_region_ids = targets
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=region_id,
                    action=InspectionAction.ACCEPT,
                    evidence_refs=["page:1"],
                )
                for region_id in targets
            ]
        )

    def inspect_crops(self, *_args, **_kwargs):
        raise AssertionError("crop inspection was not requested")


def test_parser_builds_verified_nested_document(simple_pdf: bytes) -> None:
    parser = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: AcceptingGateway(),
    )

    result = parser.parse(simple_pdf, "notice.pdf")

    heading = result.document.pages[0].blocks[0]
    assert heading.text == "Public notice"
    assert heading.verification is VerificationState.VERIFIED
    assert heading.children[0].text == "Visible body"
    assert heading.children[0].section_path == ["Public notice"]
    assert "# Public notice" in result.markdown
    payload = json.loads(result.json)
    assert payload["schema_version"] == "2.0.0"
    assert payload["metadata"]["source_name"] == "notice.pdf"
    assert payload["metadata"]["usage"]["input_tokens"] == 23
    assert json.loads(result.legacy_json)["schema_version"] == "1.3.0"
    assert getattr(result, "input_tokens", None) == 23
    assert getattr(result, "output_tokens", None) == 7
    annotated = getattr(result, "annotated_pdf", b"")
    assert annotated.startswith(b"%PDF")
    with pymupdf.open(stream=annotated, filetype="pdf") as rendered:
        assert len(rendered[0].get_drawings()) == 2


def _procedure_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 90), "1. Open the cold water tap.", fontsize=11)
    page.insert_text((72, 130), "2. Flame-sterilize the tap.", fontsize=11)
    page.insert_text((72, 170), "3. Fold and ship the form.", fontsize=11)
    data = document.tobytes()
    document.close()
    return data


class QualityRecoveryGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.quality_calls = []

    def draft_page(self, page):
        source = page.text_blocks[0]
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.LIST_ITEM,
                    text="Open the cold water tap.",
                    list_marker="1.",
                    reading_order=0,
                    confidence=0.99,
                    bbox=source.bbox.model_dump(exclude={"unit"}),
                )
            ]
        )

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.ACCEPT,
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ]
        )

    def inspect_crops(self, *_args, **_kwargs):
        raise AssertionError("ordinary crop inspection was not requested")


def test_parser_recovers_missing_native_list_steps_with_one_quality_pass() -> None:
    gateway = QualityRecoveryGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_procedure_pdf(), "procedures.pdf")

    assert result.markdown.count("1. Open the cold water tap.") == 1
    assert result.markdown.count("2. Flame-sterilize the tap.") == 1
    assert result.markdown.count("3. Fold and ship the form.") == 1
    assert len(gateway.quality_calls) == 1
    assert gateway.quality_calls[0][0] == 1
    assert len(gateway.quality_calls[0][1]) == 2


class UnresolvedCriticalGateway(QualityRecoveryGateway):
    def draft_page(self, page):
        source = page.text_blocks[0]
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.FORM_FIELD,
                    text="NPI: 1388746512",
                    reading_order=0,
                    confidence=0.99,
                    bbox=source.bbox.model_dump(exclude={"unit"}),
                )
            ]
        )

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=region_id,
                    action=InspectionAction.ACCEPT,
                    evidence_refs=["page:1"],
                )
                for region_id in targets
            ]
        )

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection()


def test_unresolved_critical_literal_remains_visible_with_review_warning() -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 90), "NPI: 1386746512", fontsize=11)
    data = document.tobytes()
    document.close()
    gateway = UnresolvedCriticalGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(data, "critical.pdf")

    assert "1388746512" in result.markdown
    assert result.document.pages[0].blocks[0].verification is VerificationState.NEEDS_REVIEW
    assert any("quality gate" in warning.casefold() for warning in result.document.warnings)
    assert '"status": "needs_review"' in result.json
    assert len(gateway.quality_calls) == 1


class AgenticRoutingGateway(AcceptingGateway):
    def __init__(self) -> None:
        self.plan_rounds = []
        self.delegations = []
        self.manager_feedback = []

    def plan_page(
        self,
        _page,
        _draft,
        *,
        region_ids,
        target_region_ids,
        repair_round,
        prior_inspections,
    ):
        self.plan_rounds.append(repair_round)
        self.manager_feedback.append(prior_inspections)
        if repair_round == 1:
            return PagePlan(
                delegations=[
                    AgentDelegation(
                        role=AgentRole.LAYOUT_TEXT,
                        target_region_ids=[region_ids[0]],
                        reason="Check heading hierarchy",
                    )
                ]
            )
        return PagePlan(
            delegations=[
                AgentDelegation(
                    role=AgentRole.EVIDENCE_CRITIC,
                    target_region_ids=[region_ids[1]],
                    use_terra=True,
                    reason="Luna left critical evidence unresolved",
                )
            ],
            finish=True,
        )

    def inspect_page(
        self,
        _page,
        _draft,
        *,
        region_ids,
        target_region_ids=None,
        agent_role=AgentRole.EVIDENCE_CRITIC,
        use_terra=False,
    ):
        targets = target_region_ids or region_ids
        self.delegations.append((agent_role, use_terra, list(targets)))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=region_id,
                    action=InspectionAction.ACCEPT,
                )
                for region_id in targets
            ]
        )


def test_manager_selects_subagents_with_two_bounded_repair_rounds(
    simple_pdf: bytes,
) -> None:
    gateway = AgenticRoutingGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert gateway.plan_rounds == [1, 2]
    assert gateway.manager_feedback[0] == []
    assert gateway.manager_feedback[1][0]["decisions"][0]["region_id"] == "p1-b1"
    assert gateway.delegations == [
        (AgentRole.LAYOUT_TEXT, False, ["p1-b1"]),
        (AgentRole.EVIDENCE_CRITIC, True, ["p1-b2"]),
    ]
    assert result.document.pages[0].blocks[0].verification is VerificationState.VERIFIED


class InvalidBoxGateway(AcceptingGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Ungrounded text",
                    reading_order=0,
                    bbox={"x0": 0.8, "y0": 0.1, "x1": 0.2, "y1": 0.3},
                )
            ]
        )


def test_invalid_grounding_cannot_be_verified(simple_pdf: bytes) -> None:
    parser = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: InvalidBoxGateway(),
    )

    result = parser.parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "Invalid bounding box"
    assert "Ungrounded text" in result.markdown
    assert "[UNRESOLVED" not in result.markdown


class MissingCorrectionGateway(AcceptingGateway):
    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.CORRECT,
                )
            ]
        )


def test_missing_correction_remains_unresolved(simple_pdf: bytes) -> None:
    parser = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: MissingCorrectionGateway(),
    )

    result = parser.parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "Correction did not include a region"


class CorrectingGateway(AcceptingGateway):
    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.CORRECT,
                    corrected_region=RegionDraft(
                        type=NodeType.HEADING,
                        text="Grounded correction",
                        reading_order=0,
                        heading_level=2,
                        bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                    ),
                )
            ]
        )


def test_grounded_correction_replaces_draft_text(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: CorrectingGateway(),
    ).parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.text == "Grounded correction"
    assert block.heading_level == 2
    assert block.verification is VerificationState.VERIFIED


class RejectingGateway(AcceptingGateway):
    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.REJECT,
                    reason="Not visible",
                )
            ]
        )


def test_explicit_rejection_is_suppressed_from_markdown(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: RejectingGateway()
    ).parse(simple_pdf, "notice.pdf")

    assert result.document.pages[0].blocks[0].verification is VerificationState.REJECTED
    assert "Public notice" not in result.markdown


class WrongCropRegionGateway(AcceptingGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Candidate",
                    reading_order=0,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.3},
                )
            ]
        )

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.INSPECT_CROP,
                )
            ]
        )

    def inspect_crops(self, *_args, **_kwargs):
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="wrong-region",
                    action=InspectionAction.ACCEPT,
                )
            ]
        )


def test_crop_decision_for_wrong_region_remains_unresolved(simple_pdf: bytes) -> None:
    parser = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: WrongCropRegionGateway(),
    )

    result = parser.parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "No crop verification decision"


class SelectiveGateway(AcceptingGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Certain paragraph",
                    confidence=0.95,
                    reading_order=0,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                ),
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Risky paragraph",
                    confidence=0.84,
                    reading_order=1,
                    bbox={"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
                ),
                RegionDraft(
                    type=NodeType.TABLE,
                    text="Certain but complex",
                    confidence=0.99,
                    reading_order=2,
                    bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.5},
                ),
            ]
        )


def test_only_low_confidence_and_complex_regions_are_sent_to_terra(simple_pdf: bytes) -> None:
    gateway = SelectiveGateway()
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert gateway.inspected_region_ids == ["p1-b2", "p1-b3"]
    assert "Certain paragraph" in result.markdown
    assert result.document.pages[0].blocks[0].verification is VerificationState.NOT_CHECKED


class CriticalLiteralGateway(AcceptingGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Ordinary high confidence prose.",
                    confidence=0.99,
                    reading_order=0,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                ),
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Call 573-751-3334 within 24 hours.",
                    confidence=0.99,
                    reading_order=1,
                    bbox={"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
                ),
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Sample volume MUST be 100–120 mL.",
                    confidence=0.99,
                    reading_order=2,
                    bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.4},
                ),
            ]
        )


def test_critical_literals_are_verified_even_at_high_confidence(simple_pdf: bytes) -> None:
    gateway = CriticalLiteralGateway()
    DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert gateway.inspected_region_ids == ["p1-b2", "p1-b3"]


class InvalidCorrectionGateway(CorrectingGateway):
    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.CORRECT,
                    corrected_region=RegionDraft(
                        type=NodeType.HEADING,
                        text="Unsupported correction",
                        reading_order=0,
                        bbox={"x0": 0.8, "y0": 0.1, "x1": 0.2, "y1": 0.2},
                    ),
                )
            ]
        )


def test_invalid_corrected_region_preserves_original_for_review(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: InvalidCorrectionGateway()
    ).parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.text == "Public notice"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "Correction contained an invalid bounding box"


class FailingVerifierGateway(SelectiveGateway):
    def inspect_page(self, *_args, **_kwargs):
        raise RuntimeError("provider unavailable")


def test_verifier_error_preserves_draft_text_as_needs_review(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: FailingVerifierGateway(),
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert "Risky paragraph" in result.markdown
    assert blocks[1].verification is VerificationState.NEEDS_REVIEW
    assert "provider unavailable" in blocks[1].verification_reason


class CropBatchGateway(AcceptingGateway):
    def __init__(self) -> None:
        self.crop_batches = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.SIGNATURE,
                    text=f"Signature {index}",
                    confidence=index / 100,
                    reading_order=index,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                )
                for index in range(10)
            ]
        )

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(region_id=region_id, action=InspectionAction.INSPECT_CROP)
                for region_id in targets
            ]
        )

    def inspect_crops(self, crops):
        self.crop_batches.append(crops)
        return PageInspection(
            decisions=[
                InspectionDecision(region_id=crop.region_id, action=InspectionAction.ACCEPT)
                for crop in crops
            ]
        )


def test_crop_requests_are_batched_once_and_limited_to_eight_highest_risk(
    simple_pdf: bytes,
) -> None:
    gateway = CropBatchGateway()
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert len(gateway.crop_batches) == 1
    assert [crop.region_id for crop in gateway.crop_batches[0]] == [
        f"p1-b{index}" for index in range(1, 9)
    ]
    overflow = result.document.pages[0].blocks[8:]
    assert [block.verification for block in overflow] == [
        VerificationState.NEEDS_REVIEW,
        VerificationState.NEEDS_REVIEW,
    ]
    assert all(
        block.verification_reason == "Crop inspection limit exceeded"
        for block in overflow
    )
    assert all(block.text in result.markdown for block in overflow)


def test_crop_render_error_preserves_draft_text(
    simple_pdf: bytes, monkeypatch,
) -> None:
    gateway = CropBatchGateway()

    def fail_crop(*_args, **_kwargs):
        raise RuntimeError("crop renderer unavailable")

    monkeypatch.setattr("grounded_docparse.pipeline.render_region_crop", fail_crop)
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert gateway.crop_batches == []
    assert all(block.verification is VerificationState.NEEDS_REVIEW for block in blocks)
    assert all(
        "crop renderer unavailable" in block.verification_reason
        for block in blocks[:8]
    )
    assert all(
        block.verification_reason == "Crop inspection limit exceeded"
        for block in blocks[8:]
    )
    assert all(block.text in result.markdown for block in blocks)


class FailingCropGateway(CropBatchGateway):
    def inspect_crops(self, crops):
        raise RuntimeError("crop provider unavailable")


def test_crop_verifier_error_preserves_draft_text(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: FailingCropGateway()
    ).parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "crop provider unavailable" in block.verification_reason
    assert "Signature 0" in result.markdown


class CoverageGateway(AcceptingGateway):
    def __init__(self) -> None:
        self.full_region_ids = []
        self.target_region_ids = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Certain introduction",
                    confidence=0.99,
                    reading_order=0,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                ),
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Risky instructions",
                    confidence=0.5,
                    reading_order=1,
                    bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.4},
                ),
            ]
        )

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        self.full_region_ids = region_ids
        self.target_region_ids = target_region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b2",
                    action=InspectionAction.ACCEPT,
                )
            ],
            additional_regions=[
                InspectionRegionAddition(
                    region_id="new-1",
                    region=RegionDraft(
                        type=NodeType.PARAGRAPH,
                        text="County: Enter the county name.",
                        confidence=0.98,
                        reading_order=2,
                        bbox={"x0": 0.1, "y0": 0.5, "x1": 0.9, "y1": 0.6},
                    ),
                )
            ],
            ordered_region_ids=["p1-b2", "new-1", "p1-b1"],
        )


def test_page_inspection_can_recover_missing_content_and_reorder_full_manifest(
    simple_pdf: bytes,
) -> None:
    gateway = CoverageGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert gateway.full_region_ids == ["p1-b1", "p1-b2"]
    assert gateway.target_region_ids == ["p1-b2"]
    assert [block.text for block in blocks] == [
        "Risky instructions",
        "County: Enter the county name.",
        "Certain introduction",
    ]
    assert blocks[1].id == "p1-b3"
    assert blocks[1].verification is VerificationState.VERIFIED
    assert blocks[1].citation.page == 1


class NormalizingGateway(AcceptingGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.HEADING,
                    text="No Paper Label:",
                    confidence=0.99,
                    reading_order=0,
                    heading_level=2,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                ),
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="No Paper Label:\nPeter Lys\u00adkowski",
                    confidence=0.99,
                    reading_order=1,
                    bbox={"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
                ),
                RegionDraft(
                    type=NodeType.LIST,
                    text="Routine – Routine – Regular monthly monitoring samples.",
                    confidence=0.99,
                    reading_order=2,
                    bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.4},
                ),
            ]
        )


def test_deterministic_cleanup_removes_soft_hyphens_and_exact_label_repetition(
    simple_pdf: bytes,
) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: NormalizingGateway()
    ).parse(simple_pdf, "notice.pdf")

    assert result.markdown.count("No Paper Label:") == 1
    assert "Peter Lyskowski" in result.markdown
    assert "Routine – Regular monthly monitoring samples." in result.markdown
    assert "Routine – Routine –" not in result.markdown
    assert "\u00ad" not in result.json


class ProactiveCropGateway(AcceptingGateway):
    def __init__(self) -> None:
        self.crop_batches = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.SIDEBAR,
                    text="Email: labwebl@health.mo.gov",
                    confidence=0.99,
                    reading_order=0,
                    bbox={"x0": 0.5, "y0": 0.6, "x1": 0.9, "y1": 0.8},
                ),
                RegionDraft(
                    type=NodeType.FIGURE,
                    figure_description="Generic bottle",
                    confidence=0.99,
                    reading_order=1,
                    bbox={"x0": 0.5, "y0": 0.2, "x1": 0.9, "y1": 0.5},
                ),
            ]
        )

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(region_id=region_id, action=InspectionAction.ACCEPT)
                for region_id in targets
            ],
            ordered_region_ids=["p1-b2", "p1-b1"],
        )

    def inspect_crops(self, crops):
        self.crop_batches.append(crops)
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b1",
                    action=InspectionAction.CORRECT,
                    corrected_region=RegionDraft(
                        type=NodeType.SIDEBAR,
                        text="Email: labweb1@health.mo.gov",
                        confidence=1,
                        reading_order=99,
                        bbox={"x0": 0.4, "y0": 0.5, "x1": 0.95, "y1": 0.9},
                    ),
                ),
                InspectionDecision(
                    region_id="p1-b2",
                    action=InspectionAction.CORRECT,
                    corrected_region=RegionDraft(
                        type=NodeType.FIGURE,
                        figure_description="Bottle with Max. fill line and Min. fill line labels.",
                        confidence=1,
                        reading_order=98,
                        bbox={"x0": 0.4, "y0": 0.1, "x1": 0.95, "y1": 0.6},
                    ),
                ),
            ]
        )


def test_accepted_visuals_are_crop_enriched_with_ambiguous_literals(
    simple_pdf: bytes,
) -> None:
    gateway = ProactiveCropGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert len(gateway.crop_batches) == 1
    assert [crop.region_id for crop in gateway.crop_batches[0]] == ["p1-b2", "p1-b1"]
    assert [block.id for block in result.document.pages[0].blocks] == ["p1-b2", "p1-b1"]
    assert [block.reading_order for block in result.document.pages[0].blocks] == [0, 1]
    assert "labweb1@health.mo.gov" in result.markdown
    assert "Bottle with Max. fill line and Min. fill line labels." in result.markdown


class ManyVisualsGateway(AcceptingGateway):
    def __init__(self) -> None:
        self.crop_batches = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.FIGURE,
                    figure_description=f"Generic visual {index}",
                    confidence=0.99,
                    reading_order=index,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                )
                for index in range(10)
            ]
        )

    def inspect_crops(self, crops):
        self.crop_batches.append(crops)
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.CORRECT,
                    corrected_region=crop.candidate_region.model_copy(
                        update={"figure_description": f"Detailed visual {crop.region_id}"}
                    ),
                )
                for crop in crops
            ]
        )


def test_all_visuals_are_crop_enriched_in_batches_of_eight(simple_pdf: bytes) -> None:
    gateway = ManyVisualsGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert [[crop.region_id for crop in batch] for batch in gateway.crop_batches] == [
        [f"p1-b{index}" for index in range(1, 9)],
        ["p1-b9", "p1-b10"],
    ]
    assert result.markdown.count("<figure>Detailed visual") == 10


class SecondVisualBatchFailsGateway(ManyVisualsGateway):
    def inspect_crops(self, crops):
        if self.crop_batches:
            self.crop_batches.append(crops)
            raise RuntimeError("second visual batch failed")
        return super().inspect_crops(crops)


def test_visual_crop_batch_failure_is_isolated(simple_pdf: bytes) -> None:
    gateway = SecondVisualBatchFailsGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert [block.verification for block in blocks[:8]] == [
        VerificationState.VERIFIED
    ] * 8
    assert all(block.figure_description.startswith("Detailed visual") for block in blocks[:8])
    assert [block.verification for block in blocks[8:]] == [
        VerificationState.NEEDS_REVIEW,
        VerificationState.NEEDS_REVIEW,
    ]
    assert all(
        "second visual batch failed" in block.verification_reason
        for block in blocks[8:]
    )


class ExtremeOrderGateway(AcceptingGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text=f"Block {index}",
                    confidence=0.5,
                    reading_order=index,
                    bbox={"x0": 0.1, "y0": index / 10, "x1": 0.9, "y1": (index + 1) / 10},
                )
                for index in range(8)
            ]
        )

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        targets = target_region_ids or region_ids
        return PageInspection(
            decisions=[
                InspectionDecision(region_id=region_id, action=InspectionAction.ACCEPT)
                for region_id in targets
            ],
            ordered_region_ids=list(reversed(region_ids)),
        )


def test_extreme_page_reordering_is_ignored_and_audited(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: ExtremeOrderGateway()
    ).parse(simple_pdf, "notice.pdf")

    assert [block.text for block in result.document.pages[0].blocks] == [
        f"Block {index}" for index in range(8)
    ]
    assert any("excessive block movement" in warning for warning in result.document.warnings)
