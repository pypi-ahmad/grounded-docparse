from grounded_docparse.config import ParserConfig
from grounded_docparse.models import (
    BoundingBox,
    InspectionAction,
    InspectionDecision,
    PageDraft,
    PageInspection,
    ProcessingProfile,
    RegionDraft,
    RunRecord,
    SegmentationMode,
    VerificationState,
)
from grounded_docparse.pipeline import DocumentParser


class AcceptingVisionGateway:
    def draft_page(self, page):
        return (
            PageDraft(
                regions=[
                    RegionDraft(
                        type="Paragraph",
                        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.6, y1=0.2),
                        reading_order=0,
                        text="Grounded source paragraph.",
                        confidence=0.8,
                    )
                ]
            ),
            RunRecord(provider="openai", model="gpt-5.6-luna", stage="page_draft"),
        )

    def inspect_page(self, page, draft, *, region_ids):
        return (
            PageInspection(
                decisions=[
                    InspectionDecision(
                        region_id=region_ids[0],
                        action=InspectionAction.ACCEPT,
                        evidence_refs=[f"page:{page.number}"],
                    )
                ]
            ),
            RunRecord(
                provider="openai",
                model="gpt-5.6-terra",
                stage="page_inspection",
            ),
        )


class CropInspectingGateway(AcceptingVisionGateway):
    def __init__(self) -> None:
        self.crop_sizes: list[tuple[int, int]] = []

    def inspect_page(self, page, draft, *, region_ids):
        return (
            PageInspection(
                decisions=[
                    InspectionDecision(
                        region_id=region_ids[0],
                        action=InspectionAction.INSPECT_CROP,
                        evidence_refs=[f"page:{page.number}"],
                    )
                ]
            ),
            RunRecord(
                provider="openai",
                model="gpt-5.6-terra",
                stage="page_inspection",
            ),
        )

    def inspect_crop(
        self,
        crop_path,
        *,
        region_id,
        candidate_text,
        evidence_ref,
        attempt,
    ):
        import pymupdf

        pixmap = pymupdf.Pixmap(str(crop_path))
        self.crop_sizes.append((pixmap.width, pixmap.height))
        return (
            InspectionDecision(
                region_id=region_id,
                action=InspectionAction.ACCEPT,
                evidence_refs=[evidence_ref],
            ),
            RunRecord(
                provider="openai",
                model="gpt-5.6-terra",
                stage="crop_inspection",
            ),
        )

def test_balanced_pipeline_releases_only_terra_verified_page_content(simple_pdf) -> None:
    parser = DocumentParser(
        ParserConfig(
            enable_paddle=False,
            enable_glm=False,
            enable_openai=True,
            render_dpi=72,
        ),
        gateway_factory=lambda config: AcceptingVisionGateway(),
    )

    result = parser.parse(
        simple_pdf,
        "verified.pdf",
        profile=ProcessingProfile.BALANCED,
        segmentation=SegmentationMode.OFF,
    )

    content = [
        result.tree.nodes[node_id]
        for page in result.tree.pages
        for node_id in page.content_node_ids
    ]
    paragraph = next(node for node in content if node.text == "Grounded source paragraph.")
    assert paragraph.verification_state is VerificationState.VERIFIED
    assert paragraph.grounding is not None
    assert paragraph.grounding.crop_ref in result.assets
    assert "Grounded source paragraph." in result.llm_markdown
    assert [run.stage for run in result.tree.model_runs] == [
        "page_draft",
        "page_inspection",
    ]


def test_fast_pipeline_marks_single_model_text_unresolved_in_strict_export(simple_pdf) -> None:
    parser = DocumentParser(
        ParserConfig(
            enable_paddle=False,
            enable_glm=False,
            enable_openai=True,
            render_dpi=72,
        ),
        gateway_factory=lambda config: AcceptingVisionGateway(),
    )

    result = parser.parse(
        simple_pdf,
        "draft.pdf",
        profile=ProcessingProfile.FAST,
        segmentation=SegmentationMode.OFF,
    )

    assert "Grounded source paragraph." in result.markdown
    assert "Grounded source paragraph." not in result.llm_markdown
    assert "[UNRESOLVED" in result.llm_markdown
    assert "verification=grounded" in result.llm_markdown


def test_balanced_pipeline_resolves_crop_request_with_450_dpi_evidence(simple_pdf) -> None:
    gateway = CropInspectingGateway()
    parser = DocumentParser(
        ParserConfig(
            enable_paddle=False,
            enable_glm=False,
            enable_openai=True,
            render_dpi=72,
        ),
        gateway_factory=lambda config: gateway,
    )

    result = parser.parse(
        simple_pdf,
        "crop.pdf",
        profile=ProcessingProfile.BALANCED,
        segmentation=SegmentationMode.OFF,
    )

    paragraph = next(
        result.tree.nodes[node_id]
        for page in result.tree.pages
        for node_id in page.content_node_ids
        if result.tree.nodes[node_id].text == "Grounded source paragraph."
    )
    assert paragraph.verification_state is VerificationState.VERIFIED
    assert gateway.crop_sizes[0][0] > 1_800
    assert any(path.startswith("assets/inspection/") for path in result.assets)
    assert [run.stage for run in result.tree.model_runs] == [
        "page_draft",
        "page_inspection",
        "crop_inspection",
    ]
