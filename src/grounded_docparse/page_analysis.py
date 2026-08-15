from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from html.parser import HTMLParser
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from .config import OcrEngine, ParserConfig
from .grounded_ocr import (
    LAYOUT_MODEL_ID,
    get_grounded_ocr_runtime,
)
from .ingest import PageEvidence
from .local_ocr import GlmPageResult, GlmRegion
from .models import (
    AnalysisEngineEvidence,
    AnalysisRegionType,
    AtomicDraft,
    BoundingBox,
    BoundingBoxProvenance,
    CheckboxState,
    CoordinateBox,
    DetectedPageFeatures,
    LayoutRegionEvidence,
    NodeType,
    PageAnalysis,
    PageComplexity,
    PageDraft,
    PageRenderEvidence,
    QualityMeasurement,
    ReadingOrderEvidence,
    ReadingOrderStatus,
    RegionComplexity,
    RegionDraft,
    ScanQualityEvidence,
    TableCellDraft,
)
from .paddle_ocr import get_paddleocr_runtime
from .rapidocr_runtime import get_docling_rapidocr_runtime

_TABLE = {"table"}
_FORMULA = {"display_formula", "inline_formula", "formula"}
_VISUAL = {"image", "chart", "figure"}
_ROTATED = {"vertical_text", "rotated_text"}
_TEXT = {
    "text",
    "title",
    "doc_title",
    "paragraph_title",
    "paragraph",
    "header",
    "footer",
    "caption",
    "figure_title",
    "list",
    "reference",
    "reference_content",
    "abstract",
    "content",
    "vision_footnote",
    "footnote",
    "seal",
    "formula_number",
}


def _percentile(histogram: list[int], fraction: float) -> int:
    target, running = sum(histogram) * fraction, 0
    for value, count in enumerate(histogram):
        running += count
        if running >= target:
            return value
    return 255


def _dense_form_order(regions: list[LayoutRegionEvidence]) -> list[str]:
    def box(region: LayoutRegionEvidence) -> BoundingBox:
        return region.bbox.normalized

    def spatial_key(region: LayoutRegionEvidence) -> tuple[float, float]:
        return round(box(region).y0, 2), box(region).x0

    margins = [
        region
        for region in regions
        if box(region).x1 <= 0.2
        and box(region).y1 - box(region).y0 >= 0.08
        and box(region).y1 - box(region).y0 > 2 * (box(region).x1 - box(region).x0)
    ]
    body = sorted(
        (region for region in regions if region not in margins),
        key=lambda region: (box(region).y0, box(region).x0),
    )

    top: list[LayoutRegionEvidence] = []
    rest = body
    if body:
        bottom = box(body[0]).y1
        for index, region in enumerate(body[1:], 1):
            if index >= 4 and box(region).y0 - bottom >= 0.02:
                top, rest = body[:index], body[index:]
                break
            bottom = max(bottom, box(region).y1)

    components: list[list[LayoutRegionEvidence]] = []
    component_right = 0.0
    for region in sorted(top, key=lambda item: box(item).x0):
        if not components or box(region).x0 > component_right + 0.01:
            components.append([region])
            component_right = box(region).x1
        else:
            components[-1].append(region)
            component_right = max(component_right, box(region).x1)
    ordered_top = [
        region
        for component in components
        for region in sorted(component, key=spatial_key)
    ]

    trailing = [region for region in rest if box(region).y0 >= 0.92]
    main = [region for region in rest if box(region).y0 < 0.92]
    ordered = [
        *ordered_top,
        *sorted(main, key=spatial_key),
        *sorted(margins, key=spatial_key),
        *sorted(trailing, key=spatial_key),
    ]
    return [region.id for region in ordered]


