from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from .audit import build_audit_json
from .config import ParserConfig
from .domain import apply_document_profile
from .extraction import (
    apply_extraction_decisions,
    build_logical_tables,
    build_table_exports,
    extract_schema_data,
    extraction_evidence,
    schema_scalar_paths,
    validate_extraction_schema,
)
from .failures import derive_failure_cases, render_failures_jsonl
from .gateways import PROMPT_VERSION, GlmOcrGateway, OpenAIDocumentGateway
from .ingest import IngestedDocument, PageEvidence, TextBlock, ingest_document
from .models import (
    AdaptiveRetryRecord,
    BatchManifest,
    BoundingBox,
    Citation,
    Confidence,
    DocumentClassification,
    DocumentLink,
    DocumentNode,
    DocumentProfile,
    DocumentResolution,
    DocumentTree,
    FormFieldData,
    GroundingScope,
    NodeType,
    PageRecord,
    ParseResult,
    ProcessingProfile,
    ProgressCallback,
    ProgressEvent,
    Provenance,
    RecognitionCandidate,
    RegionEvidence,
    Relationship,
    RunRecord,
    SchemaExtraction,
    SegmentationMode,
    SubdocumentDescriptor,
    SubdocumentResult,
    VisualAnalysis,
    VisualDataPoint,
    WindowRun,
)
from .paddle import (
    PaddleDockerRunner,
    find_paddle_regions,
    find_paddle_table_results,
    normalize_paddle_table,
)
from .render import (
    build_bundle,
    render_json,
    render_llm_markdown,
    render_markdown,
    render_node,
)
from .review import render_annotated_pdf, render_quality_json
from .segmentation import build_batch_manifest, extract_pdf_range, slice_document_tree

LABEL_MAP: dict[str, NodeType] = {
    "title": NodeType.HEADING,
    "document_title": NodeType.HEADING,
    "section_title": NodeType.HEADING,
    "paragraph_title": NodeType.HEADING,
    "heading": NodeType.HEADING,
    "text": NodeType.PARAGRAPH,
    "paragraph": NodeType.PARAGRAPH,
    "table": NodeType.TABLE,
    "figure": NodeType.FIGURE,
    "image": NodeType.IMAGE,
    "chart": NodeType.CHART,
    "chart_caption": NodeType.CAPTION,
    "figure_title": NodeType.CAPTION,
    "caption": NodeType.CAPTION,
    "table_caption": NodeType.CAPTION,
    "formula": NodeType.FORMULA,
    "list": NodeType.LIST,
    "list_item": NodeType.LIST_ITEM,
    "header": NodeType.HEADER,
    "footer": NodeType.FOOTER,
    "page_number": NodeType.FOOTER,
    "header_image": NodeType.HEADER,
    "footer_image": NodeType.FOOTER,
    "abstract": NodeType.PARAGRAPH,
    "table_of_contents": NodeType.PARAGRAPH,
    "algorithm": NodeType.PARAGRAPH,
    "seal": NodeType.SEAL,
    "signature": NodeType.SIGNATURE,
    "checkbox": NodeType.CHECKBOX,
    "check_box": NodeType.CHECKBOX,
    "sidebar": NodeType.SIDEBAR,
    "footnote": NodeType.FOOTNOTE,
    "reference": NodeType.REFERENCE,
}

COMPLEX_REGION_TYPES = {
    NodeType.TABLE.value,
    NodeType.FORMULA.value,
    NodeType.FIGURE.value,
    NodeType.IMAGE.value,
    NodeType.CHART.value,
    NodeType.CHECKBOX.value,
    NodeType.SIGNATURE.value,
    NodeType.SEAL.value,
}


def _emit(
    callback: ProgressCallback | None,
    stage: str,
    current: int,
    total: int,
    message: str,
) -> None:
    if callback:
        callback(
            ProgressEvent(stage=stage, current=current, total=total, message=message)
        )


def _node_id(
    digest: str,
    page_number: int | None,
    order: int,
    node_type: NodeType,
    bbox: BoundingBox | None,
) -> str:
    bbox_key = (
        "none"
        if bbox is None
        else ":".join(f"{value:.4f}" for value in (bbox.x0, bbox.y0, bbox.x1, bbox.y1))
    )
    raw = f"{digest}:{page_number}:{order}:{node_type.value}:{bbox_key}"
    return f"n-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _derived_id(digest: str, kind: str, seed: str) -> str:
    raw = f"{digest}:{kind}:{seed}"
    return f"n-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _words(text: str) -> list[str]:
    return re.findall(r"[\w.-]+", text.casefold(), flags=re.UNICODE)


def _support_score(text: str, evidence: str) -> float:
    tokens = _words(text)
    if not tokens:
        return 1.0
    evidence_counts = Counter(_words(evidence))
    supported = 0
    for token, count in Counter(tokens).items():
        supported += min(count, evidence_counts[token])
    return supported / len(tokens)


def _confidence(score: float, signals: dict[str, float]) -> Confidence:
    score = max(0.0, min(1.0, score))
    level = "high" if score >= 0.85 else "medium" if score >= 0.60 else "low"
    return Confidence(score=score, level=level, signals=signals)


def _bounded_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number)) if math.isfinite(number) else default


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _text_similarity(left: str, right: str) -> float:
    left_normalized = re.sub(r"\s+", "", left.casefold())
    right_normalized = re.sub(r"\s+", "", right.casefold())
    if not left_normalized or not right_normalized:
        return 1.0 if left_normalized == right_normalized else 0.0
    score = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_numbers = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", left)
    right_numbers = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", right)
    if left_numbers != right_numbers:
        score = min(score, 0.59)
    return score


def _preferred_candidate(
    region: RegionEvidence, scanned: bool
) -> RecognitionCandidate | None:
    if not region.candidates:
        return None
    if region.type == NodeType.CHECKBOX.value:
        source_order = ("glm", "paddle", "digital")
    elif scanned or region.type in COMPLEX_REGION_TYPES:
        source_order = ("glm", "digital", "paddle")
    else:
        source_order = ("digital", "glm", "paddle")
    for source in source_order:
        candidate = next(
            (item for item in reversed(region.candidates) if item.source == source),
            None,
        )
        if candidate and candidate.text.strip():
            return candidate
    return region.candidates[0]


def _bbox_from_paddle(raw: Any, page: PageEvidence) -> BoundingBox | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        values = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    if max(values) <= 1.0:
        if min(values) < 0 or values[2] < values[0] or values[3] < values[1]:
            return None
        return BoundingBox(x0=values[0], y0=values[1], x1=values[2], y1=values[3])
    with Image.open(page.image_path) as image:
        width, height = image.size
    normalized = [
        max(0, min(1, values[0] / width)),
        max(0, min(1, values[1] / height)),
        max(0, min(1, values[2] / width)),
        max(0, min(1, values[3] / height)),
    ]
    if normalized[2] < normalized[0] or normalized[3] < normalized[1]:
        return None
    return BoundingBox(
        x0=normalized[0], y0=normalized[1], x1=normalized[2], y1=normalized[3]
    )


def _cell_bbox_from_paddle(raw: Any, page: PageEvidence) -> BoundingBox | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 4 or len(raw) % 2:
        return None
    try:
        values = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    if len(values) == 4:
        box = values
    else:
        xs, ys = values[::2], values[1::2]
        box = [min(xs), min(ys), max(xs), max(ys)]
    return _bbox_from_paddle(box, page)


def _matching_block(page: PageEvidence, bbox: BoundingBox | None) -> TextBlock | None:
    if bbox is None:
        return None
    best: tuple[float, TextBlock] | None = None
    for block in page.text_blocks:
        overlap_x = max(0.0, min(bbox.x1, block.bbox.x1) - max(bbox.x0, block.bbox.x0))
        overlap_y = max(0.0, min(bbox.y1, block.bbox.y1) - max(bbox.y0, block.bbox.y0))
        overlap = overlap_x * overlap_y
        if best is None or overlap > best[0]:
            best = (overlap, block)
    return best[1] if best and best[0] > 0 else None


def _matching_node(
    tree: DocumentTree, page: PageEvidence, bbox: BoundingBox
) -> DocumentNode | None:
    record = tree.pages[page.number - 1]
    best: tuple[float, DocumentNode] | None = None
    for node_id in record.content_node_ids:
        node = tree.nodes[node_id]
        if node.bbox is None:
            continue
        overlap_x = max(0.0, min(bbox.x1, node.bbox.x1) - max(bbox.x0, node.bbox.x0))
        overlap_y = max(0.0, min(bbox.y1, node.bbox.y1) - max(bbox.y0, node.bbox.y0))
        overlap = overlap_x * overlap_y
        if best is None or overlap > best[0]:
            best = (overlap, node)
    return best[1] if best and best[0] > 0 else None


