from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from grounded_docparse.config import AnalysisThresholds, ParserConfig
from grounded_docparse.ingest import PageEvidence
from grounded_docparse.local_ocr import GlmRegion
from grounded_docparse.models import PageComplexity, ReadingOrderStatus
from grounded_docparse.page_analysis import PageAnalyzer, draft_from_analysis
from grounded_docparse.pipeline import _page_recovery_candidates


class Runtime:
    def __init__(self, regions: list[GlmRegion]) -> None:
        self.regions = regions
        self.calls = 0

    def parse(self, _path: Path) -> list[GlmRegion]:
        self.calls += 1
        return self.regions


def page(
    tmp_path: Path,
    *,
    size: tuple[int, int] = (1200, 1600),
    blank: bool = False,
    dpi: float | None = 200,
) -> PageEvidence:
    path = tmp_path / "page.png"
    image = Image.new("RGB", size, "white")
    if not blank:
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 100, size[0] - 100, 180), fill="black")
    image.save(path)
    return PageEvidence(
        number=1,
        width=float(size[0]),
        height=float(size[1]),
        dpi=200,
        image_path=path,
        render_width_pixels=size[0],
        render_height_pixels=size[1],
        effective_dpi=dpi,
        source_width=float(size[0]),
        source_height=float(size[1]),
    )


def analyzer(runtime: Runtime, **thresholds: object) -> PageAnalyzer:
    config = ParserConfig(analysis_thresholds=AnalysisThresholds(**thresholds))
    return PageAnalyzer(config, runtime_factory=lambda *_args: runtime)


def analyze(runtime: Runtime, evidence: PageEvidence, **thresholds: object):
    return next(analyzer(runtime, **thresholds).analyze_window([evidence]))


def test_blank_page_skips_glm(tmp_path: Path) -> None:
    runtime = Runtime([])
    result = analyze(runtime, page(tmp_path, blank=True))
    assert result.complexity is PageComplexity.BLANK_PAGE
    assert runtime.calls == 0


def test_rotated_and_skewed_regions_keep_provenance_and_null_ocr_confidence(
    tmp_path: Path,
) -> None:
    runtime = Runtime(
        [
            GlmRegion(
                0, "vertical_text", "Vertical", (100, 100, 300, 900), confidence=0.91
            ),
            GlmRegion(
                1, "text", "Skew", (400, 100, 900, 300), ((400, 100), (900, 120))
            ),
        ]
    )
    result = analyze(
        runtime,
        page(tmp_path),
        min_edge_variance=0,
        min_contrast_range=0,
        clipping_border_ratio=1,
    )
    assert result.features.rotated_regions == ["p1-analysis-1", "p1-analysis-2"]
    assert result.regions[0].layout_confidence == 0.91
    assert result.regions[0].ocr_confidence is None
    assert result.regions[0].bbox.source_page == 1


def test_low_resolution_scan(tmp_path: Path) -> None:
    runtime = Runtime([GlmRegion(0, "text", "Text", (10, 10, 300, 100))])
    result = analyze(
        runtime,
        page(tmp_path, size=(600, 800), dpi=72),
        min_edge_variance=0,
        min_contrast_range=0,
        clipping_border_ratio=1,
    )
    assert result.complexity is PageComplexity.LOW_QUALITY_SCAN
    assert "effective_resolution" in result.quality.warnings


def test_multi_column_order_is_explicitly_ambiguous(tmp_path: Path) -> None:
    regions = [
        GlmRegion(0, "text", "Left alpha", (50, 100, 500, 200)),
        GlmRegion(1, "text", "Right alpha", (700, 100, 1150, 200)),
        GlmRegion(2, "text", "Left beta", (50, 300, 500, 400)),
        GlmRegion(3, "text", "Right beta", (700, 300, 1150, 400)),
    ]
    evidence = page(tmp_path)
    result = analyze(
        Runtime(regions),
        evidence,
        min_edge_variance=0,
        min_contrast_range=0,
        clipping_border_ratio=1,
    )
    assert result.reading_order.status is ReadingOrderStatus.AMBIGUOUS
    assert not result.reading_order.ordered_region_ids
    assert result.complexity is PageComplexity.COMPLEX_LAYOUT
    candidates = _page_recovery_candidates(evidence, result)
    reading_order_candidates = [
        candidate
        for candidate in candidates
        if candidate.target_id in {f"p1-b{i}" for i in range(1, 5)}
    ]
    assert reading_order_candidates == []


def test_table_form_and_visual_complexity(tmp_path: Path) -> None:
    common = {
        "min_edge_variance": 0,
        "min_contrast_range": 0,
        "clipping_border_ratio": 1,
    }
    table = analyze(
        Runtime([GlmRegion(0, "table", "A | B", (0, 200, 1200, 1000))]),
        page(tmp_path),
        **common,
    )
    form = analyze(
        Runtime([GlmRegion(0, "text", "Name:\nDate:\nID:", (0, 200, 1200, 1000))]),
        page(tmp_path),
        **common,
    )
    visual = analyze(
        Runtime([GlmRegion(0, "image", "", (0, 200, 1200, 1200))]),
        page(tmp_path),
        **common,
    )
    assert table.complexity is PageComplexity.TABLE_OR_FORM_HEAVY
    assert form.complexity is PageComplexity.TABLE_OR_FORM_HEAVY
    assert visual.complexity is PageComplexity.VISUAL_HEAVY


def test_glm_analysis_draft_omits_bbox_unit(tmp_path: Path) -> None:
    analysis = analyze(
        Runtime([GlmRegion(0, "text", "Grounded text", (120, 160, 1080, 320))]),
        page(tmp_path),
        min_edge_variance=0,
        min_contrast_range=0,
        clipping_border_ratio=1,
    )

    draft = draft_from_analysis(analysis)

    assert draft.regions[0].bbox is not None
    assert draft.regions[0].bbox.model_dump() == {
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.9,
        "y1": 0.2,
    }
    assert draft.regions[0].atoms[0].bbox == draft.regions[0].bbox


def test_recovery_uses_real_ocr_confidence_when_available(tmp_path: Path) -> None:
    evidence = page(tmp_path)
    result = analyze(
        Runtime([GlmRegion(0, "text", "Readable content", (100, 100, 1100, 200))]),
        evidence,
        min_edge_variance=0,
        min_contrast_range=0,
        clipping_border_ratio=1,
    )
    assert result.regions[0].ocr_confidence is None
    assert not any(
        "low_ocr_confidence" in candidate.reasons
        for candidate in _page_recovery_candidates(evidence, result)
    )

    result.regions[0].ocr_confidence = 0.54
    candidates = _page_recovery_candidates(evidence, result)
    assert any("low_ocr_confidence" in candidate.reasons for candidate in candidates)