class PageAnalyzer:
    def __init__(
        self,
        config: ParserConfig,
        runtime_factory: Callable[..., object] | None = None,
    ) -> None:
        self.config = config
        self.runtime_factory = runtime_factory

    @property
    def engine_name(self) -> str:
        return self.config.ocr_engine.label

    def _runtime(self):
        if self.runtime_factory is None:
            if self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6:
                return get_paddleocr_runtime(
                    self.config.paddleocr_service_url,
                    self.config.paddleocr_timeout_seconds,
                )
            if self.config.ocr_engine is OcrEngine.RAPIDOCR:
                return get_docling_rapidocr_runtime()
            return get_grounded_ocr_runtime(self.config)
        if self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6:
            return self.runtime_factory(
                self.config.paddleocr_service_url,
                self.config.paddleocr_timeout_seconds,
            )
        if self.config.ocr_engine is OcrEngine.GLM_OCR:
            return self.runtime_factory(
                self.config.glmocr_config_path, self.config.glmocr_layout_device
            )
        if self.config.ocr_engine is OcrEngine.RAPIDOCR:
            return self.runtime_factory()
        return self.runtime_factory(self.config)

    def prepare_document(self, source_path: Path, pages: list[PageEvidence]) -> None:
        if self.config.ocr_engine is not OcrEngine.PADDLEOCR_VL_1_6:
            return
        runtime = self._runtime()
        parser = getattr(runtime, "parse_document", None)
        if not callable(parser):
            raise TypeError("PaddleOCR runtime does not support document parsing")
        parser(source_path, pages)

    def model_versions(self) -> dict[str, str]:
        if self.config.ocr_engine is OcrEngine.RAPIDOCR:
            return {
                "ocr_sdk": "Docling + RapidOCR",
                "ocr_model": "RapidOCR PP-OCRv6",
                "layout_model": "Docling layout",
                "vlm_backend": "ONNX Runtime CPU",
                "ai_model": self.config.cloud_model.value,
            }
        if self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6:
            return {
                "ocr_sdk": "PaddleOCR/PaddleX service",
                "ocr_model": "PaddleOCR-VL-1.6-0.9B",
                "layout_model": "PP-DocLayoutV3",
                "vlm_backend": "vLLM",
                "ai_model": self.config.cloud_model.value,
            }
        return {
            "ocr_sdk": "grounded-docparse",
            "ocr_model": (
                "zai-org/GLM-OCR"
                if self.config.ocr_engine is OcrEngine.GLM_OCR
                else self.config.ollama_model
            ),
            "layout_model": LAYOUT_MODEL_ID,
            "vlm_backend": (
                "vLLM" if self.config.ocr_engine is OcrEngine.GLM_OCR else "Ollama"
            ),
            "ai_model": self.config.cloud_model.value,
        }

    def analyze_window(self, pages: list[PageEvidence]):
        started = {page.image_path.resolve(): time.perf_counter() for page in pages}
        prepared: dict[
            Path, tuple[PageEvidence, PageRenderEvidence, ScanQualityEvidence]
        ] = {}
        for page in pages:
            render, quality = self._base(page)
            if quality.blank:
                yield self._finish(
                    page, render, quality, [], started[page.image_path.resolve()]
                )
            else:
                prepared[page.image_path.resolve()] = (page, render, quality)
        if not prepared:
            return
        if not self.config.local_ocr_enabled:
            for page, render, quality in prepared.values():
                yield self._finish(
                    page,
                    render,
                    quality,
                    [],
                    started[page.image_path.resolve()],
                    f"{self.engine_name} disabled; page analysis uncertain",
                )
            return
        try:
            runtime = self._runtime()
            if hasattr(runtime, "parse_many"):
                results = runtime.parse_many(
                    [item[0].image_path for item in prepared.values()]
                )
            else:
                results = (
                    GlmPageResult(page.image_path, runtime.parse(page.image_path))
                    for page, _render, _quality in prepared.values()
                )
            for result in results:
                item = prepared.pop(result.image_path.resolve(), None)
                if item is None:
                    continue
                page, render, quality = item
                warning = (
                    f"{self.engine_name} analysis unavailable: {result.error}"
                    if result.error
                    else None
                )
                recognition_attempts = sum(
                    region.recognition_attempted for region in result.regions
                )
                recognition_failures = sum(
                    region.recognition_failed for region in result.regions
                )
                if recognition_failures:
                    recognition_warning = (
                        f"{self.engine_name} recognition failed for "
                        f"{recognition_failures} of {recognition_attempts} OCR regions"
                    )
                    warning = (
                        f"{warning}; {recognition_warning}"
                        if warning
                        else recognition_warning
                    )
                yield self._finish(
                    page,
                    render,
                    quality,
                    result.regions,
                    started[page.image_path.resolve()],
                    warning,
                )
        except Exception as exc:
            if self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6:
                raise
            warning = f"{self.engine_name} analysis unavailable: {type(exc).__name__}: {exc}"
            for page, render, quality in prepared.values():
                yield self._finish(
                    page,
                    render,
                    quality,
                    [],
                    started[page.image_path.resolve()],
                    warning,
                )
            return
        for page, render, quality in prepared.values():
            yield self._finish(
                page,
                render,
                quality,
                [],
                started[page.image_path.resolve()],
                f"{self.engine_name} returned no result for page",
            )

    def _base(
        self, page: PageEvidence
    ) -> tuple[PageRenderEvidence, ScanQualityEvidence]:
        render = PageRenderEvidence(
            render_width_pixels=page.render_width_pixels,
            render_height_pixels=page.render_height_pixels,
            render_dpi=float(page.dpi),
            effective_dpi=page.effective_dpi,
            source_page=page.number,
            source_width=page.source_width,
            source_height=page.source_height,
            source_unit=page.source_unit,
            source_rotation_degrees=page.source_rotation_degrees,
        )
        return render, self._quality(page)

    def _finish(
        self, page, render, quality, raw, started, warning=None
    ) -> PageAnalysis:
        paddle = self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6
        ollama = self.config.ocr_engine is OcrEngine.OLLAMA
        rapidocr = self.config.ocr_engine is OcrEngine.RAPIDOCR
        engine = AnalysisEngineEvidence(
            sdk=(
                "paddleocr"
                if paddle
                else "docling+rapidocr"
                if rapidocr
                else "grounded-docparse"
            ),
            sdk_version=None,
            layout_model=(
                "Docling layout"
                if rapidocr
                else "PP-DocLayoutV3"
                if paddle
                else "PaddlePaddle/PP-DocLayoutV3_safetensors"
            ),
            ocr_model=(
                "RapidOCR PP-OCRv6"
                if rapidocr
                else "PaddleOCR-VL-1.6-0.9B"
                if paddle
                else self.config.ollama_model
                if ollama
                else "zai-org/GLM-OCR"
            ),
            layout_device="cpu",
        )
        if quality.blank:
            engine.latency_ms = round((time.perf_counter() - started) * 1000)
            return PageAnalysis(
                render=render,
                quality=quality,
                complexity=PageComplexity.BLANK_PAGE,
                engine=engine,
            )
        regions = [
            self._region(page, item, position) for position, item in enumerate(raw, 1)
        ]
        skew = max(
            (
                abs(region.rotation_degrees)
                for region in regions
                if region.type is not AnalysisRegionType.ROTATED_TEXT
            ),
            default=0.0,
        )
        quality.measurements.append(
            QualityMeasurement(
                code="skew_degrees",
                value=skew,
                threshold=self.config.analysis_thresholds.skew_degrees,
                warning=skew >= self.config.analysis_thresholds.skew_degrees,
                basis=f"largest non-vertical {self.engine_name} region baseline angle",
            )
        )
        if quality.measurements[-1].warning:
            quality.warnings.append("skew_degrees")
        features = self._features(regions)
        reading_order = self._reading_order(regions, features.multi_column_clusters)
        complexity = self._complexity(page, quality, regions, features)
        engine.latency_ms = round((time.perf_counter() - started) * 1000)
        return PageAnalysis(
            render=render,
            quality=quality,
            regions=regions,
            reading_order=reading_order,
            features=features,
            complexity=complexity,
            engine=engine,
            warnings=[warning] if warning else [],
        )

    def _quality(self, page: PageEvidence) -> ScanQualityEvidence:
        threshold = self.config.analysis_thresholds
        with Image.open(page.image_path) as source:
            gray = source.convert("L")
            if gray.width > 1600:
                gray = gray.resize(
                    (1600, max(1, round(gray.height * 1600 / gray.width)))
                )
        histogram = gray.histogram()
        total = gray.width * gray.height
        foreground = sum(histogram[:245]) / total
        contrast = float(_percentile(histogram, 0.95) - _percentile(histogram, 0.05))
        edge_variance = float(
            ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
        )
        border = max(1, min(gray.size) // 100)
        border_image = Image.new("L", gray.size, 255)
        border_image.paste(gray.crop((0, 0, gray.width, border)), (0, 0))
        border_image.paste(
            gray.crop((0, gray.height - border, gray.width, gray.height)),
            (0, gray.height - border),
        )
        border_image.paste(gray.crop((0, 0, border, gray.height)), (0, 0))
        border_image.paste(
            gray.crop((gray.width - border, 0, gray.width, gray.height)),
            (gray.width - border, 0),
        )
        border_foreground = sum(border_image.histogram()[:245]) / max(
            1, sum(histogram[:245])
        )
        low_resolution_value = page.effective_dpi or min(
            page.render_width_pixels, page.render_height_pixels
        )
        low_resolution_threshold = (
            threshold.min_effective_dpi
            if page.effective_dpi
            else threshold.min_short_edge_pixels
        )
        measurements = [
            QualityMeasurement(
                code="foreground_ratio",
                value=foreground,
                threshold=threshold.blank_foreground_ratio,
                warning=foreground <= threshold.blank_foreground_ratio,
                basis="fraction of grayscale pixels below 245",
            ),
            QualityMeasurement(
                code="edge_variance",
                value=edge_variance,
                threshold=threshold.min_edge_variance,
                warning=edge_variance < threshold.min_edge_variance,
                basis="variance after Pillow FIND_EDGES; lower means blur",
            ),
            QualityMeasurement(
                code="contrast_range",
                value=contrast,
                threshold=threshold.min_contrast_range,
                warning=contrast < threshold.min_contrast_range,
                basis="grayscale p95 minus p05",
            ),
            QualityMeasurement(
                code="border_foreground_ratio",
                value=border_foreground,
                threshold=threshold.clipping_border_ratio,
                warning=border_foreground > threshold.clipping_border_ratio,
                basis="foreground touching outer 1% border",
            ),
            QualityMeasurement(
                code="effective_resolution",
                value=float(low_resolution_value),
                threshold=float(low_resolution_threshold),
                warning=low_resolution_value < low_resolution_threshold,
                basis="DPI when known, otherwise shortest rendered edge pixels",
            ),
        ]
        warnings = [item.code for item in measurements[1:] if item.warning]
        return ScanQualityEvidence(
            blank=measurements[0].warning, measurements=measurements, warnings=warnings
        )

    def _region(
        self, page: PageEvidence, raw: GlmRegion, position: int
    ) -> LayoutRegionEvidence:
        width, height = page.render_width_pixels, page.render_height_pixels
        x0, y0, x1, y1 = raw.bbox
        scale = 1.0 if max(raw.bbox) <= 1.0 else 1000.0
        x0, x1 = sorted(
            (
                max(0.0, min(1.0, x0 / scale)),
                max(0.0, min(1.0, x1 / scale)),
            )
        )
        y0, y1 = sorted(
            (
                max(0.0, min(1.0, y0 / scale)),
                max(0.0, min(1.0, y1 / scale)),
            )
        )
        normalized = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
        polygon_rendered = [
            (point_x / scale * width, point_y / scale * height)
            for point_x, point_y in raw.polygon
        ]
        label = raw.label.casefold()
        region_type = (
            AnalysisRegionType.TABLE
            if label in _TABLE
            else AnalysisRegionType.FORMULA
            if label in _FORMULA
            else AnalysisRegionType.FIGURE
            if label in _VISUAL
            else AnalysisRegionType.ROTATED_TEXT
            if label in _ROTATED
            else AnalysisRegionType.TEXT
            if label in _TEXT
            else AnalysisRegionType.UNKNOWN
        )
        if region_type is AnalysisRegionType.TEXT and (
            raw.content.count(":") >= 2
            or any(mark in raw.content for mark in ("☐", "☑", "□", "✓"))
        ):
            region_type = AnalysisRegionType.FORM
        rotation = 90.0 if label in _ROTATED else 0.0
        if len(polygon_rendered) >= 2:
            rotation = math.degrees(
                math.atan2(
                    polygon_rendered[1][1] - polygon_rendered[0][1],
                    polygon_rendered[1][0] - polygon_rendered[0][0],
                )
            )
        complexity = (
            RegionComplexity.STRUCTURED
            if region_type
            in {
                AnalysisRegionType.TABLE,
                AnalysisRegionType.FORM,
                AnalysisRegionType.FORMULA,
            }
            else RegionComplexity.VISUAL
            if region_type is AnalysisRegionType.FIGURE
            else RegionComplexity.ROTATED
            if abs(rotation) >= self.config.analysis_thresholds.skew_degrees
            else RegionComplexity.SIMPLE_TEXT
        )
        return LayoutRegionEvidence(
            id=f"p{page.number}-analysis-{position}",
            native_label=raw.label,
            type=region_type,
            bbox=BoundingBoxProvenance(
                normalized=normalized,
                rendered=CoordinateBox(
                    x0=x0 * width,
                    y0=y0 * height,
                    x1=x1 * width,
                    y1=y1 * height,
                    unit="pixels",
                ),
                source=CoordinateBox(
                    x0=normalized.x0 * page.source_width,
                    y0=normalized.y0 * page.source_height,
                    x1=normalized.x1 * page.source_width,
                    y1=normalized.y1 * page.source_height,
                    unit=page.source_unit,
                ),
                source_page=page.number,
            ),
            polygon_rendered=polygon_rendered,
            text=raw.content,
            layout_confidence=raw.confidence,
            ocr_confidence=None,
            rotation_degrees=rotation,
            complexity=complexity,
        )

    def _features(self, regions: list[LayoutRegionEvidence]) -> DetectedPageFeatures:
        ids = lambda kind: [region.id for region in regions if region.type is kind]
        left = [r.id for r in regions if r.bbox.normalized.x1 <= 0.55]
        right = [r.id for r in regions if r.bbox.normalized.x0 >= 0.45]
        columns = [left, right] if len(left) >= 2 and len(right) >= 2 else []
        return DetectedPageFeatures(
            tables=ids(AnalysisRegionType.TABLE),
            forms=ids(AnalysisRegionType.FORM),
            figures=ids(AnalysisRegionType.FIGURE),
            formulas=ids(AnalysisRegionType.FORMULA),
            multi_column_clusters=columns,
            rotated_regions=[
                r.id
                for r in regions
                if abs(r.rotation_degrees)
                >= self.config.analysis_thresholds.skew_degrees
            ],
        )

    def _reading_order(
        self, regions: list[LayoutRegionEvidence], columns: list[list[str]]
    ) -> ReadingOrderEvidence:
        if not regions:
            return ReadingOrderEvidence(
                basis=f"{self.engine_name} returned no layout regions"
            )
        order = [r.id for r in regions]
        if self.config.ocr_engine in {
            OcrEngine.PADDLEOCR_VL_1_6,
            OcrEngine.GLM_OCR,
            OcrEngine.OLLAMA,
            OcrEngine.RAPIDOCR,
        }:
            return ReadingOrderEvidence(
                status=ReadingOrderStatus.CONFIDENT,
                ordered_region_ids=order,
                confidence=1.0,
                basis=(
                    "Docling document order"
                    if self.config.ocr_engine is OcrEngine.RAPIDOCR
                    else "PaddleOCR block_order"
                    if self.config.ocr_engine is OcrEngine.PADDLEOCR_VL_1_6
                    else "PP-DocLayoutV3 detector order"
                ),
            )
        if columns:
            membership = {
                region_id: index
                for index, group in enumerate(columns)
                for region_id in group
            }
            sequence = [membership[item] for item in order if item in membership]
            switches = sum(a != b for a, b in pairwise(sequence))
            if switches > 1:
                colon_regions = sum(":" in region.text for region in regions)
                short_regions = sum(len(region.text) < 100 for region in regions)
                dense_form = (
                    len(regions) >= 12
                    and colon_regions >= 8
                    and short_regions / len(regions) >= 0.75
                )
                return ReadingOrderEvidence(
                    status=ReadingOrderStatus.AMBIGUOUS,
                    ordered_region_ids=(
                        _dense_form_order(regions) if dense_form else []
                    ),
                    confidence=0.75 if dense_form else None,
                    ambiguous_groups=columns,
                    basis=(
                        "deterministic dense-form spatial order"
                        if dense_form
                        else "GLM order alternates between detected columns"
                    ),
                )
        return ReadingOrderEvidence(
            status=ReadingOrderStatus.CONFIDENT,
            ordered_region_ids=order,
            confidence=1.0,
            basis="GLM region index agrees with deterministic column check",
        )

    def _complexity(
        self,
        page: PageEvidence,
        quality: ScanQualityEvidence,
        regions: list[LayoutRegionEvidence],
        features: DetectedPageFeatures,
    ) -> PageComplexity:
        if quality.warnings:
            return PageComplexity.LOW_QUALITY_SCAN
        if not regions:
            return PageComplexity.UNCERTAIN
        area = lambda ids: sum(
            (r.bbox.normalized.x1 - r.bbox.normalized.x0)
            * (r.bbox.normalized.y1 - r.bbox.normalized.y0)
            for r in regions
            if r.id in ids
        )
        threshold = self.config.analysis_thresholds
        if area(features.tables + features.forms) >= threshold.table_form_area_ratio:
            return PageComplexity.TABLE_OR_FORM_HEAVY
        if area(features.figures) >= threshold.visual_area_ratio:
            return PageComplexity.VISUAL_HEAVY
        unknown = [
            region.id for region in regions if region.type is AnalysisRegionType.UNKNOWN
        ]
        if area(unknown) >= threshold.unknown_area_ratio:
            return PageComplexity.UNCERTAIN
        if (
            features.multi_column_clusters
            or features.formulas
            or features.rotated_regions
            or len(regions) >= threshold.complex_region_count
        ):
            return PageComplexity.COMPLEX_LAYOUT
        return (
            PageComplexity.SIMPLE_TEXT_PAGE
            if len(regions) == 1
            else PageComplexity.SIMPLE_TEXT_REGIONS
        )


_HEADING_LABELS = {"doc_title", "paragraph_title", "title"}
_CAPTION_LABELS = {"figure_title", "caption", "formula_number"}
_REFERENCE_LABELS = {"reference", "reference_content"}
_FOOTNOTE_LABELS = {"footnote", "vision_footnote"}
_LIST_MARKER = re.compile(r"^\s*((?:[-*•]|\d+[.)]|[A-Za-z][.)]))\s+(.*)$", re.DOTALL)
_TASK_MARKER = re.compile(r"^\s*\[([ xX])\]\s*(.*)$", re.DOTALL)


def draft_from_analysis(analysis: PageAnalysis) -> PageDraft:
    regions: list[RegionDraft] = []
    by_id = {region.id: region for region in analysis.regions}
    ordered_sources = [
        by_id[region_id]
        for region_id in analysis.reading_order.ordered_region_ids
        if region_id in by_id
    ]
    ordered_ids = {region.id for region in ordered_sources}
    ordered_sources.extend(
        region for region in analysis.regions if region.id not in ordered_ids
    )
    for order, source in enumerate(ordered_sources):
        label = source.native_label.casefold()
        node_type = NodeType.PARAGRAPH
        heading_level = None
        if label in _HEADING_LABELS:
            node_type = NodeType.HEADING
            heading_level = 1 if label == "doc_title" else 2
        elif label == "table":
            node_type = NodeType.TABLE
        elif label in _FORMULA:
            node_type = NodeType.FORMULA
        elif label == "chart":
            node_type = NodeType.CHART
        elif label in {"image", "figure"}:
            node_type = NodeType.IMAGE
        elif label == "seal":
            node_type = NodeType.SEAL
        elif label in _CAPTION_LABELS:
            node_type = NodeType.CAPTION
        elif label in _REFERENCE_LABELS:
            node_type = NodeType.REFERENCE
        elif label in _FOOTNOTE_LABELS:
            node_type = NodeType.FOOTNOTE
        elif label == "header":
            node_type = NodeType.HEADER
        elif label == "footer":
            node_type = NodeType.FOOTER
        text = source.text
        task = _TASK_MARKER.match(text)
        if task:
            checkbox_state = (
                CheckboxState.CHECKED
                if task.group(1).casefold() == "x"
                else CheckboxState.UNCHECKED
            )
            node_type = NodeType.CHECKBOX
            text = task.group(2)
        else:
            checkbox_state = None
        marker = _LIST_MARKER.match(text)
        list_marker = None
        if marker and checkbox_state is None:
            node_type, list_marker, text = (
                NodeType.LIST_ITEM,
                marker.group(1),
                marker.group(2),
            )
        if checkbox_state is None and text.lstrip().startswith(("☐", "□", "☑", "✓")):
            glyph = text.lstrip()[0]
            checkbox_state = (
                CheckboxState.CHECKED
                if glyph in {"☑", "✓"}
                else CheckboxState.UNCHECKED
            )
            node_type = NodeType.CHECKBOX
            text = text.lstrip()[1:].lstrip()
        bbox = source.bbox.normalized.model_dump(exclude={"unit"})
        table_cells = _markdown_table_cells(text) if node_type is NodeType.TABLE else []
        regions.append(
            RegionDraft(
                type=node_type,
                bbox=bbox,
                reading_order=order,
                text=text,
                confidence=source.ocr_confidence,
                heading_level=heading_level,
                list_marker=list_marker,
                checkbox_state=checkbox_state,
                table_cells=table_cells,
                atoms=[
                    AtomicDraft(
                        kind="text",
                        text=text,
                        bbox=bbox,
                        confidence=source.ocr_confidence,
                    )
                ]
                if text
                else [],
            )
        )
    return PageDraft(regions=regions, warnings=list(analysis.warnings))


def _markdown_table_cells(text: str) -> list[TableCellDraft]:
    if re.search(r"<table\b", text, re.IGNORECASE):
        return _html_table_cells(text)
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if "|" in line
    ]
    if len(rows) < 2:
        return []
    separator = re.compile(r"^:?-{3,}:?$")
    has_header = all(separator.fullmatch(cell.replace(" ", "")) for cell in rows[1])
    if has_header:
        rows.pop(1)
    return [
        TableCellDraft(
            row_index=row_index,
            column_index=column_index,
            text=cell,
            header=has_header and row_index == 0,
        )
        for row_index, row in enumerate(rows)
        for column_index, cell in enumerate(row)
    ]


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int, int, bool]]] = []
        self._row: list[tuple[str, int, int, bool]] | None = None
        self._cell: list[str] | None = None
        self._row_span = 1
        self._column_span = 1
        self._header = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.casefold()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            if self._row is None:
                self._row = []
            attributes = {name.casefold(): value for name, value in attrs}
            self._cell = []
            self._row_span = _positive_span(attributes.get("rowspan"))
            self._column_span = _positive_span(attributes.get("colspan"))
            self._header = tag == "th"
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"td", "th"} and self._cell is not None:
            assert self._row is not None
            self._row.append(
                (
                    " ".join("".join(self._cell).split()),
                    self._row_span,
                    self._column_span,
                    self._header,
                )
            )
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _positive_span(value: str | None) -> int:
    try:
        return max(1, int(value or "1"))
    except ValueError:
        return 1


def _html_table_cells(text: str) -> list[TableCellDraft]:
    parser = _TableHTMLParser()
    try:
        parser.feed(text)
        parser.close()
    except (AssertionError, ValueError):
        return []
    occupied: set[tuple[int, int]] = set()
    cells: list[TableCellDraft] = []
    for row_index, row in enumerate(parser.rows):
        column_index = 0
        for value, row_span, column_span, header in row:
            while (row_index, column_index) in occupied:
                column_index += 1
            cells.append(
                TableCellDraft(
                    row_index=row_index,
                    column_index=column_index,
                    text=value,
                    row_span=row_span,
                    column_span=column_span,
                    header=header,
                )
            )
            for occupied_row in range(row_index, row_index + row_span):
                for occupied_column in range(
                    column_index, column_index + column_span
                ):
                    occupied.add((occupied_row, occupied_column))
            column_index += column_span
    return cells
