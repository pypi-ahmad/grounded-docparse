from __future__ import annotations

import hashlib
from collections import defaultdict
from types import ModuleType

import pymupdf

from .config import ParserConfig
from .models import Element, RunUsage
from .native import (
    NativeDocument,
    NativeElement,
    NativeParseResult,
    PageRoute,
    PdfSourceAnchor,
    ProcessingType,
    SourceFormat,
    SourceSpan,
    SourceUnit,
    render_native_document,
)
from .pipeline import DocumentParser
from .render import build_elements, render_agentic_document, render_annotated_pdf
from .universal import (
    MixedNativePageUnusable,
    NativePdfRequiresMixed,
    PdfInspection,
)


def _pdf_inspector() -> ModuleType:
    try:
        import pdf_inspector
    except ImportError as exc:
        raise RuntimeError(
            "native PDF parsing requires grounded-docparse[native]"
        ) from exc
    return pdf_inspector


def _subset_pdf(data: bytes, pages: list[int]) -> bytes:
    with pymupdf.open(stream=data, filetype="pdf") as source:
        output = pymupdf.open()
        try:
            for page in pages:
                output.insert_pdf(source, from_page=page - 1, to_page=page - 1)
            return output.tobytes(garbage=3, deflate=True)
        finally:
            output.close()


def _native_type(item, roles: dict[tuple[int, int], str]) -> str:
    role = roles.get((item.page, item.mcid)) if item.mcid is not None else None
    if role:
        return role.casefold()
    return str(item.item_type or "text").casefold()


