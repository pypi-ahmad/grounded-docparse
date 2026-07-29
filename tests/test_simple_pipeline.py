import json
from types import SimpleNamespace

import pymupdf
from PIL import Image

from grounded_docparse import pipeline as pipeline_module
from grounded_docparse.config import ParserConfig
from grounded_docparse.ingest import IngestedDocument, PageEvidence
from grounded_docparse.models import (
    AgentRole,
    InspectionAction,
    InspectionDecision,
    InspectionRegionAddition,
    NodeType,
    PageDraft,
    PageInspection,
    RegionDraft,
    TableCellDraft,
    VerificationState,
)
from grounded_docparse.pipeline import DocumentParser
from grounded_docparse.runtime import ProviderRuntime


def test_geometry_only_rejection_flag_is_additive_and_fail_closed() -> None:
    try:
        typed = InspectionDecision.model_validate(
            {
                "region_id": "p1-b1",
                "action": "reject",
                "geometry_only": True,
            }
        )
    except ValueError:
        typed = None

    assert typed is not None
    assert typed.geometry_only is True
    assert (
        InspectionDecision(
            region_id="p1-b2",
            action=InspectionAction.REJECT,
        ).geometry_only
        is False
    )


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

    def inspect_crops(self, crops, **_kwargs):
        self.inspected_region_ids = [crop.region_id for crop in crops]
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
    assert payload["schema_version"] == "4.4.0"
    assert payload["metadata"]["source_name"] == "notice.pdf"
    assert payload["metadata"]["usage"]["input_tokens"] == 23
    assert getattr(result, "input_tokens", None) == 23
    assert getattr(result, "output_tokens", None) == 7
    annotated = getattr(result, "annotated_pdf", b"")
    assert annotated.startswith(b"%PDF")
    with pymupdf.open(stream=annotated, filetype="pdf") as rendered:
        assert len(rendered[0].get_drawings()) == 4


class QualityRecoveryGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.quality_calls = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.LIST_ITEM,
                    text="Open the cold water tap.",
                    list_marker="1.",
                    reading_order=0,
                    confidence=0.99,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
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


class NoQualityScanGateway:
    input_tokens = 0
    output_tokens = 0

    def draft_page(self, _page):
        return PageDraft()


class PlannedQualityCropGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.inspected = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Short",
                    reading_order=0,
                    confidence=0.99,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9},
                )
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
        self.inspected.extend(crop.region_id for crop in crops)
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


def test_planner_approved_nonvisual_box_is_dispatched(tmp_path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (200, 200), "white").save(image_path)
    page = PageEvidence(
        number=1,
        width=200,
        height=200,
        dpi=72,
        image_path=image_path,
        render_width_pixels=200,
        render_height_pixels=200,
        effective_dpi=72,
        source_width=200,
        source_height=200,
    )
    source = IngestedDocument(
        name="page.png",
        sha256="a" * 64,
        source_path=image_path,
        pages=[page],
    )
    config = ParserConfig(render_dpi=72, crop_dpi=72)
    gateway = PlannedQualityCropGateway()
    parser = DocumentParser(config, gateway_factory=lambda _config: gateway)

    processed = parser._process_page(
        source,
        page,
        tmp_path,
        1,
        None,
        ProviderRuntime(config),
        None,
        visual_recovery=True,
        allowed_recovery_boxes={(0.1, 0.1, 0.9, 0.9)},
        deferred_recovery_boxes=set(),
    )

    assert gateway.inspected == ["p1-b1"]
    assert processed.visual_recovery_crops == 1


def test_custom_gateway_without_analysis_does_not_synthesize_scan_probes() -> (
    None
):
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.draw_rect((72, 72, 540, 720), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
    data = document.tobytes()
    document.close()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: NoQualityScanGateway(),
    ).parse(data, "scan.pdf")

    blocks = result.document.pages[0].blocks
    assert blocks == []
    page_payload = json.loads(result.json)["document"]["pages"][0]
    assert page_payload["status"] == "ok"
    assert page_payload["blocks"] == []
    assert page_payload["quality"]["needs_review_reasons"] == []
    assert (
        result.document.pages[0].quality.model_dump(mode="json")
        == page_payload["quality"]
    )


class ScanProbeRecoveryGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.quality_calls = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.IMAGE,
                    text="",
                    reading_order=0,
                    confidence=0.99,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9},
                )
            ]
        )

    def inspect_crops(self, crops):
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

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.CORRECT,
                    evidence_refs=[crop.evidence_ref],
                    corrected_region=RegionDraft(
                        type=NodeType.PARAGRAPH,
                        text="Verified chart label",
                        reading_order=1,
                        confidence=0.99,
                    ),
                )
                for crop in crops
            ]
        )


def test_visual_recovery_does_not_synthesize_missing_regions() -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.draw_rect((72, 72, 540, 720), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
    data = document.tobytes()
    document.close()
    gateway = ScanProbeRecoveryGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(data, "scan.pdf")

    assert gateway.quality_calls == []
    assert [block.text for block in result.document.pages[0].blocks] == [""]
    assert result.metadata.visual_recovery_region_ids == []
    assert result.recovery_log == []


def test_visual_recovery_plan_prioritizes_failures_across_pages(monkeypatch) -> None:
    candidates = {
        1: [
            pipeline_module._RecoveryCandidate(1, (0.1, 0.1, 0.2, 0.2), 3, 0.1, 0, "low"),
            pipeline_module._RecoveryCandidate(1, (0.2, 0.2, 0.3, 0.3), 1, 0.9, 1, "broken"),
        ],
        2: [
            pipeline_module._RecoveryCandidate(2, (0.3, 0.3, 0.4, 0.4), 0, 1.0, 0, "missing")
        ],
    }
    monkeypatch.setattr(
        pipeline_module,
        "_page_recovery_candidates",
        lambda page, _analysis: candidates[page.number],
    )
    pages = [SimpleNamespace(number=1), SimpleNamespace(number=2)]

    plan = pipeline_module._visual_recovery_plan(
        pages,
        {1: None, 2: None},
        enabled=True,
        limit=2,
    )

    assert plan.candidate_count == 3
    assert plan.allowed == {
        1: {(0.2, 0.2, 0.3, 0.3)},
        2: {(0.3, 0.3, 0.4, 0.4)},
    }
    assert plan.deferred == {1: {(0.1, 0.1, 0.2, 0.2)}}

    disabled = pipeline_module._visual_recovery_plan(
        pages,
        {1: None, 2: None},
        enabled=False,
        limit=2,
    )
    assert disabled.allowed == {}
    assert disabled.deferred == {
        1: {(0.1, 0.1, 0.2, 0.2), (0.2, 0.2, 0.3, 0.3)},
        2: {(0.3, 0.3, 0.4, 0.4)},
    }
    assert disabled.candidate_count == 3


def test_visual_recovery_plan_enforces_document_and_page_limits(monkeypatch) -> None:
    candidates = {
        1: [
            pipeline_module._RecoveryCandidate(
                1,
                (index / 10, 0.0, index / 10 + 0.05, 0.2),
                4,
                0.5,
                index,
                f"p1-{index}",
            )
            for index in range(5)
        ],
        2: [
            pipeline_module._RecoveryCandidate(
                2,
                (index / 10, 0.3, index / 10 + 0.05, 0.5),
                4,
                0.5,
                index,
                f"p2-{index}",
            )
            for index in range(5)
        ],
    }
    monkeypatch.setattr(
        pipeline_module,
        "_page_recovery_candidates",
        lambda page, _analysis: candidates[page.number],
    )
    pages = [SimpleNamespace(number=1), SimpleNamespace(number=2)]
    analyses = {
        1: SimpleNamespace(quality=SimpleNamespace(warnings=[])),
        2: SimpleNamespace(quality=SimpleNamespace(warnings=[])),
    }

    plan = pipeline_module._visual_recovery_plan(
        pages, analyses, enabled=True, limit=8
    )

    assert sum(len(boxes) for boxes in plan.allowed.values()) == 6
    assert all(len(boxes) <= 3 for boxes in plan.allowed.values())

    candidates[1] = [
        pipeline_module._RecoveryCandidate(
            1, box, 1, 0.2, index, f"severe-{index}"
        )
        for index, box in enumerate(
            ((0.0, 0.0, 0.4, 1.0), (0.4, 0.0, 0.8, 1.0), (0.8, 0.0, 1.0, 1.0))
        )
    ]
    severe = pipeline_module._visual_recovery_plan(
        pages[:1], {1: analyses[1]}, enabled=True, limit=8
    )
    assert severe.allowed == {1: {candidate.bbox for candidate in candidates[1]}}


def test_garbage_ratio_is_unicode_safe() -> None:
    assert pipeline_module._garbage_ratio("Account: ₹15,480.50") == 0
    assert pipeline_module._garbage_ratio("������") > 0.35


class ConflictingScanProbeGateway(ScanProbeRecoveryGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.HEADER,
                    text="SYNTHETIC MEDICAL FAX - NO PHI",
                    reading_order=0,
                    confidence=0.99,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.8, "y1": 0.2},
                ),
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="FAX DATE: 2026-07-24",
                    reading_order=1,
                    confidence=0.99,
                    bbox={"x0": 0.1, "y0": 0.25, "x1": 0.8, "y1": 0.35},
                ),
            ]
        )

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.CORRECT,
                    evidence_refs=[crop.evidence_ref],
                    corrected_region=RegionDraft(
                        type=NodeType.PARAGRAPH,
                        text=("SYNTHETIC MEDICAL FAX - NO PHI\nFAX DATE: 2025-07-14"),
                        reading_order=2,
                        confidence=0.99,
                    ),
                )
                for crop in crops
            ]
        )


