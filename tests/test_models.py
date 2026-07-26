import pytest
from pydantic import ValidationError

from grounded_docparse import ParserConfig
from grounded_docparse.models import (
    BoundingBox,
    PageVerification,
    RecognitionCandidate,
    RegionDraft,
    VerificationDecision,
)


def test_normalized_bbox_rejects_coordinates_above_one() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x0=0, y0=0, x1=2, y1=1)


def test_source_bbox_allows_absolute_coordinates() -> None:
    box = BoundingBox(x0=0, y0=0, x1=612, y1=792, unit="pdf_points")
    assert box.x1 == 612


def test_region_bbox_cannot_bypass_normalized_limit() -> None:
    with pytest.raises(ValidationError):
        RegionDraft(
            type="Paragraph",
            bbox=BoundingBox(x0=0, y0=0, x1=612, y1=792, unit="pdf_points"),
            reading_order=0,
        )


def test_mutable_paddle_image_is_rejected() -> None:
    with pytest.raises(ValueError, match="pinned"):
        ParserConfig(paddle_image="example/paddle:latest")


def test_recognition_candidate_and_verification_are_bounded() -> None:
    candidate = RecognitionCandidate(
        id="candidate-1",
        source="glm",
        task="text",
        prompt_version="glm-region-v1",
        pass_number=1,
        text="literal text",
    )
    verification = PageVerification(
        decisions=[
            VerificationDecision(
                region_id="region-1",
                selected_candidate_id=candidate.id,
            )
        ]
    )
    assert verification.decisions[0].selected_candidate_id == "candidate-1"
