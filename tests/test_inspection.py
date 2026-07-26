import pytest
from pydantic import ValidationError

from grounded_docparse.models import (
    BoundingBox,
    InspectionAction,
    InspectionDecision,
    VerificationState,
    VisualGrounding,
)


def test_visual_grounding_preserves_auditable_coordinate_spaces() -> None:
    grounding = VisualGrounding(
        page_number=2,
        normalized_box=BoundingBox(x0=0.1, y0=0.2, x1=0.4, y1=0.5),
        pixel_box=BoundingBox(x0=200, y0=400, x1=800, y1=1000, unit="pixels"),
        pdf_box=BoundingBox(x0=61.2, y0=158.4, x1=244.8, y1=396, unit="pdf_points"),
        page_width_pixels=2000,
        page_height_pixels=2000,
        crop_ref="assets/crops/page-0002-region-1.png",
        crop_sha256="a" * 64,
    )

    assert grounding.normalized_box.x0 == 0.1
    assert grounding.pixel_box.unit == "pixels"
    assert grounding.pdf_box.unit == "pdf_points"


def test_visual_grounding_rejects_non_sha256_crop_digest() -> None:
    with pytest.raises(ValidationError, match="crop_sha256"):
        VisualGrounding(
            page_number=1,
            normalized_box=BoundingBox(x0=0, y0=0, x1=1, y1=1),
            page_width_pixels=100,
            page_height_pixels=100,
            crop_ref="crop.png",
            crop_sha256="not-a-digest",
        )


def test_correction_requires_literal_corrected_text() -> None:
    with pytest.raises(ValidationError, match="corrected_text"):
        InspectionDecision(
            region_id="region-1",
            action=InspectionAction.CORRECT,
            evidence_refs=["assets/crops/region-1.png"],
        )


def test_inspection_decision_records_fail_closed_outcome() -> None:
    decision = InspectionDecision(
        region_id="region-1",
        action=InspectionAction.REJECT,
        evidence_refs=["assets/crops/region-1.png"],
        reason="The draft is not visible in the cited crop.",
    )

    assert decision.resulting_state is VerificationState.REJECTED
