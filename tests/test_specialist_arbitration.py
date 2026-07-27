import json

import pytest

from grounded_docparse.config import ParserConfig
from grounded_docparse.models import (
    AgentDelegation,
    AgentRole,
    InspectionAction,
    InspectionDecision,
    NodeType,
    PageDraft,
    PageInspection,
    PagePlan,
    RegionDraft,
    VerificationState,
)
from grounded_docparse.pipeline import DocumentParser


def _region(text: str, *, reading_order: int = 0) -> RegionDraft:
    top = 0.1 + reading_order * 0.15
    return RegionDraft(
        type=NodeType.PARAGRAPH,
        text=text,
        confidence=0.5,
        reading_order=reading_order,
        bbox={"x0": 0.1, "y0": top, "x1": 0.9, "y1": top + 0.1},
    )


def _correction(text: str) -> RegionDraft:
    return _region(text)


class SpecialistGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(
        self,
        layout: PageInspection,
        table: PageInspection,
        arbitration: PageInspection | Exception | None = None,
    ) -> None:
        self.layout = layout
        self.table = table
        self.arbitration = arbitration
        self.calls: list[tuple[AgentRole, bool, list[str]]] = []

    def draft_page(self, _page) -> PageDraft:
        return PageDraft(regions=[_region("Draft")])

    def plan_page(
        self,
        _page,
        _draft,
        *,
        region_ids,
        target_region_ids,
        repair_round,
        prior_inspections,
    ) -> PagePlan:
        del target_region_ids, repair_round, prior_inspections
        return PagePlan(
            delegations=[
                AgentDelegation(
                    role=AgentRole.LAYOUT_TEXT,
                    target_region_ids=[region_ids[0]],
                    reason="Review literal text",
                ),
                AgentDelegation(
                    role=AgentRole.TABLE_FORM,
                    target_region_ids=[region_ids[0]],
                    reason="Review structured content",
                ),
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
    ) -> PageInspection:
        targets = list(target_region_ids or region_ids)
        self.calls.append((agent_role, use_terra, targets))
        if agent_role is AgentRole.EVIDENCE_CRITIC and use_terra:
            if isinstance(self.arbitration, Exception):
                raise self.arbitration
            return self.arbitration or PageInspection()
        if agent_role is AgentRole.LAYOUT_TEXT:
            return self.layout
        return self.table

    def inspect_crops(self, *_args, **_kwargs):
        raise AssertionError("crop inspection was not requested")


def _parse(simple_pdf: bytes, gateway: object):
    return DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")


def test_inspection_confidence_is_additive_and_defaulted() -> None:
    decision = InspectionDecision(
        region_id="p1-b1",
        action=InspectionAction.ACCEPT,
    )

    assert decision.confidence == 0.5


def test_identical_specialist_corrections_reach_audited_consensus(
    simple_pdf: bytes,
) -> None:
    gateway = SpecialistGateway(
        PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b1",
                    action=InspectionAction.CORRECT,
                    corrected_region=_correction("Consensus"),
                    confidence=0.8,
                    reason="Literal text matches",
                )
            ]
        ),
        PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b1",
                    action=InspectionAction.CORRECT,
                    corrected_region=_correction("Consensus"),
                    confidence=0.9,
                    reason="Structure matches",
                )
            ]
        ),
    )

    result = _parse(simple_pdf, gateway)

    block = result.document.pages[0].blocks[0]
    audit = result.document.pages[0].specialist_audit
    assert block.text == "Consensus"
    assert block.verification is VerificationState.VERIFIED
    assert gateway.calls == [
        (AgentRole.LAYOUT_TEXT, False, ["p1-b1"]),
        (AgentRole.TABLE_FORM, False, ["p1-b1"]),
    ]
    assert [opinion.reviewer for opinion in audit.opinions] == [
        AgentRole.LAYOUT_TEXT.value,
        AgentRole.TABLE_FORM.value,
    ]
    assert [opinion.confidence for opinion in audit.opinions] == [0.8, 0.9]
    assert all(opinion.model == "gpt-5.6-luna" for opinion in audit.opinions)
    assert all(opinion.timestamp.tzinfo is not None for opinion in audit.opinions)
    assert [opinion.reasoning for opinion in audit.opinions] == [
        "Literal text matches",
        "Structure matches",
    ]
    assert audit.resolutions[0].outcome == "consensus"
    assert audit.resolutions[0].final_decision.action is InspectionAction.CORRECT
    payload = json.loads(result.json)
    persisted = payload["document"]["pages"][0]["specialist_audit"]
    assert len(persisted["opinions"]) == 2
    assert persisted["resolutions"][0]["outcome"] == "consensus"


