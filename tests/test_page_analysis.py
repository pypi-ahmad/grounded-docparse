from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from grounded_docparse.config import AnalysisThresholds, ParserConfig
from grounded_docparse.ingest import PageEvidence
from grounded_docparse.local_ocr import GlmRegion
from grounded_docparse.models import PageComplexity, ReadingOrderStatus
from grounded_docparse.page_analysis import PageAnalyzer, draft_from_analysis


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


def test_blank_page_skips_glm(tmp_path: Path) -> None:
    runtime = Runtime([])
    result = analyzer(runtime).analyze(page(tmp_path, blank=True))
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
    result = analyzer(
        runtime, min_edge_variance=0, min_contrast_range=0, clipping_border_ratio=1
    ).analyze(page(tmp_path))
    assert result.features.rotated_regions == ["p1-analysis-1", "p1-analysis-2"]
    assert result.regions[0].layout_confidence == 0.91
    assert result.regions[0].ocr_confidence is None
    assert result.regions[0].bbox.source_page == 1


def test_low_resolution_scan(tmp_path: Path) -> None:
    runtime = Runtime([GlmRegion(0, "text", "Text", (10, 10, 300, 100))])
    result = analyzer(
        runtime, min_edge_variance=0, min_contrast_range=0, clipping_border_ratio=1
    ).analyze(page(tmp_path, size=(600, 800), dpi=72))
    assert result.complexity is PageComplexity.LOW_QUALITY_SCAN
    assert "effective_resolution" in result.quality.warnings


def test_multi_column_order_is_explicitly_ambiguous(tmp_path: Path) -> None:
    regions = [
        GlmRegion(0, "text", "L1", (50, 100, 500, 200)),
        GlmRegion(1, "text", "R1", (700, 100, 1150, 200)),
        GlmRegion(2, "text", "L2", (50, 300, 500, 400)),
        GlmRegion(3, "text", "R2", (700, 300, 1150, 400)),
    ]
    result = analyzer(
        Runtime(regions),
        min_edge_variance=0,
        min_contrast_range=0,
        clipping_border_ratio=1,
    ).analyze(page(tmp_path))
    assert result.reading_order.status is ReadingOrderStatus.AMBIGUOUS
    assert not result.reading_order.ordered_region_ids
    assert result.complexity is PageComplexity.COMPLEX_LAYOUT


def test_table_form_and_visual_complexity(tmp_path: Path) -> None:
    common = {
        "min_edge_variance": 0,
        "min_contrast_range": 0,
        "clipping_border_ratio": 1,
    }
    table = analyzer(
        Runtime([GlmRegion(0, "table", "A | B", (0, 200, 1200, 1000))]), **common
    ).analyze(page(tmp_path))
    form = analyzer(
        Runtime([GlmRegion(0, "text", "Name:\nDate:\nID:", (0, 200, 1200, 1000))]),
        **common,
    ).analyze(page(tmp_path))
    visual = analyzer(
        Runtime([GlmRegion(0, "image", "", (0, 200, 1200, 1200))]), **common
    ).analyze(page(tmp_path))
    assert table.complexity is PageComplexity.TABLE_OR_FORM_HEAVY
    assert form.complexity is PageComplexity.TABLE_OR_FORM_HEAVY
    assert visual.complexity is PageComplexity.VISUAL_HEAVY


def test_glm_analysis_draft_omits_bbox_unit(tmp_path: Path) -> None:
    analysis = analyzer(
        Runtime([GlmRegion(0, "text", "Grounded text", (120, 160, 1080, 320))]),
        min_edge_variance=0,
        min_contrast_range=0,
        clipping_border_ratio=1,
    ).analyze(page(tmp_path))

    draft = draft_from_analysis(analysis)

    assert draft.regions[0].bbox is not None
    assert draft.regions[0].bbox.model_dump() == {
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.9,
        "y1": 0.2,
    }
    assert draft.regions[0].atoms[0].bbox == draft.regions[0].bbox