def test_full_page_scan_recovery_is_not_attempted() -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.draw_rect((72, 72, 540, 720), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
    data = document.tobytes()
    document.close()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: ConflictingScanProbeGateway(),
    ).parse(data, "scan.pdf")

    assert "2025-07-14" not in result.markdown
    assert "2026-07-24" in result.markdown
    assert len(result.document.pages[0].blocks) == 2


class OverflowingScanProbeGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.quality_calls = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.TABLE,
                    text="",
                    reading_order=index,
                    bbox={
                        "x0": 0.1 + (index % 3) * (0.8 / 3),
                        "y0": 0.1 + (index // 3) * (0.8 / 3),
                        "x1": 0.1 + ((index % 3) + 1) * (0.8 / 3),
                        "y1": 0.1 + ((index // 3) + 1) * (0.8 / 3),
                    },
                    table_cells=[
                        {"row_index": 0, "column_index": 0, "text": "Medication"},
                        {"row_index": 0, "column_index": 1, "text": ""},
                    ],
                )
                for index in range(9)
            ]
        )

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection()


def test_incomplete_scanned_structures_are_repaired_without_duplicate_probes() -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.draw_rect((72, 72, 540, 720), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
    data = document.tobytes()
    document.close()

    gateway = OverflowingScanProbeGateway()
    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(data, "scan.pdf")

    assert len(result.document.pages[0].blocks) == 9
    assert [len(call[1]) for call in gateway.quality_calls] == [8, 1]
    assert not any(
        "scan omission probes" in warning for warning in result.document.warnings
    )
    assert not any(
        "recovered 9 native text regions" in warning
        for warning in result.document.warnings
    )
    assert not any(
        "repair limit exceeded" in warning for warning in result.document.warnings
    )


class UnresolvedCriticalGateway(QualityRecoveryGateway):
    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.FORM_FIELD,
                    text="NPI: 1388746512",
                    reading_order=0,
                    confidence=0.99,
                    bbox={"x0": 0.999, "y0": 0.1, "x1": 1.0, "y1": 0.2},
                )
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
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

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection()


def test_clipped_critical_literal_remains_visible_with_review_warning() -> None:
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
    assert (
        result.document.pages[0].blocks[0].verification
        is VerificationState.NEEDS_REVIEW
    )
    assert '"status": "needs_review"' in result.json
    assert len(gateway.quality_calls) == 1


def _account_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 90), "Account holder information", fontsize=11)
    data = document.tobytes()
    document.close()
    return data


class SecondRoundStructuredRepairGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.quality_calls = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Account holder information",
                    reading_order=0,
                    confidence=0.99,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                ),
                RegionDraft(
                    type=NodeType.FORM_FIELD,
                    form={
                        "label": "Account holder information",
                        "value": "Hallucinated",
                    },
                    reading_order=1,
                    confidence=0.99,
                    bbox={"x0": 0.999, "y0": 0.3, "x1": 1.0, "y1": 0.4},
                ),
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.REJECT,
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ]
        )

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        if len(self.quality_calls) == 1:
            return PageInspection(
                decisions=[
                    InspectionDecision(
                        region_id=crop.region_id,
                        action=InspectionAction.REJECT,
                        reason="First crop remained ambiguous",
                        evidence_refs=[crop.evidence_ref],
                    )
                    for crop in crops
                ]
            )
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.CORRECT,
                    evidence_refs=[crop.evidence_ref],
                    corrected_region=crop.candidate_region.model_copy(
                        update={
                            "form": crop.candidate_region.form.model_copy(
                                update={"value": "Verified"}
                            )
                        }
                    ),
                )
                for crop in crops
            ]
        )


def test_rejected_form_remains_reviewable_after_one_quality_round() -> None:
    gateway = SecondRoundStructuredRepairGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "account.pdf")

    block = result.document.pages[0].blocks[1]
    assert len(gateway.quality_calls) == 1
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.form is not None
    assert block.form.value == "Hallucinated"


def test_failed_quality_crop_preserves_reviewable_structured_content(
    monkeypatch,
) -> None:
    gateway = SecondRoundStructuredRepairGateway()

    def fail_crop(*_args, **_kwargs):
        raise RuntimeError("quality crop unavailable")

    monkeypatch.setattr("grounded_docparse.pipeline.render_region_crop", fail_crop)
    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "account.pdf")

    block = result.document.pages[0].blocks[1]
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "Hallucinated" in result.markdown


class MalformedCorrectionGateway(SecondRoundStructuredRepairGateway):
    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.CORRECT,
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ]
        )


def test_malformed_quality_correction_preserves_reviewable_content() -> None:
    gateway = MalformedCorrectionGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "account.pdf")

    block = result.document.pages[0].blocks[1]
    assert len(gateway.quality_calls) == 1
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "Hallucinated" in result.markdown


class ManyQualityCandidatesGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.quality_calls = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.FORM_FIELD,
                    form={"label": "Account holder information"},
                    reading_order=index,
                    confidence=0.4,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                )
                for index in range(10)
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
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


class MismatchedQualityEvidenceGateway(SecondRoundStructuredRepairGateway):
    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.CORRECT,
                    confidence=0.95,
                    evidence_refs=["page:1:another-region:quality"],
                    corrected_region=crop.candidate_region.model_copy(
                        update={
                            "form": crop.candidate_region.form.model_copy(
                                update={"value": "Cross-bound correction"}
                            )
                        }
                    ),
                )
                for crop in crops
            ]
        )


def test_mismatched_quality_crop_evidence_fails_closed() -> None:
    gateway = MismatchedQualityEvidenceGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "account.pdf")

    block = result.document.pages[0].blocks[1]
    assert len(gateway.quality_calls) == 1
    assert block.form is not None
    assert block.form.value == "Hallucinated"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "evidence reference" in block.verification_reason

def test_quality_repair_processes_all_candidates_in_batches_of_eight() -> None:
    gateway = ManyQualityCandidatesGateway()

    DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "accounts.pdf")

    assert [[crop.region_id for crop in call[1]] for call in gateway.quality_calls] == [
        [f"p1-b{index}" for index in range(1, 9)],
        ["p1-b9", "p1-b10"],
    ]


class RepeatedQualityRejectionGateway(ManyQualityCandidatesGateway):
    def draft_page(self, page):
        draft = super().draft_page(page)
        return PageDraft(regions=draft.regions[:1])

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.REJECT,
                    reason="Unsupported form content",
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ]
        )


def test_semantic_rejection_remains_reviewable_after_one_quality_round() -> None:
    gateway = RepeatedQualityRejectionGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "account.pdf")

    block = result.document.pages[0].blocks[0]
    assert len(gateway.quality_calls) == 1
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "Account holder information" in result.markdown


class GeometryOnlyQualityGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self) -> None:
        self.quality_calls = []

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.FORM_FIELD,
                    form={"label": "Account holder information"},
                    reading_order=0,
                    confidence=0.99,
                    bbox={"x0": 0.999, "y0": 0.1, "x1": 1.0, "y1": 0.2},
                )
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
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

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=(
                        InspectionAction.REJECT
                        if crop.region_id == "p1-b1"
                        else InspectionAction.ACCEPT
                    ),
                    reason="Crop is unreadable" if crop.region_id == "p1-b1" else "",
                    geometry_only=crop.region_id == "p1-b1",
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ]
        )


def test_geometry_only_rejection_remains_visible_for_review() -> None:
    gateway = GeometryOnlyQualityGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "account.pdf")

    block = next(item for item in result.document.pages[0].blocks if item.id == "p1-b1")
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "Account holder information" in result.markdown
    assert [[crop.region_id for crop in call[1]] for call in gateway.quality_calls] == [
        ["p1-b1"],
    ]


class SemanticRejectionOfClippedGateway(GeometryOnlyQualityGateway):
    def draft_page(self, page):
        draft = super().draft_page(page)
        form = draft.regions[0].form
        assert form is not None
        draft.regions[0] = draft.regions[0].model_copy(
            update={"form": form.model_copy(update={"value": "Unsupported"})}
        )
        return draft

    def inspect_quality_crops(self, crops, *, page_number):
        self.quality_calls.append((page_number, crops))
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=(
                        InspectionAction.REJECT
                        if crop.region_id == "p1-b1"
                        else InspectionAction.ACCEPT
                    ),
                    reason=(
                        "Geometry is valid; content is unsupported"
                        if crop.region_id == "p1-b1"
                        else ""
                    ),
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ]
        )


def test_semantic_rejection_of_clipped_content_remains_suppressed() -> None:
    gateway = SemanticRejectionOfClippedGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72, crop_dpi=144),
        gateway_factory=lambda _config: gateway,
    ).parse(_account_pdf(), "account.pdf")

    block = next(item for item in result.document.pages[0].blocks if item.id == "p1-b1")
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "Unsupported" in result.markdown


class DirectInspectionGateway(AcceptingGateway):
    def __init__(self) -> None:
        self.inspections = []

    def inspect_crops(
        self,
        crops,
        *,
        agent_role=AgentRole.EVIDENCE_CRITIC,
        **_kwargs,
    ):
        self.inspections.append((agent_role, [crop.region_id for crop in crops]))
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


def test_risky_regions_are_inspected_directly(
    simple_pdf: bytes,
) -> None:
    gateway = DirectInspectionGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert gateway.inspections == [
        (AgentRole.EVIDENCE_CRITIC, ["p1-b1", "p1-b2"]),
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
    def inspect_crops(self, crops, **_kwargs):
        targets = [crop.region_id for crop in crops]
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.CORRECT,
                    evidence_refs=[crops[0].evidence_ref],
                ),
                *[
                    InspectionDecision(
                        region_id=crop.region_id,
                        action=InspectionAction.ACCEPT,
                        evidence_refs=[crop.evidence_ref],
                    )
                    for crop in crops[1:]
                ],
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
    assert "Correction did not include a region" in block.verification_reason


class CorrectingGateway(AcceptingGateway):
    def inspect_crops(self, crops, **_kwargs):
        targets = [crop.region_id for crop in crops]
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.CORRECT,
                    confidence=0.95,
                    evidence_refs=[crops[0].evidence_ref],
                    corrected_region=RegionDraft(
                        type=NodeType.HEADING,
                        text="Grounded correction",
                        reading_order=0,
                        heading_level=2,
                        bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                    ),
                ),
                *[
                    InspectionDecision(
                        region_id=crop.region_id,
                        action=InspectionAction.ACCEPT,
                        evidence_refs=[crop.evidence_ref],
                    )
                    for crop in crops[1:]
                ],
            ]
        )


def test_grounded_correction_replaces_draft_text(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: CorrectingGateway(),
    ).parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.text == "Grounded correction"
    assert block.heading_level == 1
    assert block.verification is VerificationState.VERIFIED


class RejectingGateway(AcceptingGateway):
    def inspect_crops(self, crops, **_kwargs):
        targets = [crop.region_id for crop in crops]
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.REJECT,
                    reason="Not visible",
                    evidence_refs=[crops[0].evidence_ref],
                )
            ]
        )