class DocumentParser:
    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config or ParserConfig.from_env()

    def parse(
        self,
        data: bytes,
        filename: str,
        progress_callback: ProgressCallback | None = None,
        *,
        profile: ProcessingProfile | str | None = None,
        document_profile: DocumentProfile | str = DocumentProfile.AUTO,
        allow_cloud: bool | None = None,
        segmentation: SegmentationMode | str = SegmentationMode.AUTO,
        extraction_schema: dict[str, Any] | None = None,
    ) -> ParseResult:
        if extraction_schema is not None:
            extraction_schema = validate_extraction_schema(extraction_schema)
        selected_profile = self._select_profile(profile, allow_cloud)
        selected_document_profile = DocumentProfile(document_profile)
        cloud_enabled = selected_profile != ProcessingProfile.LOCAL_ONLY
        if cloud_enabled and not self.config.enable_openai:
            raise ValueError("The selected processing profile requires OpenAI")
        if cloud_enabled and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required by the selected profile")
        base = Path.cwd() / ".docparse"
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="run-", dir=base) as temporary:
            workdir = Path(temporary)
            _emit(progress_callback, "ingest", 0, 1, "Validating document")
            document = ingest_document(
                data,
                filename,
                workdir,
                dpi=self.config.render_dpi,
                max_bytes=self.config.max_upload_bytes,
                max_pages=self.config.max_pages,
                max_page_pixels=self.config.max_page_pixels,
            )
            total = len(document.pages)
            _emit(progress_callback, "ingest", total, total, f"Prepared {total} pages")

            warnings: list[str] = []
            model_runs: list[RunRecord] = []
            adaptive_retries: list[AdaptiveRetryRecord] = []
            window_runs = [
                WindowRun(
                    start_page=start,
                    end_page=min(total, start + self.config.page_window_size - 1),
                    status="pending",
                )
                for start in range(1, total + 1, self.config.page_window_size)
            ]
            paddle_results: dict[int, dict[str, Any]] = {}
            if self.config.enable_paddle:
                try:
                    paddle_results = PaddleDockerRunner(self.config).run(
                        document.source_path, workdir, total, progress_callback
                    )
                except Exception as exc:  # noqa: BLE001 - provider fallback boundary
                    warnings.append(f"PaddleOCR-VL unavailable ({type(exc).__name__})")
            for page_number, payload in paddle_results.items():
                if payload.get("_provider_error"):
                    warnings.append(
                        f"Page {page_number} PaddleOCR-VL chunk fallback "
                        f"({payload['_provider_error']})"
                    )

            regions = self._initial_regions(document, paddle_results)
            if self.config.enable_paddle:
                self._adaptive_page_layout_retries(
                    document,
                    regions,
                    paddle_results,
                    workdir,
                    warnings,
                    adaptive_retries,
                    progress_callback,
                )
            glm: GlmOcrGateway | None = None
            if self.config.enable_glm:
                try:
                    glm = GlmOcrGateway(self.config)
                    self._process_glm_windows(
                        document,
                        regions,
                        glm,
                        workdir,
                        window_runs,
                        warnings,
                        model_runs,
                        progress_callback,
                    )
                    if selected_profile == ProcessingProfile.LOCAL_ONLY:
                        self._adaptive_region_retries(
                            document,
                            regions,
                            glm,
                            workdir,
                            warnings,
                            model_runs,
                            adaptive_retries,
                            progress_callback,
                        )
                except Exception as exc:  # noqa: BLE001 - provider fallback boundary
                    warnings.append(f"GLM-OCR unavailable ({type(exc).__name__})")
                    for window in window_runs:
                        window.status = "degraded"
            else:
                for page in document.pages:
                    for region in regions[page.number]:
                        self._reconcile_region(region, page.scanned)
                for window in window_runs:
                    window.status = "complete"

            openai_gateway: OpenAIDocumentGateway | None = None
            if self.config.enable_openai and cloud_enabled:
                try:
                    openai_gateway = OpenAIDocumentGateway(self.config)
                except Exception as exc:  # noqa: BLE001 - provider fallback boundary
                    warnings.append(f"OpenAI unavailable ({type(exc).__name__})")

            if openai_gateway:
                self._verify_regions(
                    document,
                    regions,
                    openai_gateway,
                    glm,
                    workdir,
                    warnings,
                    model_runs,
                    progress_callback,
                    uncertain_only=selected_profile == ProcessingProfile.HYBRID,
                )

            try:
                tree, assets = self._build_tree(
                    document,
                    regions,
                    openai_gateway,
                    warnings,
                    model_runs,
                    selected_profile,
                    window_runs,
                    adaptive_retries,
                    use_terra=selected_profile
                    == ProcessingProfile.MAXIMUM_ACCURACY,
                )
            finally:
                if glm is not None:
                    glm.unload()
            apply_document_profile(tree, selected_document_profile)
            self._populate_citations(tree)
            self._attach_table_citation_metadata(tree)
            self._validate_tree(tree)
            manifest = build_batch_manifest(
                tree,
                selected_profile,
                selected_document_profile,
                enabled=SegmentationMode(segmentation) == SegmentationMode.AUTO,
            )
            if openai_gateway and SegmentationMode(segmentation) == SegmentationMode.AUTO:
                manifest = self._adjudicate_boundaries(
                    document,
                    tree,
                    manifest,
                    openai_gateway,
                    selected_profile,
                    selected_document_profile,
                )
            tree.batch_manifest = manifest
            if len(manifest.subdocuments) > 1:
                tree.document_classification = DocumentClassification(
                    profile=DocumentProfile.MIXED_BATCH,
                    domain="mixed",
                    confidence=sum(
                        item.confidence for item in manifest.subdocuments
                    )
                    / len(manifest.subdocuments),
                    method="segmentation",
                )
                tree.grounded_fields = []
                tree.validation_findings = []
            extraction_json = ""
            table_exports: dict[str, bytes] = {}
            master_extractions: list[SchemaExtraction] = []
            is_pdf = Path(filename).suffix.casefold() == ".pdf"
            if extraction_schema is not None and not is_pdf:
                extraction = self._extract_with_profile(
                    tree,
                    extraction_schema,
                    selected_profile,
                    openai_gateway,
                )
                tree.schema_extractions = [extraction]
                self._validate_tree(tree)
                master_extractions.append(extraction)
                extraction_json = extraction.model_dump_json(indent=2)
                table_exports = build_table_exports(extraction, extraction_schema)
            for node in tree.nodes.values():
                node.markdown = render_node(node)
            markdown = render_markdown(tree)
            llm_markdown = render_llm_markdown(tree)
            subdocuments: list[SubdocumentResult] = []
            batch_files: dict[str, bytes | str] = {
                "batch.manifest.json": manifest.model_dump_json(indent=2)
            }
            if is_pdf:
                for descriptor in manifest.subdocuments:
                    subdocument, segment_assets, new_model_runs = (
                        self._build_subdocument_result(
                            data,
                            descriptor,
                            tree,
                            assets,
                            extraction_schema,
                            selected_profile,
                            openai_gateway,
                        )
                    )
                    known_logical_ids = {item.id for item in tree.logical_tables}
                    tree.logical_tables.extend(
                        item.model_copy(deep=True)
                        for item in subdocument.tree.logical_tables
                        if item.id not in known_logical_ids
                    )
                    tree.model_runs.extend(new_model_runs)
                    master_extractions.extend(subdocument.tree.schema_extractions)
                    subdocuments.append(subdocument)
                    self._add_subdocument_files(
                        subdocument,
                        segment_assets,
                        batch_files,
                        table_exports,
                    )
            if extraction_schema is not None and is_pdf:
                tree.schema_extractions = master_extractions
                self._validate_tree(tree)
                if len(master_extractions) == 1:
                    extraction_json = master_extractions[0].model_dump_json(indent=2)
                else:
                    extraction_json = json.dumps(
                        {
                            "schema_version": "1.0.0",
                            "schema_name": str(
                                extraction_schema.get("title") or "Custom extraction"
                            ),
                            "documents": [
                                item.model_dump(mode="json")
                                for item in master_extractions
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                batch_files["extraction.manifest.json"] = extraction_json
            elif extraction_json:
                batch_files[f"{Path(filename).stem}.extraction.json"] = extraction_json
                batch_files.update(table_exports)
            parse_result = self._finalize_result(
                data=data,
                filename=filename,
                tree=tree,
                assets=assets,
                markdown=markdown,
                llm_markdown=llm_markdown,
                manifest=manifest,
                subdocuments=subdocuments,
                extraction_json=extraction_json,
                table_exports=table_exports,
                batch_files=batch_files,
            )
            _emit(progress_callback, "complete", total, total, "Exports ready")
            return parse_result

    def _process_glm_windows(
        self,
        document: IngestedDocument,
        regions: dict[int, list[RegionEvidence]],
        glm: GlmOcrGateway,
        workdir: Path,
        window_runs: list[WindowRun],
        warnings: list[str],
        model_runs: list[RunRecord],
        progress_callback: ProgressCallback | None,
    ) -> None:
        for window_number, window in enumerate(window_runs, start=1):
            window.status = "processing"
            _emit(
                progress_callback,
                "window",
                window_number,
                len(window_runs),
                f"Processing pages {window.start_page}-{window.end_page}",
            )
            pages = document.pages[window.start_page - 1 : window.end_page]
            for attempt in range(1, self.config.window_retry_count + 2):
                window.attempts = attempt
                try:
                    for page in pages:
                        page_regions = regions[page.number]
                        for index, region in enumerate(page_regions, start=1):
                            if not self._should_use_glm(page, region):
                                self._reconcile_region(region, page.scanned)
                                continue
                            _emit(
                                progress_callback,
                                "glm",
                                index,
                                len(page_regions),
                                f"GLM-OCR reading page {page.number}, region {index}",
                            )
                            try:
                                crop = self._crop_region(
                                    page, region, workdir, pass_number=1
                                )
                                candidate, run = glm.recognize_region(
                                    crop,
                                    NodeType(region.type),
                                    region_id=region.id,
                                    pass_number=1,
                                )
                                candidate.bbox = region.bbox
                                run.page_number = page.number
                                region.candidates.append(candidate)
                                model_runs.append(run)
                            except Exception as exc:  # noqa: BLE001
                                warnings.append(
                                    f"Page {page.number} region {region.id} "
                                    f"GLM fallback ({type(exc).__name__})"
                                )
                            self._reconcile_region(region, page.scanned)
                except Exception as exc:  # noqa: BLE001 - window retry boundary
                    if attempt <= self.config.window_retry_count:
                        continue
                    window.status = "degraded"
                    warnings.append(
                        f"Pages {window.start_page}-{window.end_page} "
                        f"window fallback ({type(exc).__name__})"
                    )
                else:
                    window.status = "complete"
                break

    def _adjudicate_boundaries(
        self,
        document: IngestedDocument,
        tree: DocumentTree,
        manifest: BatchManifest,
        gateway: OpenAIDocumentGateway,
        processing_profile: ProcessingProfile,
        document_profile: DocumentProfile,
    ) -> BatchManifest:
        overrides: dict[int, tuple[str, float, str, str]] = {}
        page_by_number = {page.number: page for page in document.pages}
        classification_by_page = {
            item.page_number: item for item in manifest.page_classifications
        }
        for boundary in manifest.boundaries:
            if boundary.decision != "uncertain":
                continue
            try:
                evidence = {
                    "boundary": boundary.model_dump(mode="json"),
                    "previous_page": classification_by_page[
                        boundary.before_page - 1
                    ].model_dump(mode="json"),
                    "current_page": classification_by_page[
                        boundary.before_page
                    ].model_dump(mode="json"),
                }
                decision, run = gateway.adjudicate_boundary(
                    page_by_number[boundary.before_page - 1],
                    page_by_number[boundary.before_page],
                    evidence,
                )
                tree.model_runs.append(run)
                adjudication = "luna"
                if (
                    decision.decision == "uncertain"
                    and processing_profile == ProcessingProfile.MAXIMUM_ACCURACY
                ):
                    decision, run = gateway.adjudicate_boundary(
                        page_by_number[boundary.before_page - 1],
                        page_by_number[boundary.before_page],
                        evidence,
                        use_terra=True,
                    )
                    tree.model_runs.append(run)
                    adjudication = "terra"
                if decision.decision != "uncertain" and decision.confidence >= 0.65:
                    overrides[boundary.before_page] = (
                        decision.decision,
                        decision.confidence,
                        adjudication,
                        decision.reason,
                    )
            except Exception as exc:  # noqa: BLE001 - conservative fallback
                tree.warnings.append(
                    f"Boundary before page {boundary.before_page} retained "
                    f"after cloud fallback ({type(exc).__name__})"
                )
        if not overrides:
            return manifest
        return build_batch_manifest(
            tree,
            processing_profile,
            document_profile,
            boundary_overrides=overrides,
        )

    def _build_subdocument_result(
        self,
        data: bytes,
        descriptor: SubdocumentDescriptor,
        tree: DocumentTree,
        assets: dict[str, bytes],
        extraction_schema: dict[str, Any] | None,
        processing_profile: ProcessingProfile,
        gateway: OpenAIDocumentGateway | None,
    ) -> tuple[SubdocumentResult, dict[str, bytes], list[RunRecord]]:
        segment_tree = slice_document_tree(tree, descriptor)
        segment_tree.logical_tables = []
        segment_tree.schema_extractions = []
        build_logical_tables(segment_tree)
        apply_document_profile(segment_tree, descriptor.profile)
        self._validate_tree(segment_tree)

        before_runs = len(segment_tree.model_runs)
        extraction_json = ""
        table_exports: dict[str, bytes] = {}
        if extraction_schema is not None:
            extraction = self._extract_with_profile(
                segment_tree,
                extraction_schema,
                processing_profile,
                gateway,
                subdocument_id=descriptor.id,
            )
            segment_tree.schema_extractions = [extraction]
            self._validate_tree(segment_tree)
            extraction_json = extraction.model_dump_json(indent=2)
            table_exports = build_table_exports(extraction, extraction_schema)

        segment_tree.failure_cases = derive_failure_cases(segment_tree)
        self._validate_tree(segment_tree)
        failures_jsonl = render_failures_jsonl(segment_tree)
        quality_json = render_quality_json(segment_tree)
        for node in segment_tree.nodes.values():
            node.markdown = render_node(node)
        markdown = render_markdown(segment_tree)
        llm_markdown = render_llm_markdown(segment_tree)
        json_text = render_json(segment_tree)
        audit_json = build_audit_json(segment_tree)
        source_pdf = extract_pdf_range(
            data, descriptor.start_page, descriptor.end_page
        )
        annotated_pdf = render_annotated_pdf(
            source_pdf, segment_tree.source_name, segment_tree
        )
        segment_assets = {
            path: content
            for path, content in assets.items()
            if path in segment_tree.assets
        }
        stem = Path(segment_tree.source_name).stem
        extra_files: dict[str, bytes | str] = {
            "source.pdf": source_pdf,
            f"{stem}.failures.jsonl": failures_jsonl,
            f"{stem}.quality.json": quality_json,
            f"{stem}.annotated.pdf": annotated_pdf,
        }
        if extraction_json:
            extra_files[f"{stem}.extraction.json"] = extraction_json
        extra_files.update(table_exports)
        bundle = build_bundle(
            segment_tree.source_name,
            markdown,
            llm_markdown,
            audit_json,
            json_text,
            segment_assets,
            extra_files,
        )
        result = SubdocumentResult(
            descriptor=descriptor,
            markdown=markdown,
            llm_markdown=llm_markdown,
            audit_json=audit_json,
            json_text=json_text,
            tree=segment_tree,
            source_pdf=source_pdf,
            bundle=bundle,
            extraction_json=extraction_json,
            table_exports=table_exports,
            failures_jsonl=failures_jsonl,
            quality_json=quality_json,
            annotated_pdf=annotated_pdf,
        )
        return result, segment_assets, segment_tree.model_runs[before_runs:]

    def _add_subdocument_files(
        self,
        result: SubdocumentResult,
        segment_assets: dict[str, bytes],
        batch_files: dict[str, bytes | str],
        table_exports: dict[str, bytes],
    ) -> None:
        safe_name = Path(result.tree.source_name).stem
        prefix = f"subdocuments/{safe_name}"
        batch_files.update(
            {
                f"{prefix}/source.pdf": result.source_pdf,
                f"{prefix}/{safe_name}.md": result.markdown,
                f"{prefix}/{safe_name}.llm.md": result.llm_markdown,
                f"{prefix}/{safe_name}.json": result.json,
                f"{prefix}/{safe_name}.audit.json": result.audit_json,
                f"{prefix}/{safe_name}.failures.jsonl": result.failures_jsonl,
                f"{prefix}/{safe_name}.quality.json": result.quality_json,
                f"{prefix}/{safe_name}.annotated.pdf": result.annotated_pdf,
            }
        )
        for path, content in segment_assets.items():
            batch_files[f"{prefix}/{path}"] = content
        if result.extraction_json:
            batch_files[f"{prefix}/{safe_name}.extraction.json"] = (
                result.extraction_json
            )
        for path, content in result.table_exports.items():
            batch_files[f"{prefix}/{path}"] = content
            table_exports[f"{prefix}/{path}"] = content

    def _finalize_result(
        self,
        *,
        data: bytes,
        filename: str,
        tree: DocumentTree,
        assets: dict[str, bytes],
        markdown: str,
        llm_markdown: str,
        manifest: BatchManifest,
        subdocuments: list[SubdocumentResult],
        extraction_json: str,
        table_exports: dict[str, bytes],
        batch_files: dict[str, bytes | str],
    ) -> ParseResult:
        tree.failure_cases = derive_failure_cases(tree)
        self._validate_tree(tree)
        failures_jsonl = render_failures_jsonl(tree)
        quality_json = render_quality_json(tree)
        annotated_pdf = render_annotated_pdf(data, filename, tree)
        json_text = render_json(tree)
        audit_json = build_audit_json(tree)
        stem = Path(filename).stem
        batch_files[f"{stem}.failures.jsonl"] = failures_jsonl
        batch_files[f"{stem}.quality.json"] = quality_json
        batch_files[f"{stem}.annotated.pdf"] = annotated_pdf
        bundle = build_bundle(
            filename,
            markdown,
            llm_markdown,
            audit_json,
            json_text,
            assets,
            batch_files,
        )
        return ParseResult(
            markdown=markdown,
            llm_markdown=llm_markdown,
            audit_json=audit_json,
            json_text=json_text,
            tree=tree,
            assets=assets,
            bundle=bundle,
            batch_manifest_json=manifest.model_dump_json(indent=2),
            subdocuments=subdocuments,
            extraction_json=extraction_json,
            table_exports=table_exports,
            failures_jsonl=failures_jsonl,
            quality_json=quality_json,
            annotated_pdf=annotated_pdf,
        )

    def parse_path(
        self,
        path: Path,
        progress_callback: ProgressCallback | None = None,
        **options: Any,
    ) -> ParseResult:
        size = path.stat().st_size
        if size > self.config.max_upload_bytes:
            raise ValueError(
                f"Uploaded document exceeds {self.config.max_upload_bytes // (1024 * 1024)} MB"
            )
        return self.parse(path.read_bytes(), path.name, progress_callback, **options)

    def _extract_with_profile(
        self,
        tree: DocumentTree,
        schema: dict[str, Any],
        profile: ProcessingProfile,
        gateway: OpenAIDocumentGateway | None,
        *,
        subdocument_id: str | None = None,
    ) -> SchemaExtraction:
        extraction = extract_schema_data(
            tree, schema, subdocument_id=subdocument_id
        )
        if gateway is None or profile == ProcessingProfile.LOCAL_ONLY:
            return extraction
        all_paths = schema_scalar_paths(schema)
        unresolved = (
            all_paths
            if profile == ProcessingProfile.MAXIMUM_ACCURACY
            else [path for path in all_paths if path not in extraction.provenance]
        )
        if not unresolved:
            return extraction
        decisions, run = gateway.resolve_extraction(
            schema,
            extraction_evidence(tree),
            unresolved_paths=unresolved,
        )
        tree.model_runs.append(run)
        apply_extraction_decisions(
            tree, schema, extraction, decisions, method="luna"
        )
        needs_terra = [
            path
            for path in all_paths
            if path not in extraction.provenance
            or extraction.provenance[path].method == "deterministic"
        ]
        if profile == ProcessingProfile.MAXIMUM_ACCURACY and needs_terra:
            decisions, run = gateway.resolve_extraction(
                schema,
                extraction_evidence(tree),
                unresolved_paths=needs_terra,
                use_terra=True,
            )
            tree.model_runs.append(run)
            apply_extraction_decisions(
                tree, schema, extraction, decisions, method="terra"
            )
            still_unverified = [
                path
                for path in all_paths
                if path in extraction.provenance
                and extraction.provenance[path].method == "deterministic"
            ]
            extraction.validation_errors.extend(
                f"Cloud verification did not confirm {path}"
                for path in still_unverified
            )
            if still_unverified:
                extraction.status = "partial"
        return extraction

    @staticmethod
    def _select_profile(
        profile: ProcessingProfile | str | None,
        allow_cloud: bool | None,
    ) -> ProcessingProfile:
        if profile is not None and allow_cloud is not None:
            raise ValueError("profile and allow_cloud cannot be used together")
        if allow_cloud is not None:
            return (
                ProcessingProfile.MAXIMUM_ACCURACY
                if allow_cloud
                else ProcessingProfile.LOCAL_ONLY
            )
        if profile is None:
            return ProcessingProfile.LOCAL_ONLY
        return ProcessingProfile(profile)

    @staticmethod
    def _initial_regions(
        document: IngestedDocument,
        paddle_results: dict[int, dict[str, Any]],
    ) -> dict[int, list[RegionEvidence]]:
        results: dict[int, list[RegionEvidence]] = {}
        for page in document.pages:
            regions: list[RegionEvidence] = []
            payload = paddle_results.get(page.number, {})
            paddle_tables = find_paddle_table_results(payload)
            table_index = 0
            for index, raw in enumerate(find_paddle_regions(payload)):
                label = str(raw.get("block_label", "text")).casefold()
                node_type = LABEL_MAP.get(label, NodeType.OCR_BLOCK)
                bbox = _bbox_from_paddle(raw.get("block_bbox"), page)
                order = _bounded_int(raw.get("block_order"), index, 0, 100_000)
                region_id = _node_id(
                    document.sha256, page.number, order + 1, node_type, bbox
                )
                text = str(raw.get("block_content", "")).strip()
                candidates = []
                if text:
                    candidates.append(
                        RecognitionCandidate(
                            id=f"{region_id}:paddle:0",
                            source="paddle",
                            task="layout-ocr",
                            prompt_version="paddle-layout-v1",
                            pass_number=0,
                            text=text,
                            bbox=bbox,
                            validation_signals={
                                "provider_confidence": _bounded_float(
                                    raw.get("score"), 0.7
                                )
                            },
                        )
                    )
                native_block = _matching_block(page, bbox)
                if native_block and native_block.text.strip():
                    candidates.append(
                        RecognitionCandidate(
                            id=f"{region_id}:digital:0",
                            source="digital",
                            task="native-text",
                            prompt_version="digital-extract-v1",
                            pass_number=0,
                            text=native_block.text,
                            bbox=native_block.bbox,
                        )
                    )
                attributes: dict[str, Any] = {}
                if label == "table":
                    rows = raw.get("table_rows")
                    if not isinstance(rows, list) or not rows:
                        rows = (
                            normalize_paddle_table(paddle_tables[table_index])
                            if table_index < len(paddle_tables)
                            else []
                        )
                    table_index += 1
                    for cells in rows:
                        if not isinstance(cells, list):
                            continue
                        for cell in cells:
                            if not isinstance(cell, dict):
                                continue
                            provider_bbox = cell.pop("provider_bbox", None)
                            if provider_bbox is None:
                                continue
                            cell_bbox = _cell_bbox_from_paddle(provider_bbox, page)
                            if cell_bbox is not None:
                                cell["bbox"] = [
                                    cell_bbox.x0,
                                    cell_bbox.y0,
                                    cell_bbox.x1,
                                    cell_bbox.y1,
                                ]
                    attributes["table_rows"] = rows
                if node_type == NodeType.CHECKBOX:
                    attributes["state"] = str(raw.get("state", "unknown"))[:20]
                if label == "chart":
                    for key in (
                        "chart_type",
                        "chart_title",
                        "axes",
                        "legends",
                        "chart_data",
                    ):
                        if key in raw:
                            value = raw[key]
                            if isinstance(value, list):
                                limit = 10_000 if key == "chart_data" else 100
                                attributes[key] = value[:limit]
                            elif isinstance(value, str):
                                attributes[key] = value[:100_000]
                            elif isinstance(value, (int, float, bool)):
                                attributes[key] = value
                regions.append(
                    RegionEvidence(
                        id=region_id,
                        page_number=page.number,
                        type=node_type,
                        bbox=bbox,
                        reading_order=order,
                        semantic_role=label,
                        candidates=candidates,
                        attributes=attributes,
                    )
                )
            if not regions and page.text_blocks:
                median_size = sorted(block.font_size for block in page.text_blocks)[
                    (len(page.text_blocks) - 1) // 2
                ]
                for index, block in enumerate(page.text_blocks):
                    is_heading = (
                        block.font_size >= median_size * 1.25 and len(block.text) < 200
                    )
                    node_type = NodeType.HEADING if is_heading else NodeType.PARAGRAPH
                    region_id = _node_id(
                        document.sha256, page.number, index + 1, node_type, block.bbox
                    )
                    regions.append(
                        RegionEvidence(
                            id=region_id,
                            page_number=page.number,
                            type=node_type,
                            bbox=block.bbox,
                            reading_order=index,
                            semantic_role="heading" if is_heading else "paragraph",
                            candidates=[
                                RecognitionCandidate(
                                    id=f"{region_id}:digital:0",
                                    source="digital",
                                    task="native-text",
                                    prompt_version="digital-extract-v1",
                                    pass_number=0,
                                    text=block.text,
                                    bbox=block.bbox,
                                )
                            ],
                            attributes={"heading_level": 2} if is_heading else {},
                        )
                    )
            if not regions:
                node_type = NodeType.OCR_BLOCK
                bbox = BoundingBox(x0=0, y0=0, x1=1, y1=1)
                region_id = _node_id(document.sha256, page.number, 1, node_type, bbox)
                regions.append(
                    RegionEvidence(
                        id=region_id,
                        page_number=page.number,
                        type=node_type,
                        bbox=bbox,
                        reading_order=0,
                        semantic_role="full_page_fallback",
                    )
                )
            results[page.number] = regions
        return results

    @staticmethod
    def _layout_score(regions: list[RegionEvidence]) -> float:
        if not regions or all(
            region.semantic_role == "full_page_fallback" for region in regions
        ):
            return 0.0
        boxed = sum(region.bbox is not None for region in regions) / len(regions)
        textual = sum(
            any(candidate.text.strip() for candidate in region.candidates)
            for region in regions
        ) / len(regions)
        return min(1.0, 0.5 * boxed + 0.5 * textual)

    def _adaptive_page_layout_retries(
        self,
        document: IngestedDocument,
        regions: dict[int, list[RegionEvidence]],
        paddle_results: dict[int, dict[str, Any]],
        workdir: Path,
        warnings: list[str],
        records: list[AdaptiveRetryRecord],
        progress: ProgressCallback | None,
    ) -> None:
        for page in document.pages:
            payload = paddle_results.get(page.number, {})
            current = regions[page.number]
            triggers: list[str] = []
            if payload.get("_provider_error"):
                triggers.append("paddle_provider_error")
            if any(item.semantic_role == "full_page_fallback" for item in current):
                triggers.append("full_page_fallback")
            if not triggers:
                continue
            before = self._layout_score(current)
            record_id = hashlib.sha256(
                f"{document.sha256}:page:{page.number}:adaptive-layout-1".encode()
            ).hexdigest()[:20]
            try:
                _emit(
                    progress,
                    "adaptive_page",
                    page.number,
                    len(document.pages),
                    f"Retrying page {page.number} layout at 450 DPI",
                )
                retry_path = workdir / f"page-{page.number:04d}-adaptive-450.png"
                with Image.open(page.image_path) as image:
                    requested_scale = 450 / max(72, page.dpi)
                    pixel_scale = math.sqrt(
                        self.config.max_page_pixels / max(1, image.width * image.height)
                    )
                    scale = max(1.0, min(requested_scale, pixel_scale))
                    retry_dpi = max(page.dpi, int(page.dpi * scale))
                    image.resize(
                        (
                            max(1, int(image.width * scale)),
                            max(1, int(image.height * scale)),
                        ),
                        Image.Resampling.LANCZOS,
                    ).save(retry_path, "PNG")
                raw = PaddleDockerRunner(self.config).run(
                    retry_path, workdir, 1, progress
                ).get(1, {})
                retry_page = PageEvidence(
                    number=page.number,
                    width=page.width,
                    height=page.height,
                    dpi=retry_dpi,
                    image_path=retry_path,
                    ocr_image_path=retry_path,
                    scanned=page.scanned,
                    text_blocks=page.text_blocks,
                    links=page.links,
                )
                retry_document = IngestedDocument(
                    document.name,
                    document.sha256,
                    retry_path,
                    [retry_page],
                )
                proposed = self._initial_regions(
                    retry_document, {page.number: raw}
                )[page.number]
                after = self._layout_score(proposed)
                applied = after > before
                if applied:
                    regions[page.number] = proposed
                records.append(
                    AdaptiveRetryRecord(
                        id=f"retry-{record_id}",
                        scope="page",
                        page_number=page.number,
                        trigger_codes=triggers,
                        providers=["paddle"],
                        dpi=retry_dpi,
                        before_score=before,
                        after_score=after,
                        outcome="applied" if applied else "rejected",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - bounded provider retry
                warnings.append(
                    f"Page {page.number} adaptive layout retry fallback ({type(exc).__name__})"
                )
                records.append(
                    AdaptiveRetryRecord(
                        id=f"retry-{record_id}",
                        scope="page",
                        page_number=page.number,
                        trigger_codes=triggers,
                        providers=["paddle"],
                        dpi=450,
                        before_score=before,
                        outcome="failed",
                    )
                )

    def _adaptive_region_retries(
        self,
        document: IngestedDocument,
        regions: dict[int, list[RegionEvidence]],
        glm: GlmOcrGateway,
        workdir: Path,
        warnings: list[str],
        model_runs: list[RunRecord],
        records: list[AdaptiveRetryRecord],
        progress: ProgressCallback | None,
    ) -> None:
        for page in document.pages:
            targets = [
                region
                for region in regions[page.number]
                if region.verification_status in {"disputed", "unreadable", "unresolved"}
                or region.confidence < 0.65
            ]
            for index, region in enumerate(targets, start=1):
                triggers = [region.verification_status]
                if region.confidence < 0.65:
                    triggers.append("low_confidence")
                before = region.confidence
                previous = (
                    region.selected_candidate_id,
                    region.verification_status,
                    region.confidence,
                    region.agreement_score,
                )
                record_id = hashlib.sha256(
                    f"{document.sha256}:{page.number}:{region.id}:adaptive-region-1".encode()
                ).hexdigest()[:20]
                try:
                    _emit(
                        progress,
                        "adaptive_region",
                        index,
                        len(targets),
                        f"Retrying page {page.number} region {index} at high resolution",
                    )
                    crop = self._crop_region(page, region, workdir, pass_number=2)
                    candidate, run = glm.recognize_region(
                        crop,
                        NodeType(region.type),
                        region_id=region.id,
                        pass_number=2,
                    )
                    candidate.id = f"{candidate.id}:adaptive"
                    candidate.task = f"adaptive-{candidate.task}"
                    candidate.bbox = region.bbox
                    run.page_number = page.number
                    run.region_id = region.id
                    run.stage = "adaptive_region_ocr"
                    region.candidates.append(candidate)
                    model_runs.append(run)
                    self._reconcile_region(region, page.scanned)
                    after = region.confidence
                    old_unresolved = previous[1] in {"unreadable", "unresolved"}
                    new_usable = region.selected_candidate_id is not None
                    applied = (old_unresolved and new_usable) or after > before
                    if not applied:
                        (
                            region.selected_candidate_id,
                            region.verification_status,
                            region.confidence,
                            region.agreement_score,
                        ) = previous
                    records.append(
                        AdaptiveRetryRecord(
                            id=f"retry-{record_id}",
                            scope="region",
                            page_number=page.number,
                            region_id=region.id,
                            trigger_codes=triggers,
                            providers=["glm"],
                            dpi=min(1200, page.dpi * 2),
                            crop_padding=0.08,
                            before_score=before,
                            after_score=after,
                            outcome="applied" if applied else "rejected",
                            selected_candidate_id=region.selected_candidate_id,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - bounded provider retry
                    warnings.append(
                        f"Page {page.number} region {region.id} adaptive retry fallback ({type(exc).__name__})"
                    )
                    records.append(
                        AdaptiveRetryRecord(
                            id=f"retry-{record_id}",
                            scope="region",
                            page_number=page.number,
                            region_id=region.id,
                            trigger_codes=triggers,
                            providers=["glm"],
                            dpi=min(1200, page.dpi * 2),
                            crop_padding=0.08,
                            before_score=before,
                            outcome="failed",
                        )
                    )

    @staticmethod
    def _should_use_glm(page: PageEvidence, region: RegionEvidence) -> bool:
        if page.scanned:
            return True
        if region.type in COMPLEX_REGION_TYPES:
            return True
        paddle = next(
            (item for item in region.candidates if item.source == "paddle"), None
        )
        if paddle and page.digital_text:
            return _support_score(paddle.text, page.digital_text) < 0.85
        return False

    @staticmethod
    def _crop_region(
        page: PageEvidence,
        region: RegionEvidence,
        workdir: Path,
        *,
        pass_number: int,
    ) -> Path:
        source = (
            page.image_path
            if region.type in COMPLEX_REGION_TYPES
            else page.ocr_image_path
        )
        output = workdir / f"page-{page.number:04d}-{region.id}-pass-{pass_number}.png"
        with Image.open(source) as image:
            width, height = image.size
            bbox = region.bbox or BoundingBox(x0=0, y0=0, x1=1, y1=1)
            padding = 0.08 if pass_number == 2 else 0.03
            pad_x = max(8 / width, (bbox.x1 - bbox.x0) * padding)
            pad_y = max(8 / height, (bbox.y1 - bbox.y0) * padding)
            left = max(0, int((bbox.x0 - pad_x) * width))
            top = max(0, int((bbox.y0 - pad_y) * height))
            right = min(width, max(left + 1, int((bbox.x1 + pad_x) * width)))
            bottom = min(height, max(top + 1, int((bbox.y1 + pad_y) * height)))
            crop = image.crop((left, top, right, bottom)).convert("RGB")
            if pass_number == 2:
                crop = crop.resize(
                    (crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS
                )
            crop.save(output, "PNG")
        return output

    @staticmethod
    def _reconcile_region(region: RegionEvidence, scanned: bool) -> None:
        usable = [item for item in region.candidates if item.text.strip()]
        if not usable:
            region.selected_candidate_id = None
            region.agreement_score = 0
            region.confidence = 0
            region.verification_status = "unreadable"
            return
        preferred = _preferred_candidate(region, scanned) or usable[0]
        region.selected_candidate_id = preferred.id
        if len(usable) == 1:
            region.agreement_score = 1
            region.confidence = 0.92 if preferred.source == "digital" else 0.75
            region.verification_status = "single_source"
            return
        comparisons = [
            _text_similarity(preferred.text, candidate.text)
            for candidate in usable
            if candidate.id != preferred.id
        ]
        region.agreement_score = max(comparisons, default=0)
        if region.agreement_score >= 0.90:
            region.confidence = 0.95
            region.verification_status = "local_agreement"
        else:
            region.confidence = 0.55
            region.verification_status = "disputed"

    def _verify_regions(
        self,
        document: IngestedDocument,
        regions: dict[int, list[RegionEvidence]],
        gateway: OpenAIDocumentGateway,
        glm: GlmOcrGateway | None,
        workdir: Path,
        warnings: list[str],
        model_runs: list[RunRecord],
        progress: ProgressCallback | None,
        *,
        uncertain_only: bool,
    ) -> None:
        for page in document.pages:
            page_regions = regions[page.number]
            target_regions = (
                [
                    region
                    for region in page_regions
                    if region.confidence < 0.85
                    or region.verification_status
                    in {"disputed", "unreadable", "unresolved"}
                ]
                if uncertain_only
                else page_regions
            )
            if not target_regions:
                continue
            try:
                _emit(
                    progress,
                    "luna",
                    page.number,
                    len(document.pages),
                    f"Luna verifying page {page.number}",
                )
                verification, run = gateway.verify_page(page, target_regions)
                model_runs.append(run)
                warnings.extend(
                    f"Page {page.number}: {item}" for item in verification.warnings
                )
            except Exception as exc:  # noqa: BLE001 - provider fallback boundary
                warnings.append(
                    f"Page {page.number} Luna fallback ({type(exc).__name__})"
                )
                continue
            by_id = {region.id: region for region in target_regions}
            for decision in verification.decisions:
                region = by_id.get(decision.region_id)
                if region is None:
                    warnings.append(
                        f"Page {page.number}: Luna returned unknown region ID"
                    )
                    continue
                known_ids = {candidate.id for candidate in region.candidates}
                if decision.semantic_role:
                    region.semantic_role = decision.semantic_role
                if (
                    decision.selected_candidate_id
                    and decision.selected_candidate_id not in known_ids
                ):
                    warnings.append(
                        f"Page {page.number} region {region.id}: "
                        "Luna returned unknown candidate ID"
                    )
                if (
                    decision.selected_candidate_id in known_ids
                    and not decision.needs_retry
                ):
                    region.selected_candidate_id = decision.selected_candidate_id
                    region.verification_status = "cloud_verified"
                    region.confidence = max(region.confidence, 0.92)
                    continue
                if not (decision.needs_retry or decision.proposed_text):
                    continue
                proposal = (decision.proposed_text or "").strip()
                if proposal:
                    region.candidates.append(
                        RecognitionCandidate(
                            id=f"{region.id}:luna:1",
                            source="luna",
                            task="verification-proposal",
                            prompt_version=PROMPT_VERSION,
                            pass_number=1,
                            text=proposal,
                            bbox=region.bbox,
                        )
                    )
                if glm is None:
                    region.selected_candidate_id = None
                    region.verification_status = "unresolved"
                    region.confidence = 0.2
                    continue
                try:
                    crop = self._crop_region(page, region, workdir, pass_number=2)
                    retry, retry_run = glm.recognize_region(
                        crop, NodeType(region.type), region_id=region.id, pass_number=2
                    )
                    retry.bbox = region.bbox
                    retry_run.page_number = page.number
                    region.candidates.append(retry)
                    model_runs.append(retry_run)
                except Exception as exc:  # noqa: BLE001 - retry fallback boundary
                    warnings.append(
                        f"Page {page.number} region {region.id} GLM retry fallback ({type(exc).__name__})"
                    )
                    region.selected_candidate_id = None
                    region.verification_status = "unresolved"
                    region.confidence = 0.2
                    continue
                targets = [
                    candidate
                    for candidate in region.candidates[:-1]
                    if candidate.source != "luna"
                ]
                best = max(
                    targets,
                    key=lambda item: _text_similarity(retry.text, item.text),
                    default=None,
                )
                proposal_score = (
                    _text_similarity(retry.text, proposal) if proposal else 0
                )
                prior_score = _text_similarity(retry.text, best.text) if best else 0
                if max(proposal_score, prior_score) >= 0.80:
                    region.selected_candidate_id = (
                        retry.id if proposal_score >= prior_score else best.id
                    )
                    region.agreement_score = max(proposal_score, prior_score)
                    region.verification_status = "retry_confirmed"
                    region.confidence = 0.88
                else:
                    region.selected_candidate_id = None
                    region.verification_status = "unresolved"
                    region.confidence = 0.2

    def _build_tree(
        self,
        document: IngestedDocument,
        region_results: dict[int, list[RegionEvidence]],
        openai_gateway: OpenAIDocumentGateway | None,
        warnings: list[str],
        model_runs: list[RunRecord],
        processing_profile: ProcessingProfile,
        window_runs: list[WindowRun],
        adaptive_retries: list[AdaptiveRetryRecord],
        *,
        use_terra: bool,
    ) -> tuple[DocumentTree, dict[str, bytes]]:
        document_id = f"doc-{document.sha256[:16]}"
        root_id = _node_id(document.sha256, None, 0, NodeType.DOCUMENT, None)
        nodes: dict[str, DocumentNode] = {
            root_id: DocumentNode(
                id=root_id,
                type=NodeType.DOCUMENT,
                semantic_role="document",
                provenance=[Provenance(source="upload", source_ref=document.sha256)],
            )
        }
        pages: list[PageRecord] = []
        assets: dict[str, bytes] = {}

        for page in document.pages:
            page_id = _node_id(document.sha256, page.number, 0, NodeType.PAGE, None)
            page_node = DocumentNode(
                id=page_id,
                type=NodeType.PAGE,
                parent_id=root_id,
                page_number=page.number,
                semantic_role="page",
                provenance=[
                    Provenance(source="render", source_ref=page.image_path.name)
                ],
            )
            nodes[page_id] = page_node
            nodes[root_id].children_ids.append(page_id)
            page_record = PageRecord(
                id=page_id,
                number=page.number,
                width=page.width,
                height=page.height,
                dpi=page.dpi,
                scanned=page.scanned,
            )
            for order, region in enumerate(
                sorted(region_results[page.number], key=lambda item: item.reading_order)
            ):
                node_type = NodeType(region.type)
                bbox = region.bbox
                node_id = _node_id(
                    document.sha256, page.number, order + 1, node_type, bbox
                )
                selected = next(
                    (
                        item
                        for item in region.candidates
                        if item.id == region.selected_candidate_id
                    ),
                    None,
                )
                text = (
                    selected.text.strip()
                    if selected and selected.text.strip()
                    else f"[UNREADABLE {node_id}]"
                )
                alternatives = [
                    item.text
                    for item in region.candidates
                    if item.id != region.selected_candidate_id and item.text.strip()
                ]
                signals = {
                    "candidate_agreement": region.agreement_score,
                    "verification_confidence": region.confidence,
                }
                provenance = [
                    Provenance(
                        source=candidate.source,
                        source_ref=candidate.id,
                        model=(
                            self.config.glm_model
                            if candidate.source == "glm"
                            else self.config.luna_model
                            if candidate.source == "luna"
                            else None
                        ),
                        prompt_version=candidate.prompt_version,
                    )
                    for candidate in region.candidates
                ]
                matching = _matching_block(page, bbox)
                node = DocumentNode(
                    id=node_id,
                    type=node_type,
                    parent_id=page_id,
                    page_number=page.number,
                    bbox=bbox,
                    source_bbox=matching.source_bbox if matching else None,
                    reading_order=order,
                    semantic_role=region.semantic_role,
                    text=text,
                    confidence=_confidence(region.confidence, signals),
                    provenance=provenance,
                    alternatives=alternatives,
                    recognition_candidates=list(region.candidates),
                    agreement_score=region.agreement_score,
                    verification_status=region.verification_status,
                    selected_candidate_id=region.selected_candidate_id,
                    attributes=dict(region.attributes),
                )
                if node_type in {
                    NodeType.FIGURE,
                    NodeType.IMAGE,
                    NodeType.CHART,
                    NodeType.SIGNATURE,
                    NodeType.SEAL,
                }:
                    node.visual_analysis = self._visual_analysis(
                        node, processing_profile
                    )
                if (
                    node_type
                    in {
                        NodeType.FIGURE,
                        NodeType.IMAGE,
                        NodeType.CHART,
                        NodeType.SIGNATURE,
                        NodeType.SEAL,
                        NodeType.FORMULA,
                    }
                    and bbox
                ):
                    asset_path, content = self._crop_asset(page, node_id, bbox)
                    node.attributes["asset_path"] = asset_path
                    assets[asset_path] = content
                nodes[node_id] = node
                page_node.children_ids.append(node_id)
                page_record.content_node_ids.append(node_id)
            pages.append(page_record)

        tree = DocumentTree(
            document_id=document_id,
            source_name=document.name,
            source_sha256=document.sha256,
            processing_profile=processing_profile,
            root_id=root_id,
            nodes=nodes,
            pages=pages,
            assets=sorted(assets),
            warnings=warnings,
            model_runs=model_runs,
            window_runs=window_runs,
            adaptive_retries=adaptive_retries,
        )
        if openai_gateway and use_terra and len(pages) > 1:
            self._resolve_windows(tree, openai_gateway)
        self._validate_table_limits(tree)
        self._build_semantic_hierarchy(tree, document)
        self._resolve_repeated_decorations(tree)
        self._link_page_continuations(tree)
        build_logical_tables(tree)
        self._validate_tree(tree)
        return tree, assets

    @staticmethod
    def _visual_analysis(
        node: DocumentNode, processing_profile: ProcessingProfile
    ) -> VisualAnalysis:
        raw_points = node.attributes.get("chart_data", [])
        points: list[VisualDataPoint] = []
        if isinstance(raw_points, list):
            for raw in raw_points[:10_000]:
                if not isinstance(raw, dict) or raw.get("value") is None:
                    continue
                points.append(
                    VisualDataPoint(
                        label=str(raw.get("label"))[:1_000]
                        if raw.get("label") is not None
                        else None,
                        value=str(raw["value"])[:10_000],
                        series=str(raw.get("series"))[:1_000]
                        if raw.get("series") is not None
                        else None,
                        source_text=str(raw.get("source_text"))[:10_000]
                        if raw.get("source_text") is not None
                        else None,
                    )
                )
        axes = node.attributes.get("axes", [])
        legends = node.attributes.get("legends", [])
        summary = None
        if processing_profile == ProcessingProfile.MAXIMUM_ACCURACY:
            summary = (
                f"{node.type} region containing {len(points)} grounded data points."
                if node.type == NodeType.CHART.value
                else f"{node.type} region with associated literal OCR and caption evidence."
            )
        return VisualAnalysis(
            kind=node.type,
            literal_text=node.text or "",
            title=str(node.attributes.get("chart_title"))[:10_000]
            if node.attributes.get("chart_title") is not None
            else None,
            chart_type=str(node.attributes.get("chart_type"))[:1_000]
            if node.attributes.get("chart_type") is not None
            else None,
            axes=[str(item)[:1_000] for item in axes[:20]]
            if isinstance(axes, list)
            else [],
            legends=[str(item)[:1_000] for item in legends[:100]]
            if isinstance(legends, list)
            else [],
            data_points=points,
            derived_summary=summary,
            summary_literal=False,
            source_node_ids=[node.id],
            confidence=node.confidence.score if node.confidence else 0.5,
        )

    def _build_semantic_hierarchy(
        self, tree: DocumentTree, document: IngestedDocument
    ) -> None:
        root = tree.nodes[tree.root_id]
        root.children_ids = [page.id for page in tree.pages]
        section_stack: list[tuple[int, str]] = []
        unsectioned_id: str | None = None
        decorations = {NodeType.HEADER.value, NodeType.FOOTER.value}

        def add_section(title: str, level: int, page_number: int, seed: str) -> str:
            section_id = _derived_id(document.sha256, "section", seed)
            parent_id = section_stack[-1][1] if section_stack else tree.root_id
            tree.nodes[section_id] = DocumentNode(
                id=section_id,
                type=NodeType.SECTION,
                parent_id=parent_id,
                page_number=page_number,
                semantic_role="section",
                text=title,
                attributes={"heading_level": level},
                provenance=[Provenance(source="deterministic_hierarchy")],
            )
            tree.nodes[parent_id].children_ids.append(section_id)
            return section_id

        for page in tree.pages:
            evidence_page = document.pages[page.number - 1]
            page_node = tree.nodes[page.id]
            page_node.children_ids = []
            current_list_id: str | None = None
            for node_id in page.content_node_ids:
                node = tree.nodes[node_id]
                if node.type in decorations:
                    node.parent_id = page.id
                    page_node.children_ids.append(node_id)
                    continue
                if node.type == NodeType.HEADING.value:
                    level = _bounded_int(node.attributes.get("heading_level"), 2, 1, 6)
                    while section_stack and section_stack[-1][0] >= level:
                        section_stack.pop()
                    section_id = add_section(
                        node.text or "[UNREADABLE]", level, page.number, node.id
                    )
                    section_stack.append((level, section_id))
                    node.parent_id = section_id
                    tree.nodes[section_id].children_ids.append(node_id)
                    current_list_id = None
                    continue
                if not section_stack:
                    if unsectioned_id is None:
                        unsectioned_id = add_section(
                            "Unsectioned", 1, page.number, "unsectioned"
                        )
                    section_stack = [(1, unsectioned_id)]
                parent_id = section_stack[-1][1]
                if node.type == NodeType.LIST_ITEM.value:
                    if current_list_id is None:
                        current_list_id = _derived_id(document.sha256, "list", node.id)
                        tree.nodes[current_list_id] = DocumentNode(
                            id=current_list_id,
                            type=NodeType.LIST,
                            parent_id=parent_id,
                            page_number=page.number,
                            semantic_role="list",
                            provenance=[Provenance(source="deterministic_hierarchy")],
                        )
                        tree.nodes[parent_id].children_ids.append(current_list_id)
                    parent_id = current_list_id
                else:
                    current_list_id = None
                node.parent_id = parent_id
                tree.nodes[parent_id].children_ids.append(node_id)
                if node.type == NodeType.TABLE.value:
                    self._materialize_table(tree, document.sha256, node)
            DocumentParser._associate_captions(tree, page)
            DocumentParser._attach_links(tree, page_node, evidence_page, document.pages)
        DocumentParser._materialize_forms(tree, document.sha256)

    def _materialize_table(
        self, tree: DocumentTree, digest: str, table: DocumentNode
    ) -> None:
        rows = table.attributes.get("table_rows")
        if not isinstance(rows, list):
            return
        if len(rows) > self.config.max_table_rows:
            raise ValueError(f"Table exceeds {self.config.max_table_rows} rows")
        for row_index, cells in enumerate(rows):
            if not isinstance(cells, list):
                continue
            row_id = _derived_id(digest, "table-row", f"{table.id}:{row_index}")
            row = DocumentNode(
                id=row_id,
                type=NodeType.TABLE_ROW,
                parent_id=table.id,
                page_number=table.page_number,
                reading_order=row_index,
                semantic_role="table_row",
            )
            tree.nodes[row_id] = row
            table.children_ids.append(row_id)
            if len(cells) > self.config.max_table_columns:
                raise ValueError(f"Table exceeds {self.config.max_table_columns} columns")
            for cell_index, value in enumerate(cells):
                cell = value if isinstance(value, dict) else {"text": str(value)}
                cell_id = _derived_id(digest, "table-cell", f"{row_id}:{cell_index}")
                raw_bbox = cell.get("bbox") or cell.get("cell_bbox")
                cell_bbox = None
                if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
                    try:
                        values = [float(item) for item in raw_bbox]
                        if min(values) >= 0 and max(values) <= 1:
                            cell_bbox = BoundingBox(
                                x0=values[0],
                                y0=values[1],
                                x1=values[2],
                                y1=values[3],
                            )
                    except (TypeError, ValueError):
                        cell_bbox = None
                tree.nodes[cell_id] = DocumentNode(
                    id=cell_id,
                    type=NodeType.TABLE_CELL,
                    parent_id=row_id,
                    page_number=table.page_number,
                    reading_order=cell_index,
                    semantic_role="table_cell",
                    text=str(cell.get("text", ""))[:100_000],
                    bbox=cell_bbox,
                    confidence=_confidence(
                        _bounded_float(cell.get("score"), 0.7),
                        {"provider_confidence": _bounded_float(cell.get("score"), 0.7)},
                    ),
                    provenance=list(table.provenance),
                    attributes={
                        key: cell[key]
                        for key in ("header", "rowspan", "colspan")
                        if key in cell
                    },
                )
                row.children_ids.append(cell_id)

    def _validate_table_limits(self, tree: DocumentTree) -> None:
        total_cells = 0
        for table in tree.nodes.values():
            if table.type != NodeType.TABLE.value:
                continue
            rows = table.attributes.get("table_rows")
            if not isinstance(rows, list):
                continue
            if len(rows) > self.config.max_table_rows:
                raise ValueError(f"Table exceeds {self.config.max_table_rows} rows")
            for row in rows:
                if not isinstance(row, list):
                    continue
                if len(row) > self.config.max_table_columns:
                    raise ValueError(
                        f"Table exceeds {self.config.max_table_columns} columns"
                    )
                total_cells += len(row)
                if total_cells > self.config.max_table_cells:
                    raise ValueError(
                        f"Document exceeds {self.config.max_table_cells} table cells"
                    )

    @staticmethod
    def _materialize_forms(tree: DocumentTree, digest: str) -> None:
        for page in tree.pages:
            for node_id in list(page.content_node_ids):
                source = tree.nodes[node_id]
                if source.type == NodeType.CHECKBOX.value:
                    state = str(source.attributes.get("state", "unknown")).casefold()
                    if state not in {"checked", "unchecked", "unknown"}:
                        state = "unknown"
                    source.form_field = FormFieldData(
                        label=source.text or "checkbox",
                        field_kind="checkbox",
                        state=state,
                        label_node_id=source.id,
                    )
                    continue
                if source.type not in {
                    NodeType.PARAGRAPH.value,
                    NodeType.OCR_BLOCK.value,
                }:
                    continue
                match = re.match(r"^\s*([^:\n]{1,200})\s*:\s*(.{0,2000})\s*$", source.text or "")
                if not match:
                    continue
                label, value = (item.strip() for item in match.groups())
                form_id = _derived_id(digest, "form-field", source.id)
                form = DocumentNode(
                    id=form_id,
                    type=NodeType.FORM_FIELD,
                    parent_id=source.parent_id,
                    page_number=source.page_number,
                    bbox=source.bbox,
                    source_bbox=source.source_bbox,
                    reading_order=source.reading_order,
                    semantic_role="form_field",
                    text=source.text,
                    confidence=source.confidence,
                    provenance=[Provenance(source="deterministic_form_pairing")],
                    relationships=[Relationship(type="derived_from", target_id=source.id)],
                    form_field=FormFieldData(
                        label=label,
                        value=value,
                        label_node_id=source.id,
                        value_node_id=source.id,
                    ),
                )
                tree.nodes[form_id] = form
                if source.parent_id:
                    tree.nodes[source.parent_id].children_ids.append(form_id)

    @staticmethod
    def _associate_captions(tree: DocumentTree, page: PageRecord) -> None:
        figures: list[DocumentNode] = []
        for node_id in page.content_node_ids:
            node = tree.nodes[node_id]
            if node.type in {
                NodeType.FIGURE.value,
                NodeType.IMAGE.value,
                NodeType.CHART.value,
            }:
                figures.append(node)
            elif node.type == NodeType.CAPTION.value and figures:
                figure = figures[-1]
                old_parent = tree.nodes[node.parent_id] if node.parent_id else None
                if old_parent and node.id in old_parent.children_ids:
                    old_parent.children_ids.remove(node.id)
                node.parent_id = figure.id
                figure.children_ids.append(node.id)
                figure.attributes["caption"] = node.text or ""
                if figure.visual_analysis:
                    figure.visual_analysis.title = node.text or ""
                    figure.visual_analysis.source_node_ids.append(node.id)
                node.relationships.append(
                    Relationship(type="caption_of", target_id=figure.id)
                )

    @staticmethod
    def _resolve_repeated_decorations(tree: DocumentTree) -> None:
        groups: dict[tuple[str, str], list[DocumentNode]] = {}
        for page in tree.pages:
            for node_id in page.content_node_ids:
                node = tree.nodes[node_id]
                if node.type not in {NodeType.HEADER.value, NodeType.FOOTER.value}:
                    continue
                key = (node.type, " ".join((node.text or "").casefold().split()))
                if key[1]:
                    groups.setdefault(key, []).append(node)
        minimum = max(3, math.ceil(len(tree.pages) * 0.6))
        for nodes in groups.values():
            if len(nodes) < minimum:
                continue
            canonical = nodes[0]
            pages = [node.page_number for node in nodes if node.page_number is not None]
            canonical.attributes["repeat_pages"] = pages
            for node in nodes:
                node.attributes["repeated_decoration"] = True
                if node.id != canonical.id:
                    node.relationships.append(
                        Relationship(type="repeats", target_id=canonical.id)
                    )

    @staticmethod
    def _link_page_continuations(tree: DocumentTree) -> None:
        decorations = {NodeType.HEADER.value, NodeType.FOOTER.value}
        for left_page, right_page in zip(tree.pages, tree.pages[1:], strict=False):
            left_nodes = [
                tree.nodes[node_id]
                for node_id in left_page.content_node_ids
                if tree.nodes[node_id].type not in decorations
            ]
            right_nodes = [
                tree.nodes[node_id]
                for node_id in right_page.content_node_ids
                if tree.nodes[node_id].type not in decorations
            ]
            if not left_nodes or not right_nodes:
                continue
            left = left_nodes[-1]
            right = right_nodes[0]
            continued_table = (
                left.type == NodeType.TABLE.value
                and right.type == NodeType.TABLE.value
            )
            continued_paragraph = (
                left.type in {NodeType.PARAGRAPH.value, NodeType.OCR_BLOCK.value}
                and right.type == left.type
                and bool(left.text)
                and (left.text or "").rstrip()[-1:] not in ".!?;:"
            )
            if continued_table or continued_paragraph:
                left.relationships.append(
                    Relationship(type="continues", target_id=right.id, confidence=0.8)
                )

    @staticmethod
    def _attach_links(
        tree: DocumentTree,
        page_node: DocumentNode,
        page: PageEvidence,
        all_pages: list[PageEvidence],
    ) -> None:
        for raw in page.links:
            source = raw.get("from")
            if source is None:
                continue
            bbox = BoundingBox(
                x0=max(0, min(1, float(source.x0) / page.width)),
                y0=max(0, min(1, float(source.y0) / page.height)),
                x1=max(0, min(1, float(source.x1) / page.width)),
                y1=max(0, min(1, float(source.y1) / page.height)),
            )
            target = _matching_node(tree, page, bbox) or page_node
            uri = str(raw.get("uri", ""))
            if uri and urlparse(uri).scheme.lower() in {"http", "https", "mailto"}:
                target.links.append(DocumentLink(uri=uri, bbox=bbox))
            destination = raw.get("page")
            if isinstance(destination, int) and 0 <= destination < len(all_pages):
                target.relationships.append(
                    Relationship(
                        type="internal_link",
                        target_id=tree.pages[destination].id,
                    )
                )

    @staticmethod
    def _crop_asset(
        page: PageEvidence, node_id: str, bbox: BoundingBox
    ) -> tuple[str, bytes]:
        with Image.open(page.image_path) as image:
            width, height = image.size
            crop = image.crop(
                (
                    int(bbox.x0 * width),
                    int(bbox.y0 * height),
                    max(int(bbox.x1 * width), int(bbox.x0 * width) + 1),
                    max(int(bbox.y1 * height), int(bbox.y0 * height) + 1),
                )
            )
            from io import BytesIO

            buffer = BytesIO()
            crop.save(buffer, "PNG")
        path = f"assets/page-{page.number:04d}-{node_id}.png"
        return path, buffer.getvalue()

    def _resolve_windows(
        self, tree: DocumentTree, gateway: OpenAIDocumentGateway
    ) -> None:
        for start in range(0, len(tree.pages), 10):
            window = tree.pages[start : start + 12]
            ids = [node_id for page in window for node_id in page.content_node_ids]
            summary = [
                {
                    "id": node_id,
                    "page": tree.nodes[node_id].page_number,
                    "type": tree.nodes[node_id].type,
                    "role": tree.nodes[node_id].semantic_role,
                    "text": (tree.nodes[node_id].text or "")[:1000],
                }
                for node_id in ids
            ]
            try:
                resolution, run = gateway.resolve_document(summary)
                tree.model_runs.append(run)
                self._apply_resolution(tree, resolution, set(ids))
            except Exception as exc:  # noqa: BLE001 - provider fallback boundary
                tree.warnings.append(
                    f"Cross-page resolution fallback ({type(exc).__name__})"
                )

    @staticmethod
    def _apply_resolution(
        tree: DocumentTree, resolution: DocumentResolution, allowed_ids: set[str]
    ) -> None:
        for update in resolution.updates:
            if update.node_id not in allowed_ids or update.node_id not in tree.nodes:
                continue
            node = tree.nodes[update.node_id]
            if update.semantic_role:
                node.semantic_role = update.semantic_role
            if update.heading_level:
                node.attributes["heading_level"] = update.heading_level
        for relation in resolution.relationships:
            if (
                relation.source_id not in allowed_ids
                or relation.target_id not in allowed_ids
            ):
                continue
            tree.nodes[relation.source_id].relationships.append(
                Relationship(
                    type=relation.type,
                    target_id=relation.target_id,
                    confidence=relation.confidence,
                )
            )
        tree.warnings.extend(resolution.warnings)

    @staticmethod
    def _populate_citations(tree: DocumentTree) -> None:
        for node in tree.nodes.values():
            bbox = node.bbox
            source_bbox = node.source_bbox
            scope = GroundingScope.EXACT if bbox is not None else GroundingScope.AGGREGATE
            parent_citation_id = None
            evidence_source = node.provenance[0].source if node.provenance else "derived"
            if node.type == NodeType.PAGE.value:
                bbox = BoundingBox(x0=0, y0=0, x1=1, y1=1)
                scope = GroundingScope.EXACT
                evidence_source = "render"
            elif node.type == NodeType.TABLE_CELL.value and bbox is None:
                current = tree.nodes[node.parent_id] if node.parent_id else None
                while current and current.type != NodeType.TABLE.value:
                    current = tree.nodes[current.parent_id] if current.parent_id else None
                if current and current.bbox:
                    bbox = current.bbox
                    source_bbox = current.source_bbox
                    scope = GroundingScope.TABLE
                    parent_citation_id = f"cite-{current.id}"
                    evidence_source = "inherited_table"
                else:
                    scope = GroundingScope.UNRESOLVED
            elif bbox is None and node.type not in {
                NodeType.DOCUMENT.value,
                NodeType.SECTION.value,
                NodeType.LIST.value,
                NodeType.TABLE_ROW.value,
            }:
                scope = GroundingScope.UNRESOLVED
            node.citations = [
                Citation(
                    id=f"cite-{node.id}",
                    source_node_id=node.id,
                    page_number=node.page_number,
                    bbox=bbox,
                    source_bbox=source_bbox,
                    confidence=node.confidence.score if node.confidence else 0.5,
                    evidence_source=evidence_source,
                    grounding_scope=scope,
                    parent_citation_id=parent_citation_id,
                )
            ]

    @staticmethod
    def _attach_table_citation_metadata(tree: DocumentTree) -> None:
        for table in tree.nodes.values():
            if table.type != NodeType.TABLE.value:
                continue
            rows = table.attributes.get("table_rows")
            if not isinstance(rows, list):
                continue
            for row_index, row_id in enumerate(table.children_ids):
                if row_index >= len(rows) or not isinstance(rows[row_index], list):
                    continue
                row = tree.nodes[row_id]
                for cell_index, cell_id in enumerate(row.children_ids):
                    if cell_index >= len(rows[row_index]):
                        continue
                    raw = rows[row_index][cell_index]
                    cell_data = raw if isinstance(raw, dict) else {"text": str(raw)}
                    cell = tree.nodes[cell_id]
                    citation = cell.citations[0]
                    cell_data["citation_id"] = citation.id
                    cell_data["grounding_scope"] = citation.grounding_scope.value
                    cell_data["page_number"] = citation.page_number
                    cell_data["confidence"] = citation.confidence
                    if citation.bbox:
                        cell_data["bbox"] = citation.bbox.model_dump(mode="json")
                    rows[row_index][cell_index] = cell_data

    @staticmethod
    def _validate_tree(tree: DocumentTree) -> None:
        node_ids = set(tree.nodes)
        page_numbers = {page.number for page in tree.pages}
        for node in tree.nodes.values():
            if node.parent_id and node.parent_id not in node_ids:
                raise ValueError(f"Dangling parent ID: {node.parent_id}")
            if any(child not in node_ids for child in node.children_ids):
                raise ValueError(f"Dangling child ID on node {node.id}")
            if any(rel.target_id not in node_ids for rel in node.relationships):
                raise ValueError(f"Dangling relationship on node {node.id}")
            for child_id in node.children_ids:
                if tree.nodes[child_id].parent_id != node.id:
                    raise ValueError(f"Non-reciprocal child on node {node.id}")
        for node in tree.nodes.values():
            seen: set[str] = set()
            current = node
            while current.parent_id:
                if current.id in seen:
                    raise ValueError(f"Hierarchy cycle at node {node.id}")
                seen.add(current.id)
                current = tree.nodes[current.parent_id]
            if node.visual_analysis and any(
                source_id not in node_ids
                for source_id in node.visual_analysis.source_node_ids
            ):
                raise ValueError(f"Unknown visual source node on {node.id}")
            if any(citation.source_node_id not in node_ids for citation in node.citations):
                raise ValueError(f"Unknown citation source on {node.id}")
        for field in tree.grounded_fields:
            if any(source_id not in node_ids for source_id in field.source_node_ids):
                raise ValueError(f"Unknown source node for field {field.path}")
            if any(source.node_id not in node_ids for source in field.sources):
                raise ValueError(f"Unknown field source for {field.path}")
        logical_ids = {table.id for table in tree.logical_tables}
        for table in tree.logical_tables:
            if any(node_id not in node_ids for node_id in table.source_table_node_ids):
                raise ValueError(f"Unknown source node for logical table {table.id}")
        for extraction in tree.schema_extractions:
            for path, provenance in extraction.provenance.items():
                if path != provenance.path:
                    raise ValueError(f"Mismatched extraction provenance path: {path}")
                for citation in provenance.citations:
                    if citation.node_id not in node_ids:
                        raise ValueError(f"Unknown extraction source node: {citation.node_id}")
                    if (
                        citation.logical_table_id is not None
                        and citation.logical_table_id not in logical_ids
                    ):
                        raise ValueError(
                            f"Unknown logical table: {citation.logical_table_id}"
                        )
        for failure in tree.failure_cases:
            if any(node_id not in node_ids for node_id in failure.node_ids):
                raise ValueError(f"Unknown failure source node: {failure.id}")
            if failure.page_number is not None and failure.page_number not in page_numbers:
                raise ValueError(f"Unknown failure source page: {failure.id}")
