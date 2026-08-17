from __future__ import annotations

import pytest

from grounded_docparse import pipeline as pipeline_module
from grounded_docparse.config import ParserConfig
from grounded_docparse.models import (
    AnalysisRegionType,
    BoundingBoxProvenance,
    CoordinateBox,
    InspectionAction,
    InspectionDecision,
    InspectionRegionAddition,
    LayoutRegionEvidence,
    NodeType,
    PageAnalysis,
    PageDraft,
    PageInspection,
    PageRenderEvidence,
    RegionDraft,
    ScanQualityEvidence,
    VerificationState,
)
from grounded_docparse.pipeline import DocumentParser


class RecoveryGateway:
    input_tokens = 0
    output_tokens = 0

    def __init__(self, *, confidence: float = 0.95, reject: bool = False) -> None:
        self.confidence = confidence
        self.reject = reject

    def draft_page(self, _page):
        return PageDraft(
            regions=[
                RegionDraft(
                    type=NodeType.PARAGRAPH,
                    text="GLM original",
                    reading_order=0,
                    confidence=0.4,
                    bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
                )
            ]
        )

    def inspect_crops(self, crops, **_kwargs):
        region_id = crops[0].region_id
        decision = InspectionDecision(
            region_id=region_id,
            action=(InspectionAction.REJECT if self.reject else InspectionAction.CORRECT),
            reason="Unreadable" if self.reject else "Clearly visible",
            confidence=self.confidence,
            evidence_refs=[crops[0].evidence_ref],
            corrected_region=(
                None
                if self.reject
                else RegionDraft(
                    type=NodeType.HEADING,
                    text="Luna recovered",
                    reading_order=7,
                    confidence=0.99,
                    heading_level=2,
                    bbox={"x0": 0.5, "y0": 0.5, "x1": 0.8, "y1": 0.8},
                )
            ),
        )
        return PageInspection(
            decisions=[decision],
            additional_regions=[
                InspectionRegionAddition(
                    region_id="luna-added",
                    region=RegionDraft(
                        type=NodeType.PARAGRAPH,
                        text="Unsupported addition",
                        reading_order=1,
                        bbox={"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.4},
                    ),
                )
            ],
            ordered_region_ids=["luna-added", region_id],
        )


class MismatchedEvidenceRecoveryGateway(RecoveryGateway):
    def inspect_crops(self, crops, **_kwargs):
        inspection = super().inspect_crops(crops, **_kwargs)
        inspection.decisions[0].evidence_refs = ["page:1:another-region"]
        return inspection


class DuplicateRecoveryGateway(RecoveryGateway):
    def inspect_crops(self, crops, **_kwargs):
        inspection = super().inspect_crops(crops, **_kwargs)
        inspection.decisions.append(
            inspection.decisions[0].model_copy(
                deep=True,
                update={
                    "corrected_region": inspection.decisions[0].corrected_region.model_copy(
                        update={"text": "Duplicate decision text"}
                    )
                },
            )
        )
        return inspection


def _parse(simple_pdf: bytes, gateway: RecoveryGateway):
    return DocumentParser(
        ParserConfig(render_dpi=72), gateway_factory=lambda _config: gateway
    ).parse(simple_pdf, "notice.pdf", refine_markdown=False)


def test_high_confidence_recovery_changes_only_existing_text(simple_pdf: bytes) -> None:
    result = _parse(simple_pdf, RecoveryGateway())

    blocks = result.document.pages[0].blocks
    assert len(blocks) == 1
    block = blocks[0]
    assert block.text == "Luna recovered"
    assert block.type is NodeType.PARAGRAPH
    assert block.reading_order == 0
    assert block.heading_level is None
    assert block.confidence == 0.4
    assert block.bbox.model_dump(exclude={"unit"}) == {
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.9,
        "y1": 0.2,
    }
    assert result.elements[0].source == "luna-recovery"
    assert result.recovery_log[0].original_element_id == block.id
    assert result.recovery_log[0].confidence == "high"


def test_sub_high_confidence_recovery_keeps_glm_text(simple_pdf: bytes) -> None:
    result = _parse(simple_pdf, RecoveryGateway(confidence=0.84))

    block = result.document.pages[0].blocks[0]
    assert block.text == "GLM original"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "AI correction confidence below 0.85"
    assert result.elements[0].source == "glm-ocr"
    assert result.recovery_log == []


def test_luna_rejection_keeps_glm_text_visible(simple_pdf: bytes) -> None:
    result = _parse(simple_pdf, RecoveryGateway(reject=True))

    block = result.document.pages[0].blocks[0]
    assert block.text == "GLM original"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "GLM original" in result.markdown
    assert result.recovery_log == []


def test_mismatched_crop_evidence_fails_closed(simple_pdf: bytes) -> None:
    result = _parse(simple_pdf, MismatchedEvidenceRecoveryGateway())

    block = result.document.pages[0].blocks[0]
    assert block.text == "GLM original"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "evidence reference" in block.verification_reason
    assert result.recovery_log == []


def test_duplicate_crop_decisions_fail_closed(simple_pdf: bytes) -> None:
    result = _parse(simple_pdf, DuplicateRecoveryGateway())

    block = result.document.pages[0].blocks[0]
    assert block.text == "GLM original"
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert "multiple decisions" in block.verification_reason
    assert result.recovery_log == []


def test_glm_failure_on_all_nonblank_pages_stops_before_luna(
    monkeypatch, simple_pdf: bytes
) -> None:
    class FailedAnalyzer:
        def __init__(self, _config):
            pass

        def analyze_window(self, pages, progress_callback=None):
            for page in pages:
                yield PageAnalysis(
                    render=PageRenderEvidence(
                        render_width_pixels=612,
                        render_height_pixels=792,
                        source_page=page.number,
                        source_width=612,
                        source_height=792,
                        source_unit="points",
                    ),
                    quality=ScanQualityEvidence(blank=False),
                    warnings=["GLM-OCR returned no layout regions"],
                )

    monkeypatch.setattr(pipeline_module, "PageAnalyzer", FailedAnalyzer)

    with pytest.raises(
        RuntimeError,
        match="GLM-OCR produced no usable elements for any nonblank page",
    ):
        DocumentParser(ParserConfig(render_dpi=72)).parse(
            simple_pdf,
            "notice.pdf",
            refine_markdown=False,
            visual_recovery=False,
        )


def test_glm_recognition_failure_is_not_exported_as_an_image_only_success(
    monkeypatch, simple_pdf: bytes
) -> None:
    class FailedRecognitionAnalyzer:
        def __init__(self, _config):
            pass

        def analyze_window(self, pages, progress_callback=None):
            for page in pages:
                yield PageAnalysis(
                    render=PageRenderEvidence(
                        render_width_pixels=612,
                        render_height_pixels=792,
                        source_page=page.number,
                        source_width=612,
                        source_height=792,
                        source_unit="points",
                    ),
                    quality=ScanQualityEvidence(blank=False),
                    regions=[
                        LayoutRegionEvidence(
                            id=f"p{page.number}-analysis-1",
                            native_label="text",
                            type=AnalysisRegionType.TEXT,
                            text="",
                            bbox=BoundingBoxProvenance(
                                normalized={
                                    "x0": 0.1,
                                    "y0": 0.1,
                                    "x1": 0.9,
                                    "y1": 0.2,
                                },
                                rendered=CoordinateBox(
                                    x0=61.2,
                                    y0=79.2,
                                    x1=550.8,
                                    y1=158.4,
                                    unit="pixels",
                                ),
                                source=CoordinateBox(
                                    x0=61.2,
                                    y0=79.2,
                                    x1=550.8,
                                    y1=158.4,
                                    unit="points",
                                ),
                                source_page=page.number,
                            ),
                        ),
                        LayoutRegionEvidence(
                            id=f"p{page.number}-analysis-2",
                            native_label="image",
                            type=AnalysisRegionType.FIGURE,
                            text="",
                            bbox=BoundingBoxProvenance(
                                normalized={
                                    "x0": 0.1,
                                    "y0": 0.3,
                                    "x1": 0.9,
                                    "y1": 0.8,
                                },
                                rendered=CoordinateBox(
                                    x0=61.2,
                                    y0=237.6,
                                    x1=550.8,
                                    y1=633.6,
                                    unit="pixels",
                                ),
                                source=CoordinateBox(
                                    x0=61.2,
                                    y0=237.6,
                                    x1=550.8,
                                    y1=633.6,
                                    unit="points",
                                ),
                                source_page=page.number,
                            ),
                        ),
                    ],
                    warnings=["GLM-OCR recognition failed for 1 of 1 OCR regions"],
                )

    monkeypatch.setattr(pipeline_module, "PageAnalyzer", FailedRecognitionAnalyzer)

    with pytest.raises(RuntimeError, match="GLM-OCR recognition failed"):
        DocumentParser(ParserConfig(render_dpi=72)).parse(
            simple_pdf,
            "notice.pdf",
            refine_markdown=False,
            visual_recovery=False,
        )