def test_explicit_rejection_keeps_glm_content_reviewable(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: RejectingGateway()
    ).parse(simple_pdf, "notice.pdf")

    assert result.document.pages[0].blocks[0].verification is VerificationState.NEEDS_REVIEW
    assert "Public notice" in result.markdown


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

    def inspect_crops(self, crops, **_kwargs):
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="wrong-region",
                    action=InspectionAction.ACCEPT,
                    evidence_refs=[crops[0].evidence_ref],
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
    assert "unexpected region IDs wrong-region" in block.verification_reason


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
                    text="Name | Value\n--- | ---\nStatus | Current",
                    confidence=0.99,
                    reading_order=2,
                    bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.5},
                    table_cells=[
                        TableCellDraft(row_index=0, column_index=0, text="Name"),
                        TableCellDraft(row_index=0, column_index=1, text="Value"),
                        TableCellDraft(row_index=1, column_index=0, text="Status"),
                        TableCellDraft(row_index=1, column_index=1, text="Current"),
                    ],
                ),
            ]
        )


def test_only_low_confidence_regions_are_sent_to_luna(
    simple_pdf: bytes,
) -> None:
    gateway = SelectiveGateway()
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert gateway.inspected_region_ids == ["p1-b2"]
    assert "Certain paragraph" in result.markdown
    assert (
        result.document.pages[0].blocks[0].verification is VerificationState.NOT_CHECKED
    )


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
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Batch ID2 SCAN-042",
                    confidence=0.99,
                    reading_order=3,
                    bbox={"x0": 0.1, "y0": 0.4, "x1": 0.9, "y1": 0.5},
                ),
            ]
        )


def test_only_ambiguous_critical_literals_trigger_luna(
    simple_pdf: bytes,
) -> None:
    gateway = CriticalLiteralGateway()
    DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert gateway.inspected_region_ids == ["p1-b4"]


class InvalidCorrectionGateway(CorrectingGateway):
    def inspect_crops(self, crops, **_kwargs):
        targets = [crop.region_id for crop in crops]
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=targets[0],
                    action=InspectionAction.CORRECT,
                    confidence=0.95,
                    evidence_refs=[crops[0].evidence_ref],
                    corrected_region=RegionDraft(
                        type=NodeType.HEADING,
                        text="Unsupported correction",
                        reading_order=0,
                        bbox={"x0": 0.8, "y0": 0.1, "x1": 0.2, "y1": 0.2},
                    ),
                ),
                *[
                    InspectionDecision(
                        region_id=crop.region_id,
                        action=InspectionAction.ACCEPT,
                        evidence_refs=[crop.evidence_ref],
                    )
                    for crop in crops[1:]
                ],
            ]
        )


def test_invalid_corrected_geometry_is_ignored_while_text_is_applied(
    simple_pdf: bytes,
) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: InvalidCorrectionGateway(),
    ).parse(simple_pdf, "notice.pdf")

    block = result.document.pages[0].blocks[0]
    assert block.text == "Unsupported correction"
    assert block.verification is VerificationState.VERIFIED
    assert block.bbox.model_dump(exclude={"unit"}) == {
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.9,
        "y1": 0.2,
    }


class FailingVerifierGateway(SelectiveGateway):
    def inspect_crops(self, *_args, **_kwargs):
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

    def inspect_crops(self, crops):
        self.crop_batches.append(crops)
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


def test_crop_requests_cover_all_risky_regions_in_one_batch(
    simple_pdf: bytes,
) -> None:
    gateway = CropBatchGateway()
    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert len(gateway.crop_batches) == 1
    assert [crop.region_id for crop in gateway.crop_batches[0]] == [
        f"p1-b{index}" for index in range(1, 11)
    ]
    assert all(
        block.verification is VerificationState.VERIFIED
        for block in result.document.pages[0].blocks
    )