def test_conflicting_specialists_are_resolved_by_terra_evidence_critic(
    simple_pdf: bytes,
) -> None:
    gateway = SpecialistGateway(
        PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b1",
                    action=InspectionAction.ACCEPT,
                    confidence=0.7,
                    reason="Draft appears literal",
                )
            ]
        ),
        PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b1",
                    action=InspectionAction.REJECT,
                    confidence=0.6,
                    reason="Draft is unsupported",
                )
            ]
        ),
        PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b1",
                    action=InspectionAction.CORRECT,
                    corrected_region=_correction("Terra resolution"),
                    confidence=0.95,
                    reason="Source image supports this literal",
                )
            ]
        ),
    )

    result = _parse(simple_pdf, gateway)

    block = result.document.pages[0].blocks[0]
    audit = result.document.pages[0].specialist_audit
    assert block.text == "Terra resolution"
    assert block.verification is VerificationState.VERIFIED
    assert gateway.calls[-1] == (
        AgentRole.EVIDENCE_CRITIC,
        True,
        ["p1-b1"],
    )
    assert [opinion.reviewer for opinion in audit.opinions] == [
        AgentRole.LAYOUT_TEXT.value,
        AgentRole.TABLE_FORM.value,
        AgentRole.EVIDENCE_CRITIC.value,
    ]
    assert audit.opinions[-1].model == "gpt-5.6-terra"
    assert audit.resolutions[0].outcome == "arbitrated"
    assert audit.resolutions[0].final_decision.reason == (
        "Source image supports this literal"
    )


@pytest.mark.parametrize(
    ("arbitration", "warning"),
    [
        (RuntimeError("Terra unavailable"), "Arbitration failed: RuntimeError: Terra unavailable"),
        (
            PageInspection(
                decisions=[
                    InspectionDecision(
                        region_id="p1-b999",
                        action=InspectionAction.ACCEPT,
                    )
                ]
            ),
            "different region ID",
        ),
        (
            PageInspection(
                decisions=[
                    InspectionDecision(
                        region_id="p1-b1",
                        action=InspectionAction.CORRECT,
                    )
                ]
            ),
            "did not include a region",
        ),
    ],
)
def test_invalid_arbitration_fails_closed_and_is_audited(
    simple_pdf: bytes,
    arbitration: PageInspection | Exception,
    warning: str,
) -> None:
    gateway = SpecialistGateway(
        PageInspection(
            decisions=[
                InspectionDecision(region_id="p1-b1", action=InspectionAction.ACCEPT)
            ]
        ),
        PageInspection(
            decisions=[
                InspectionDecision(region_id="p1-b1", action=InspectionAction.REJECT)
            ]
        ),
        arbitration,
    )

    result = _parse(simple_pdf, gateway)

    block = result.document.pages[0].blocks[0]
    resolution = result.document.pages[0].specialist_audit.resolutions[0]
    assert block.text == "Draft"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert warning in block.verification_reason
    assert resolution.outcome == "needs_review"
    assert resolution.final_decision is None
    assert warning in resolution.reasoning


class DuplicateDecisionGateway:
    input_tokens = 0
    output_tokens = 0

    def draft_page(self, _page) -> PageDraft:
        return PageDraft(regions=[_region("Draft")])

    def inspect_page(self, _page, _draft, *, region_ids, target_region_ids=None):
        region_id = (target_region_ids or region_ids)[0]
        return PageInspection(
            decisions=[
                InspectionDecision(region_id=region_id, action=InspectionAction.ACCEPT),
                InspectionDecision(
                    region_id=region_id,
                    action=InspectionAction.CORRECT,
                    corrected_region=_correction("Last writer must not win"),
                ),
            ]
        )

    def inspect_crops(self, *_args, **_kwargs):
        raise AssertionError("crop inspection was not requested")