class PdfInspectorParser:
    def __init__(
        self,
        config: ParserConfig,
        legacy_parser: DocumentParser,
        *,
        pdf_module: ModuleType | None = None,
    ) -> None:
        self.config = config
        self.legacy_parser = legacy_parser
        self.pdf_module = pdf_module or _pdf_inspector()

    def parse(
        self,
        data: bytes,
        filename: str,
        *,
        processing_type: ProcessingType,
        page_routes: dict[int, PageRoute] | None,
        inspection: PdfInspection,
        progress_callback=None,
        refine_markdown: bool = True,
        visual_recovery: bool = True,
    ) -> NativeParseResult:
        routes = (
            {page: PageRoute.NATIVE for page in range(1, inspection.page_count + 1)}
            if processing_type is ProcessingType.NATIVE_PDF
            else dict(page_routes or {})
        )
        native_pages = [page for page, route in routes.items() if route is PageRoute.NATIVE]
        ocr_pages = [page for page, route in routes.items() if route is PageRoute.OCR]
        unusable_native = set(native_pages) & set(inspection.pages_needing_ocr)
        if unusable_native:
            if processing_type is ProcessingType.NATIVE_PDF:
                raise NativePdfRequiresMixed(unusable_native)
            raise MixedNativePageUnusable(unusable_native)

        page_markdown: dict[int, str] = {}
        native_items = []
        roles: dict[tuple[int, int], str] = {}
        if native_pages:
            extracted = self.pdf_module.extract_pages_markdown_bytes(
                data, pages=[page - 1 for page in native_pages]
            )
            unusable = {
                page.page + 1 for page in extracted.pages if page.needs_ocr
            }
            if unusable:
                if processing_type is ProcessingType.NATIVE_PDF:
                    raise NativePdfRequiresMixed(unusable)
                raise MixedNativePageUnusable(unusable)
            page_markdown.update(
                (page.page + 1, page.markdown) for page in extracted.pages
            )
            native_items = self.pdf_module.extract_text_with_positions_bytes(
                data, pages=native_pages
            )
            roles = {
                (item.page, item.mcid): item.role
                for item in self.pdf_module.extract_structure_elements_bytes(
                    data, pages=native_pages
                )
            }

        ocr_result = None
        ocr_page_map: dict[int, int] = {}
        if ocr_pages:
            subset = _subset_pdf(data, ocr_pages)
            ocr_result = self.legacy_parser.parse(
                subset,
                filename,
                progress_callback=progress_callback,
                refine_markdown=refine_markdown,
                visual_recovery=visual_recovery,
            )
            ocr_page_map = {
                subset_page: source_page
                for subset_page, source_page in enumerate(ocr_pages, start=1)
            }
            for page in ocr_result.document.pages:
                source_page = ocr_page_map[page.number]
                copied = page.model_copy(deep=True, update={"number": source_page})
                rendered = render_agentic_document(
                    ocr_result.document.model_copy(update={"pages": [copied]})
                )
                page_markdown[source_page] = rendered.markdown

        with pymupdf.open(stream=data, filetype="pdf") as source:
            page_sizes = {
                index + 1: (page.rect.width, page.rect.height)
                for index, page in enumerate(source)
            }

        base_parts: list[str] = []
        elements: list[NativeElement] = []
        annotation_elements: list[Element] = []
        reading_order: defaultdict[int, int] = defaultdict(int)
        base_length = 0
        candidates: defaultdict[
            int, list[tuple[int, str, str, tuple[float, float, float, float] | None]]
        ] = defaultdict(list)

        def add_element(
            *, page: int, text: str, kind: str, bbox: tuple[float, float, float, float] | None
        ) -> None:
            nonlocal base_length
            if not text:
                return
            if base_parts:
                base_parts.append("\n")
                base_length += 1
            start = base_length
            base_parts.append(text)
            end = start + len(text)
            base_length = end
            reading_order[page] += 1
            element_id = f"p{page}-e{reading_order[page]}"
            anchor = PdfSourceAnchor(
                unit_id=f"page-{page}", page=page, bbox=bbox
            )
            elements.append(
                NativeElement(
                    id=element_id,
                    type=kind,
                    text=text,
                    reading_order=reading_order[page] - 1,
                    source=SourceSpan(
                        start=start, end=end, element_id=element_id, anchor=anchor
                    ),
                )
            )
            annotation_elements.append(
                Element(
                    id=element_id,
                    type=kind,
                    page=page,
                    bbox=bbox,
                    text=text,
                    reading_order=reading_order[page],
                )
            )

        for item in native_items:
            width, height = page_sizes[item.page]
            bbox = (
                max(0.0, item.x / width),
                max(0.0, item.y / height),
                min(1.0, (item.x + item.width) / width),
                min(1.0, (item.y + item.height) / height),
            )
            candidates[item.page].append(
                (len(candidates[item.page]), item.text, _native_type(item, roles), bbox)
            )

        if ocr_result is not None:
            ocr_elements = ocr_result.elements or build_elements(ocr_result.document)
            for item in sorted(ocr_elements, key=lambda value: (value.page, value.reading_order)):
                source_page = ocr_page_map[item.page]
                candidates[source_page].append(
                    (item.reading_order, item.text, str(item.type), item.bbox)
                )

        for page in range(1, inspection.page_count + 1):
            for _order, text, kind, bbox in sorted(candidates[page]):
                add_element(page=page, text=text, kind=kind, bbox=bbox)

        units = []
        for page in range(1, inspection.page_count + 1):
            warnings = []
            if page in inspection.pages_with_tables:
                warnings.append("table layout detected")
            if page in inspection.pages_with_columns:
                warnings.append("multi-column layout detected")
            units.append(
                SourceUnit(
                    id=f"page-{page}",
                    kind="page",
                    index=page,
                    requested_route=routes[page],
                    effective_route=routes[page],
                    parser=(
                        "pdf-inspector"
                        if routes[page] is PageRoute.NATIVE
                        else self.config.ocr_engine.value
                    ),
                    warnings=warnings,
                )
            )
        document = NativeDocument(
            source_name=filename,
            source_sha256=hashlib.sha256(data).hexdigest(),
            source_format=SourceFormat.PDF,
            requested_processing_type=processing_type,
            base_text="".join(base_parts),
            units=units,
            elements=elements,
        )
        markdown = "\n\n".join(
            f"<!-- Page {page} -->\n\n{page_markdown.get(page, '').strip()}"
            for page in range(1, inspection.page_count + 1)
        ).rstrip()
        rendered = render_native_document(document, markdown=markdown)
        annotated_pdf = render_annotated_pdf(
            data,
            filename,
            annotation_elements,
            page_count=inspection.page_count,
        )
        usage = (
            ocr_result.usage.model_copy(deep=True)
            if ocr_result is not None and ocr_result.usage is not None
            else RunUsage()
        )
        return NativeParseResult(
            document=document,
            markdown=rendered.markdown,
            json=rendered.json,
            annotated_pdf=annotated_pdf,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            usage=usage,
            trace=list(ocr_result.trace or []) if ocr_result is not None else [],
        )


class DoclingNativeParser:
    def __init__(self, config: ParserConfig) -> None:
        self.config = config

    def parse(self, *_args, **_kwargs):
        raise NotImplementedError("Docling native parsing is implemented in a later slice")