def test_crop_render_error_preserves_draft_text(
    simple_pdf: bytes,
    monkeypatch,
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
    assert all("crop renderer unavailable" in block.verification_reason for block in blocks)
    assert all(block.text in result.markdown for block in blocks)


class FailingCropGateway(CropBatchGateway):
    def inspect_crops(self, crops):
        raise RuntimeError("crop provider unavailable")


def test_crop_verifier_error_preserves_draft_text(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: FailingCropGateway(),
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

    def inspect_crops(self, crops, **_kwargs):
        targets = [crop.region_id for crop in crops]
        self.full_region_ids = targets
        self.target_region_ids = targets
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b2",
                    action=InspectionAction.ACCEPT,
                    evidence_refs=[crops[0].evidence_ref],
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


def test_page_inspection_cannot_add_content_or_reorder_glm_manifest(
    simple_pdf: bytes,
) -> None:
    gateway = CoverageGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert gateway.full_region_ids == ["p1-b2"]
    assert gateway.target_region_ids == ["p1-b2"]
    assert [block.text for block in blocks] == [
        "Certain introduction",
        "Risky instructions",
    ]
    assert [block.id for block in blocks] == ["p1-b1", "p1-b2"]
    assert any("ignored 1 Luna-added region" in warning for warning in result.document.warnings)
    assert any("ignored Luna reading-order changes" in warning for warning in result.document.warnings)


class RejectedAdditionGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(
        self,
        *,
        predecessor_count: int = 1,
        reject: bool = True,
        overlap_correction: bool = False,
    ) -> None:
        self.predecessor_count = predecessor_count
        self.reject = reject
        self.overlap_correction = overlap_correction

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="Grounded replacement",
                    confidence=0.4,
                    reading_order=index,
                    bbox={
                        "x0": 0.1,
                        "y0": 0.1 + index * 0.2,
                        "x1": 0.9,
                        "y1": 0.2 + index * 0.2,
                    },
                )
                for index in range(self.predecessor_count)
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
        action = InspectionAction.REJECT if self.reject else InspectionAction.ACCEPT
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=action,
                    reason="Unsupported draft" if self.reject else "Grounded draft",
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ],
            additional_regions=[
                InspectionRegionAddition(
                    region_id="provider-replacement",
                    reason="Grounded page inspection replacement",
                    region=RegionDraft(
                        type=NodeType.PARAGRAPH,
                        text=(
                            "Grounded correction"
                            if self.overlap_correction
                            else "Grounded replacement"
                        ),
                        confidence=0.98,
                        reading_order=self.predecessor_count,
                        bbox=(
                            {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2}
                            if self.overlap_correction
                            else {"x0": 0.1, "y0": 0.7, "x1": 0.9, "y1": 0.8}
                        ),
                    ),
                )
            ],
        )


def test_luna_addition_cannot_supersede_glm_element(
    simple_pdf: bytes,
) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: RejectedAdditionGateway(
            overlap_correction=True
        ),
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert len(blocks) == 1
    assert blocks[0].id == "p1-b1"
    assert blocks[0].text == "Grounded replacement"
    assert blocks[0].verification is VerificationState.NEEDS_REVIEW
    assert blocks[0].confidence == 0.4
    assert blocks[0].correction_lineage == []
    assert any("ignored 1 Luna-added region" in warning for warning in result.document.warnings)


class OrderedRejectedAdditionGateway(RejectedAdditionGateway):
    def draft_page(self, page):
        draft = super().draft_page(page)
        draft.regions.append(
            RegionDraft(
                type=NodeType.PARAGRAPH,
                text="Active companion",
                confidence=0.4,
                reading_order=1,
                bbox={"x0": 0.1, "y0": 0.4, "x1": 0.9, "y1": 0.5},
            )
        )
        return draft

    def inspect_crops(self, crops, **kwargs):
        inspection = super().inspect_crops(crops, **kwargs)
        inspection.decisions[1] = InspectionDecision(
            region_id="p1-b2",
            action=InspectionAction.ACCEPT,
            reason="Grounded draft",
            evidence_refs=[crops[1].evidence_ref],
        )
        inspection.ordered_region_ids = [
            "p1-b2",
            "p1-b1",
            "provider-replacement",
        ]
        return inspection