def test_conflict_without_manager_flow_uses_deterministic_review_fallback(
    simple_pdf: bytes,
) -> None:
    result = _parse(simple_pdf, DuplicateDecisionGateway())

    block = result.document.pages[0].blocks[0]
    audit = result.document.pages[0].specialist_audit
    assert block.text == "Draft"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "conflicting specialist opinions" in block.verification_reason
    assert len(audit.opinions) == 2
    assert audit.resolutions[0].outcome == "needs_review"


def test_missing_specialist_decision_has_audited_review_resolution(
    simple_pdf: bytes,
) -> None:
    result = _parse(
        simple_pdf,
        SpecialistGateway(PageInspection(), PageInspection()),
    )

    block = result.document.pages[0].blocks[0]
    audit = result.document.pages[0].specialist_audit
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "No verification decision"
    assert audit.opinions == []
    assert len(audit.resolutions) == 1
    assert audit.resolutions[0].region_id == "p1-b1"
    assert audit.resolutions[0].outcome == "needs_review"
    assert audit.resolutions[0].reasoning == "No verification decision"


class OrderingConflictGateway(SpecialistGateway):
    def __init__(self, *, reject: bool = False) -> None:
        super().__init__(PageInspection(), PageInspection())
        self.reject = reject

    def draft_page(self, _page) -> PageDraft:
        return PageDraft(regions=[_region(f"Block {index}", reading_order=index) for index in range(4)])

    def plan_page(
        self,
        _page,
        _draft,
        *,
        region_ids,
        target_region_ids,
        repair_round,
        prior_inspections,
    ) -> PagePlan:
        del target_region_ids, repair_round, prior_inspections
        return PagePlan(
            delegations=[
                AgentDelegation(
                    role=AgentRole.LAYOUT_TEXT,
                    target_region_ids=region_ids,
                    reason="Review order",
                ),
                AgentDelegation(
                    role=AgentRole.TABLE_FORM,
                    target_region_ids=region_ids,
                    reason="Review order",
                ),
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
    ) -> PageInspection:
        targets = list(target_region_ids or region_ids)
        self.calls.append((agent_role, use_terra, targets))
        order = list(region_ids)
        if agent_role is AgentRole.TABLE_FORM:
            order[1], order[2] = order[2], order[1]
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=region_id,
                    action=(
                        InspectionAction.REJECT if self.reject else InspectionAction.ACCEPT
                    ),
                )
                for region_id in targets
            ],
            ordered_region_ids=order,
        )


def test_conflicting_order_opinions_are_ignored_audited_and_mark_page_for_review(
    simple_pdf: bytes,
) -> None:
    result = _parse(simple_pdf, OrderingConflictGateway())

    page = result.document.pages[0]
    payload_page = json.loads(result.json)["document"]["pages"][0]
    assert [block.text for block in page.blocks] == [f"Block {index}" for index in range(4)]
    assert all(block.verification is VerificationState.NEEDS_REVIEW for block in page.blocks)
    assert page.specialist_audit.ordering_resolution.outcome == "needs_review"
    assert page.specialist_audit.ordering_resolution.ordered_region_ids == []
    assert len(page.specialist_audit.ordering_opinions) == 2
    assert payload_page["status"] == "needs_review"
    assert any("conflicting ordered_region_ids" in warning for warning in result.document.warnings)


def test_order_conflict_marks_all_rejected_page_for_review_in_agentic_output(
    simple_pdf: bytes,
) -> None:
    result = _parse(simple_pdf, OrderingConflictGateway(reject=True))

    page = result.document.pages[0]
    payload_page = json.loads(result.json)["document"]["pages"][0]
    assert all(block.verification is VerificationState.REJECTED for block in page.blocks)
    assert page.specialist_audit.ordering_resolution.outcome == "needs_review"
    assert payload_page["blocks"] == []
    assert payload_page["status"] == "needs_review"