def test_provider_order_alias_cannot_reorder_glm_elements(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: OrderedRejectedAdditionGateway(
            overlap_correction=True
        ),
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert [(block.id, block.text) for block in blocks] == [
        ("p1-b1", "Grounded replacement"),
        ("p1-b2", "Active companion"),
    ]
    assert any(
        "ignored Luna reading-order changes" in warning
        for warning in result.document.warnings
    )


def test_luna_addition_is_ignored_even_when_duplicate(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: RejectedAdditionGateway(reject=False),
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert [block.id for block in blocks] == ["p1-b1"]
    assert blocks[0].confidence == 0.4
    assert blocks[0].correction_lineage == []
    assert any(
        "ignored 1 Luna-added region" in warning
        for warning in result.document.warnings
    )


def test_luna_addition_is_ignored_for_multiple_glm_predecessors(
    simple_pdf: bytes,
) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: RejectedAdditionGateway(predecessor_count=2),
    ).parse(simple_pdf, "notice.pdf")

    blocks = result.document.pages[0].blocks
    assert [block.verification for block in blocks] == [
        VerificationState.NEEDS_REVIEW,
        VerificationState.NEEDS_REVIEW,
    ]
    assert [block.id for block in blocks] == ["p1-b1", "p1-b2"]
    assert all(block.correction_lineage == [] for block in blocks)


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
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: NormalizingGateway(),
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

    def inspect_crops(self, crops):
        self.crop_batches.append(crops)
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id="p1-b1",
                    action=InspectionAction.CORRECT,
                    confidence=0.95,
                    evidence_refs=[crops[0].evidence_ref],
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
                    confidence=0.95,
                    evidence_refs=[crops[0].evidence_ref],
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


def test_unexpected_crop_decision_rejects_the_visual_batch(
    simple_pdf: bytes,
) -> None:
    gateway = ProactiveCropGateway()

    result = DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf")

    assert len(gateway.crop_batches) == 1
    assert [crop.region_id for crop in gateway.crop_batches[0]] == ["p1-b2"]
    assert [block.id for block in result.document.pages[0].blocks] == ["p1-b1", "p1-b2"]
    assert [block.reading_order for block in result.document.pages[0].blocks] == [0, 1]
    assert "labwebl@health.mo.gov" in result.markdown
    assert "Bottle with Max. fill line and Min. fill line labels." not in result.markdown
    assert "<figure>Generic bottle</figure>" in result.markdown
    assert any(
        "unexpected region IDs p1-b1" in warning
        for warning in result.document.warnings
    )


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
                    confidence=0.95,
                    evidence_refs=[crop.evidence_ref],
                    corrected_region=crop.candidate_region.model_copy(
                        update={
                            "figure_description": f"Detailed visual {crop.region_id}"
                        }
                    ),
                )
                for crop in crops
            ]
        )


def test_all_visuals_are_enriched_in_bounded_batches(
    simple_pdf: bytes,
) -> None:
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
    assert [block.verification for block in blocks] == [
        *([VerificationState.VERIFIED] * 8),
        *([VerificationState.NEEDS_REVIEW] * 2),
    ]
    assert all(
        block.figure_description.startswith("Detailed visual") for block in blocks[:8]
    )
    assert all(
        block.figure_description.startswith("Generic visual") for block in blocks[8:]
    )
    assert all(
        "second visual batch failed" in block.verification_reason for block in blocks[8:]
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
                    bbox={
                        "x0": 0.1,
                        "y0": index / 10,
                        "x1": 0.9,
                        "y1": (index + 1) / 10,
                    },
                )
                for index in range(8)
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
        return PageInspection(
            decisions=[
                InspectionDecision(
                    region_id=crop.region_id,
                    action=InspectionAction.ACCEPT,
                    evidence_refs=[crop.evidence_ref],
                )
                for crop in crops
            ],
            ordered_region_ids=list(
                reversed([crop.region_id for crop in crops])
            ),
        )


def test_extreme_page_reordering_is_ignored_and_audited(simple_pdf: bytes) -> None:
    result = DocumentParser(
        ParserConfig(render_dpi=72),
        gateway_factory=lambda _config: ExtremeOrderGateway(),
    ).parse(simple_pdf, "notice.pdf")

    assert [block.text for block in result.document.pages[0].blocks] == [
        f"Block {index}" for index in range(8)
    ]
    assert any(
        "ignored Luna reading-order changes" in warning
        for warning in result.document.warnings
    )
