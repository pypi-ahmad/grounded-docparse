from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .config import ParserConfig
from .extraction import DocumentExtractor
from .gateways import OpenAIDocumentGateway
from .models import (
    AgenticAnalysis,
    AgenticFeatureMetadata,
    AgentTraceEvent,
    Block,
    ChatAnswer,
    ChatSource,
    ClassifierProfile,
    Document,
    DocumentClassification,
    Element,
    ExtractedField,
    ExtractionResult,
    FormClassificationResult,
    FormSegment,
    NodeType,
    ParseResult,
    RoutedExtractionResult,
    RunUsage,
    SegmentExtraction,
    TableOfContents,
    TocSection,
    VerificationState,
)
from .render import build_elements, render_agentic_document, render_markdown

MAX_CONTEXT_CHARACTERS = 48_000
MAX_CONTEXT_PAGES = 8
MAX_CHAT_TURN_PAIRS = 8


@dataclass(frozen=True, slots=True)
class AgenticContext:
    page_numbers: tuple[int, ...]
    markdown: str
    layout: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PreparedDocumentContext:
    page_markdown: dict[int, str]
    contexts: tuple[AgenticContext, ...]
    elements: tuple[Element, ...]


def _profile_fingerprint(profile: ClassifierProfile) -> str:
    payload = profile.model_dump_json(exclude_none=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _category_map(profile: ClassifierProfile) -> dict[str, object]:
    return {category.key: category for category in profile.categories}


def _validate_segmentation(
    raw_segments,
    context: AgenticContext,
    profile: ClassifierProfile,
) -> list[str]:
    issues: list[str] = []
    expected_pages = list(context.page_numbers)
    category_keys = {category.key for category in profile.categories} | {"other"}
    element_pages = {item["id"]: item["page"] for item in context.layout}
    covered: list[int] = []
    previous_end = expected_pages[0] - 1 if expected_pages else 0
    for index, segment in enumerate(raw_segments):
        if segment.start_page > segment.end_page:
            issues.append(f"segment {index} has an inverted page range")
            continue
        if segment.start_page != previous_end + 1:
            issues.append(f"segment {index} does not start after the previous segment")
        previous_end = segment.end_page
        covered.extend(range(segment.start_page, segment.end_page + 1))
        if segment.category not in category_keys:
            issues.append(f"segment {index} uses unknown category {segment.category!r}")
        if segment.category != "other" and not segment.evidence_element_ids:
            issues.append(f"segment {index} has no grounded evidence")
        for element_id in segment.evidence_element_ids:
            page = element_pages.get(element_id)
            if page is None:
                issues.append(f"segment {index} cites unknown element {element_id!r}")
            elif not segment.start_page <= page <= segment.end_page:
                issues.append(f"segment {index} cites evidence outside its page range")
    if covered != expected_pages:
        issues.append("segments must cover every supplied page exactly once")
    return issues


def _validate_effective_segments(
    result: FormClassificationResult,
    parse_result: ParseResult,
) -> None:
    if result.profile_fingerprint != _profile_fingerprint(result.profile):
        raise ValueError("classifier profile changed after classification")
    pages = [page.number for page in parse_result.document.pages]
    covered = [
        page
        for segment in sorted(result.segments, key=lambda item: item.start_page)
        for page in range(segment.start_page, segment.end_page + 1)
    ]
    if covered != pages:
        raise ValueError("reviewed form segments must cover every page exactly once")
    categories = _category_map(result.profile)
    for segment in result.segments:
        if not segment.approved:
            raise ValueError(f"form segment {segment.id} requires review")
        if segment.category != "other" and segment.category not in categories:
            raise ValueError(f"form segment {segment.id} has an unknown category")
        expected = categories.get(segment.category)
        expected_eligible = bool(expected and expected.extract)
        expected_schema = expected.schema_name if expected_eligible else None
        if segment.eligible != expected_eligible or segment.schema_name != expected_schema:
            raise ValueError(f"form segment {segment.id} routing metadata is stale")


def _segment_extraction_payload(item: SegmentExtraction) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "segment_id": item.segment_id,
        "category": item.category,
        "start_page": item.start_page,
        "end_page": item.end_page,
        "schema_name": item.schema_name,
        "status": item.status,
        "error": item.error,
    }
    if item.extraction is not None:
        payload.update(
            {
                "data": item.extraction.data,
                "evidence": item.extraction.evidence,
                "fields": {
                    name: field.model_dump(mode="json")
                    for name, field in item.extraction.fields.items()
                },
                "warnings": item.extraction.warnings,
            }
        )
    return payload


def _walk(blocks: Iterable[Block]) -> Iterable[Block]:
    for block in sorted(blocks, key=lambda item: item.reading_order):
        yield block
        yield from _walk(block.children)


def _active_elements(result: ParseResult) -> list[Element]:
    rejected = {
        block.id
        for page in result.document.pages
        for block in _walk(page.blocks)
        if block.verification is VerificationState.REJECTED
    }
    elements = result.elements or build_elements(result.document)
    return [element for element in elements if element.id not in rejected]


def _page_markdown(result: ParseResult) -> dict[int, str]:
    separator = "\n\n<!-- PAGE BREAK -->\n\n"
    parts = result.markdown.rstrip().split(separator)
    if len(parts) == len(result.document.pages):
        return {
            page.number: f"{part.rstrip()}\n"
            for page, part in zip(result.document.pages, parts, strict=True)
        }
    return {
        page.number: render_markdown(
            Document(
                source_name=result.document.source_name,
                source_sha256=result.document.source_sha256,
                pages=[page.model_copy(deep=True)],
            )
        )
        for page in result.document.pages
    }


def _prepare_agentic_context(result: ParseResult) -> PreparedDocumentContext:
    elements = _active_elements(result)
    by_page: dict[int, list[Element]] = {}
    for element in elements:
        by_page.setdefault(element.page, []).append(element)
    markdown = _page_markdown(result)
    contexts: list[AgenticContext] = []
    pending_pages: list[int] = []
    pending_markdown: list[str] = []
    pending_layout: list[dict[str, Any]] = []
    pending_size = 0

    def flush() -> None:
        nonlocal pending_pages, pending_markdown, pending_layout, pending_size
        if not pending_pages:
            return
        contexts.append(
            AgenticContext(
                page_numbers=tuple(pending_pages),
                markdown="\n\n<!-- PAGE BREAK -->\n\n".join(pending_markdown),
                layout=list(pending_layout),
            )
        )
        pending_pages, pending_markdown, pending_layout, pending_size = [], [], [], 0

    for page in result.document.pages:
        layout = [
            {
                "id": item.id,
                "type": item.type,
                "page": item.page,
                "order": item.reading_order,
                "text": item.text,
            }
            for item in sorted(by_page.get(page.number, []), key=lambda item: item.reading_order)
        ]
        page_markdown = markdown.get(page.number, "")
        size = len(page_markdown) + len(json.dumps(layout, ensure_ascii=False))
        if size > MAX_CONTEXT_CHARACTERS and layout:
            flush()
            group: list[dict[str, Any]] = []
            group_size = 0
            for record in layout:
                record_size = len(json.dumps(record, ensure_ascii=False))
                if record_size > MAX_CONTEXT_CHARACTERS:
                    if group:
                        contexts.append(
                            AgenticContext(
                                page_numbers=(page.number,),
                                markdown="\n\n".join(item["text"] for item in group),
                                layout=group,
                            )
                        )
                        group, group_size = [], 0
                    text = record["text"]
                    for start in range(0, len(text), MAX_CONTEXT_CHARACTERS // 2):
                        sliced = {**record, "text": text[start : start + MAX_CONTEXT_CHARACTERS // 2]}
                        contexts.append(
                            AgenticContext(
                                page_numbers=(page.number,),
                                markdown=sliced["text"],
                                layout=[sliced],
                            )
                        )
                    continue
                if group and group_size + record_size > MAX_CONTEXT_CHARACTERS:
                    contexts.append(
                        AgenticContext(
                            page_numbers=(page.number,),
                            markdown="\n\n".join(item["text"] for item in group),
                            layout=group,
                        )
                    )
                    group, group_size = [], 0
                group.append(record)
                group_size += record_size
            if group:
                contexts.append(
                    AgenticContext(
                        page_numbers=(page.number,),
                        markdown="\n\n".join(item["text"] for item in group),
                        layout=group,
                    )
                )
            continue
        if pending_pages and (
            len(pending_pages) >= MAX_CONTEXT_PAGES
            or pending_size + size > MAX_CONTEXT_CHARACTERS
        ):
            flush()
        pending_pages.append(page.number)
        pending_markdown.append(page_markdown)
        pending_layout.extend(layout)
        pending_size += size
    flush()
    return PreparedDocumentContext(
        page_markdown=markdown,
        contexts=tuple(contexts),
        elements=tuple(elements),
    )


def _flatten_sections(sections: Iterable[TocSection]) -> list[TocSection]:
    flat: list[TocSection] = []
    for section in sections:
        flat.append(section.model_copy(update={"children": []}))
        flat.extend(_flatten_sections(section.children))
    return flat


def _nest_sections(sections: Iterable[TocSection]) -> list[TocSection]:
    roots: list[TocSection] = []
    stack: list[TocSection] = []
    for source in sections:
        section = source.model_copy(deep=True, update={"children": []})
        while stack and stack[-1].level >= section.level:
            stack.pop()
        if stack:
            stack[-1].children.append(section)
        else:
            roots.append(section)
        stack.append(section)
    return roots


def _fallback_toc(result: ParseResult) -> TableOfContents:
    sections = []
    for page in result.document.pages:
        for block in _walk(page.blocks):
            if block.verification is VerificationState.REJECTED:
                continue
            if block.type is NodeType.HEADING and block.text.strip():
                sections.append(
                    TocSection(
                        title=block.text.strip(),
                        level=block.heading_level or 1,
                        page=page.number,
                        element_id=block.id,
                    )
                )
    return TableOfContents(sections=_nest_sections(sections))


def _validate_toc(
    toc: TableOfContents,
    elements: dict[str, Element],
    valid_pages: set[int],
) -> TableOfContents:
    flat = []
    for section in _flatten_sections(toc.sections):
        title = re.sub(r"^\s{0,3}#{1,6}[ \t]+", "", section.title).strip()
        if not title:
            raise ValueError("TOC title is empty after Markdown normalization")
        section = section.model_copy(update={"title": title})
        if section.page not in valid_pages:
            raise ValueError(f"TOC page {section.page} is outside the document")
        if section.element_id is not None:
            element = elements.get(section.element_id)
            if element is None or element.page != section.page:
                raise ValueError(f"invalid TOC element {section.element_id}")
        flat.append(section)
    flat.sort(key=lambda item: (item.page, elements.get(item.element_id).reading_order if item.element_id in elements else 10**9))
    return TableOfContents(sections=_nest_sections(flat))


def _feature_error(name: str, started: float, exc: Exception) -> AgenticFeatureMetadata:
    return AgenticFeatureMetadata(
        status="failed",
        duration_ms=round((time.perf_counter() - started) * 1000),
        warnings=[f"{name} failed: {type(exc).__name__}: {exc}"],
    )


class DocumentAgent:
    def __init__(
        self,
        config: ParserConfig | None = None,
        *,
        gateway_factory: Callable[[ParserConfig], object] = OpenAIDocumentGateway,
    ) -> None:
        self.config = config or ParserConfig.from_env()
        self.gateway_factory = gateway_factory

    @staticmethod
    def prepare(parse_result: ParseResult) -> PreparedDocumentContext:
        return _prepare_agentic_context(parse_result)

    def analyze(
        self,
        parse_result: ParseResult,
        *,
        classify: bool = True,
        generate_toc: bool = True,
        prepared_context: PreparedDocumentContext | None = None,
    ) -> AgenticAnalysis:
        features: dict[str, AgenticFeatureMetadata] = {}
        if not os.getenv("OPENAI_API_KEY") and self.gateway_factory is OpenAIDocumentGateway:
            for name, enabled in (("classification", classify), ("toc", generate_toc)):
                features[name] = AgenticFeatureMetadata(
                    status="unavailable" if enabled else "off",
                    warnings=["OPENAI_API_KEY is not set"] if enabled else [],
                )
            return AgenticAnalysis(features=features)

        prepared = prepared_context or self.prepare(parse_result)
        contexts = prepared.contexts
        elements = {element.id: element for element in prepared.elements}
        valid_pages = {page.number for page in parse_result.document.pages}

        def classify_document():
            started = time.perf_counter()
            gateway = self.gateway_factory(self.config)
            page_markdown = prepared.page_markdown
            context = AgenticContext(
                page_numbers=tuple(
                    page.number for page in parse_result.document.pages[:2]
                ),
                markdown="\n\n<!-- PAGE BREAK -->\n\n".join(
                    page_markdown.get(page.number, "")
                    for page in parse_result.document.pages[:2]
                )[:MAX_CONTEXT_CHARACTERS],
                layout=[
                    record
                    for item in contexts
                    for record in item.layout
                    if record["page"] <= 2
                ],
            )
            result = gateway.classify_document(context.markdown, context.layout)
            return result, gateway, started

        def generate_document_toc():
            started = time.perf_counter()
            gateway = self.gateway_factory(self.config)
            sections: list[TocSection] = []
            for context in contexts:
                generated = gateway.generate_toc(context.markdown, context.layout)
                generated = _validate_toc(
                    generated, elements, valid_pages
                )
                sections.extend(_flatten_sections(generated.sections))
            deduplicated = []
            seen = set()
            for section in sections:
                key = (section.element_id, section.title.casefold(), section.page)
                if key not in seen:
                    seen.add(key)
                    deduplicated.append(section)
            toc = _validate_toc(
                TableOfContents(sections=_nest_sections(deduplicated)),
                elements,
                valid_pages,
            )
            return toc, gateway, started

        jobs = {}
        job_started: dict[str, float] = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="docparse-agentic") as executor:
            if classify:
                job_started["classification"] = time.perf_counter()
                jobs["classification"] = executor.submit(classify_document)
            else:
                features["classification"] = AgenticFeatureMetadata(status="off")
            if generate_toc:
                job_started["toc"] = time.perf_counter()
                jobs["toc"] = executor.submit(generate_document_toc)
            else:
                features["toc"] = AgenticFeatureMetadata(status="off")

        classification: DocumentClassification | None = None
        toc: TableOfContents | None = None
        usage = RunUsage()
        trace: list[AgentTraceEvent] = []
        for name, future in jobs.items():
            try:
                value, gateway, started = future.result()
                if name == "classification":
                    classification = value
                else:
                    toc = value
                features[name] = AgenticFeatureMetadata(
                    status="succeeded",
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
                usage.calls.extend(getattr(gateway, "usage", RunUsage()).calls)
                trace.extend(getattr(gateway, "trace", []))
            except Exception as exc:  # noqa: BLE001 - feature failures are isolated
                features[name] = _feature_error(name, job_started[name], exc)
                if name == "toc":
                    toc = _fallback_toc(parse_result)
                    features[name].status = "partial"
                    features[name].warnings.append("Using detected heading fallback")
        return AgenticAnalysis(
            classification=classification,
            toc=toc,
            features=features,
            usage=usage,
            trace=trace,
        )

    def classify_forms(
        self,
        parse_result: ParseResult,
        profile: ClassifierProfile,
        *,
        prepared_context: PreparedDocumentContext | None = None,
        confidence_threshold: float = 0.85,
    ) -> FormClassificationResult:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence threshold must be between 0 and 1")
        prepared = prepared_context or self.prepare(parse_result)
        gateway = self.gateway_factory(self.config)
        profile_payload = {
            "name": profile.name,
            "instructions": profile.instructions,
            "categories": [
                {"key": category.key, "description": category.description}
                for category in profile.categories
            ]
            + [{"key": "other", "description": "No supplied category applies."}],
        }
        predicted = []
        boundary_pages: set[int] = set()
        warnings: list[str] = []
        previous_context: AgenticContext | None = None
        for target_context in prepared.contexts:
            context = target_context
            if previous_context is not None and target_context.page_numbers:
                candidate = previous_context.page_numbers[-1]
                if candidate not in target_context.page_numbers:
                    boundary_pages.add(target_context.page_numbers[0])
                    overlap_layout = [
                        item for item in previous_context.layout if item["page"] == candidate
                    ]
                    context = AgenticContext(
                        page_numbers=(candidate, *target_context.page_numbers),
                        markdown=(
                            prepared.page_markdown.get(candidate, "")
                            + "\n\n<!-- PAGE BREAK -->\n\n"
                            + target_context.markdown
                        ),
                        layout=[*overlap_layout, *target_context.layout],
                    )
            issues: list[str] = []
            raw = None
            for attempt in range(2):
                raw = gateway.classify_forms(
                    context.markdown,
                    context.layout,
                    profile_payload,
                    issues=issues or None,
                )
                issues = _validate_segmentation(raw.segments, context, profile)
                if not issues:
                    break
            if raw is None or issues:
                detail = "; ".join(issues) or "classifier returned no result"
                raise ValueError(f"custom form classification failed validation: {detail}")
            element_pages = {item["id"]: item["page"] for item in context.layout}
            for segment in raw.segments:
                start_page = max(segment.start_page, target_context.page_numbers[0])
                end_page = min(segment.end_page, target_context.page_numbers[-1])
                if start_page > end_page:
                    continue
                evidence = [
                    element_id
                    for element_id in segment.evidence_element_ids
                    if start_page <= element_pages.get(element_id, -1) <= end_page
                ]
                confidence = segment.confidence
                if segment.category != "other" and not evidence:
                    confidence = 0
                    warnings.append(
                        f"Segment {start_page}-{end_page} lost grounded evidence while "
                        "reconciling a classifier window and requires review."
                    )
                predicted.append(
                    segment.model_copy(
                        update={
                            "start_page": start_page,
                            "end_page": end_page,
                            "confidence": confidence,
                            "evidence_element_ids": evidence,
                        }
                    )
                )
            previous_context = target_context

        category_by_key = _category_map(profile)
        segments: list[FormSegment] = []
        for raw in predicted:
            boundary_review = False
            if (
                segments
                and raw.start_page in boundary_pages
                and segments[-1].end_page + 1 == raw.start_page
                and segments[-1].category == raw.category
            ):
                previous = segments.pop()
                raw = raw.model_copy(
                    update={
                        "start_page": previous.start_page,
                        "confidence": min(previous.confidence, raw.confidence),
                        "reasoning": (
                            f"{previous.reasoning} {raw.reasoning}"
                        ).strip(),
                        "evidence_element_ids": list(
                            dict.fromkeys(
                                [*previous.evidence_element_ids, *raw.evidence_element_ids]
                            )
                        ),
                    }
                )
                boundary_review = True
                warnings.append(
                    f"Merged category {raw.category} across a classifier window boundary; "
                    "review the page range."
                )
            category = category_by_key.get(raw.category)
            eligible = bool(category and category.extract)
            auto_approved = raw.confidence >= confidence_threshold and not boundary_review
            segments.append(
                FormSegment(
                    id="pending",
                    predicted_start_page=raw.start_page,
                    predicted_end_page=raw.end_page,
                    predicted_category=raw.category,
                    start_page=raw.start_page,
                    end_page=raw.end_page,
                    category=raw.category,
                    confidence=raw.confidence,
                    reasoning=raw.reasoning,
                    evidence_element_ids=raw.evidence_element_ids,
                    approved=auto_approved,
                    review_status="auto_approved" if auto_approved else "needs_review",
                    eligible=eligible,
                    schema_name=category.schema_name if eligible else None,
                )
            )
        for index, segment in enumerate(segments, start=1):
            segment.id = f"form-{index:03d}"

        usage = getattr(gateway, "usage", RunUsage()).model_copy(deep=True)
        trace = list(getattr(gateway, "trace", []))
        return FormClassificationResult(
            profile=profile,
            profile_fingerprint=_profile_fingerprint(profile),
            confidence_threshold=confidence_threshold,
            predicted_segments=predicted,
            segments=segments,
            warnings=warnings,
            usage=usage,
            trace=trace,
        )

    def extract_forms(
        self,
        parse_result: ParseResult,
        classification: FormClassificationResult,
        schemas_by_name: Mapping[str, dict[str, Any]],
    ) -> RoutedExtractionResult:
        _validate_effective_segments(classification, parse_result)
        pages = {page.number: page for page in parse_result.document.pages}
        source_elements = parse_result.elements or build_elements(parse_result.document)
        forms: list[SegmentExtraction] = []
        usage = classification.usage.model_copy(deep=True)
        trace = list(classification.trace)

        for segment in classification.segments:
            if not segment.eligible or not segment.schema_name:
                continue
            schema = schemas_by_name.get(segment.schema_name)
            if schema is None:
                raise ValueError(
                    f"missing extraction schema {segment.schema_name!r} for {segment.category}"
                )
            document = Document(
                source_name=parse_result.document.source_name,
                source_sha256=parse_result.document.source_sha256,
                pages=[
                    pages[number].model_copy(deep=True)
                    for number in range(segment.start_page, segment.end_page + 1)
                ],
            )
            rendered = render_agentic_document(document)
            subset = ParseResult(
                document=document,
                markdown=rendered.markdown,
                base_markdown=rendered.markdown,
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=b"",
                elements=[
                    element.model_copy(deep=True)
                    for element in source_elements
                    if segment.start_page <= element.page <= segment.end_page
                ],
            )
            try:
                extracted = self.extract(subset, schema)
            except Exception as exc:  # noqa: BLE001 - batch failures remain isolated
                forms.append(
                    SegmentExtraction(
                        segment_id=segment.id,
                        category=segment.category,
                        start_page=segment.start_page,
                        end_page=segment.end_page,
                        schema_name=segment.schema_name,
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            usage.calls.extend(extracted.usage.calls)
            trace.extend(extracted.trace)
            forms.append(
                SegmentExtraction(
                    segment_id=segment.id,
                    category=segment.category,
                    start_page=segment.start_page,
                    end_page=segment.end_page,
                    schema_name=segment.schema_name,
                    status="succeeded",
                    extraction=extracted,
                )
            )

        payload = {
            "schema_version": "2.0.0",
            "custom_classification": classification.model_dump(mode="json"),
            "forms": [_segment_extraction_payload(item) for item in forms],
            "metadata": {
                "usage": usage.model_dump(mode="json"),
                "trace": [item.model_dump(mode="json") for item in trace],
            },
        }
        return RoutedExtractionResult(
            classification=classification,
            forms=forms,
            json=json.dumps(payload, ensure_ascii=False, indent=2),
            usage=usage,
            trace=trace,
        )

    def extract(
        self,
        parse_result: ParseResult,
        schema: dict[str, Any],
        *,
        prepared_context: PreparedDocumentContext | None = None,
    ) -> ExtractionResult:
        prepared = prepared_context or self.prepare(parse_result)
        contexts = prepared.contexts
        scalar_schema = all(
            not isinstance(field.get("properties"), dict) and "items" not in field
            for field in schema.get("properties", {}).values()
        )
        if len(contexts) == 1 or not scalar_schema:
            extractor = DocumentExtractor(
                self.config,
                gateway_factory=self.gateway_factory,
            )
            return extractor.extract(parse_result, schema, allow_inferred=True)

        pages = {page.number: page for page in parse_result.document.pages}

        def extract_context(context: AgenticContext) -> ExtractionResult:
            document = Document(
                source_name=parse_result.document.source_name,
                source_sha256=parse_result.document.source_sha256,
                pages=[pages[number].model_copy(deep=True) for number in context.page_numbers],
            )
            rendered = render_agentic_document(document)
            subset = ParseResult(
                document=document,
                markdown=context.markdown,
                base_markdown=rendered.markdown,
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=b"",
            )
            extractor = DocumentExtractor(
                self.config,
                gateway_factory=self.gateway_factory,
            )
            return extractor.extract(subset, schema, allow_inferred=True)

        with ThreadPoolExecutor(
            max_workers=min(self.config.provider_concurrency, len(contexts)),
            thread_name_prefix="docparse-extraction",
        ) as executor:
            results = list(executor.map(extract_context, contexts))

        rank = {"not_found": 0, "inferred": 1, "medium": 2, "high": 3}
        fields: dict[str, ExtractedField] = {}
        warnings = [warning for result in results for warning in result.warnings]
        conflicted_names: set[str] = set()
        for name in schema.get("properties", {}):
            candidates = [result.fields[name] for result in results if name in result.fields]
            candidates.sort(
                key=lambda field: (
                    rank[field.confidence],
                    -(field.page or 10**9),
                ),
                reverse=True,
            )
            chosen = candidates[0] if candidates else ExtractedField(
                value=None, confidence="not_found"
            )
            conflicting = {
                json.dumps(field.value, ensure_ascii=False, sort_keys=True)
                for field in candidates
                if field.value is not None
                and rank[field.confidence] == rank[chosen.confidence]
            }
            if len(conflicting) > 1:
                conflicted_names.add(name)
            fields[name] = chosen

        if conflicted_names:
            conflict_pages = {
                field.page
                for result in results
                for name, field in result.fields.items()
                if name in conflicted_names and field.value is not None and field.page
            }
            try:
                arbitration_document = Document(
                    source_name=parse_result.document.source_name,
                    source_sha256=parse_result.document.source_sha256,
                    pages=[
                        page.model_copy(deep=True)
                        for page in parse_result.document.pages
                        if page.number in conflict_pages
                    ],
                )
                rendered = render_agentic_document(arbitration_document)
                arbitration_result = DocumentExtractor(
                    self.config,
                    gateway_factory=self.gateway_factory,
                ).extract(
                    ParseResult(
                        document=arbitration_document,
                        markdown=rendered.markdown,
                        base_markdown=rendered.markdown,
                        json=rendered.json,
                        input_tokens=0,
                        output_tokens=0,
                        annotated_pdf=b"",
                    ),
                    schema,
                    allow_inferred=True,
                )
                results.append(arbitration_result)
                for name in conflicted_names:
                    candidate = arbitration_result.fields.get(name)
                    if candidate is not None and candidate.value is not None:
                        fields[name] = candidate
            except Exception as exc:  # noqa: BLE001 - deterministic merge remains valid
                warnings.append(
                    "Conflicting extraction arbitration failed; selected earliest "
                    f"highest-confidence evidence: {type(exc).__name__}: {exc}"
                )

        data = {name: field.value for name, field in fields.items()}
        evidence = {}
        for name, field in fields.items():
            if field.element_id and field.page:
                escaped = name.replace("~", "~0").replace("/", "~1")
                evidence[f"/{escaped}"] = [
                    {
                        "block_id": field.element_id,
                        "atom_id": None,
                        "page": field.page,
                        "span": None,
                        "bbox": (
                            {
                                "x0": field.bbox[0],
                                "y0": field.bbox[1],
                                "x1": field.bbox[2],
                                "y1": field.bbox[3],
                            }
                            if field.bbox
                            else None
                        ),
                        "confidence": field.confidence,
                    }
                ]
        usage = RunUsage()
        trace = []
        for result in results:
            usage.calls.extend(result.usage.calls)
            trace.extend(result.trace)
        payload = {
            "schema_version": "1.1.0",
            "schema": schema,
            "data": data,
            "evidence": evidence,
            "fields": {
                name: field.model_dump(mode="json") for name, field in fields.items()
            },
            "warnings": warnings,
            "metadata": {
                "usage": usage.model_dump(mode="json"),
                "trace": [item.model_dump(mode="json") for item in trace],
            },
        }
        return ExtractionResult(
            data=data,
            evidence=evidence,
            json=json.dumps(payload, ensure_ascii=False, indent=2),
            warnings=warnings,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            usage=usage,
            trace=trace,
            fields=fields,
        )

    def chat(
        self,
        parse_result: ParseResult,
        question: str,
        history: list[dict[str, str]],
        *,
        prepared_context: PreparedDocumentContext | None = None,
    ) -> ChatAnswer:
        question = question.strip()
        if not question:
            raise ValueError("question is required")
        prepared = prepared_context or self.prepare(parse_result)
        elements = list(prepared.elements)
        contexts = prepared.contexts
        combined_size = sum(
            len(item.markdown) + len(json.dumps(item.layout, ensure_ascii=False))
            for item in contexts
        )
        if combined_size <= MAX_CONTEXT_CHARACTERS:
            markdown = "\n\n<!-- PAGE BREAK -->\n\n".join(item.markdown for item in contexts)
            layout = [record for item in contexts for record in item.layout]
        else:
            terms = set(re.findall(r"[\w-]{2,}", question.casefold()))
            scored = []
            for index, element in enumerate(elements):
                text = element.text.casefold()
                overlap = sum(term in text for term in terms)
                score = overlap * 10 + SequenceMatcher(None, question.casefold(), text[:500]).ratio()
                if element.type in {"heading", "title"}:
                    score += 0.25
                scored.append((score, index, element))
            selected_indexes = set()
            for _score, index, _element in sorted(scored, reverse=True)[:40]:
                selected_indexes.update({index - 1, index, index + 1})
            selected = [
                element
                for index, element in enumerate(elements)
                if index in selected_indexes
            ]
            selected.sort(key=lambda item: (item.page, item.reading_order))
            layout = []
            parts = []
            size = 0
            for element in selected:
                record = {
                    "id": element.id,
                    "type": element.type,
                    "page": element.page,
                    "order": element.reading_order,
                    "text": element.text,
                }
                serialized = json.dumps(record, ensure_ascii=False)
                if size + len(serialized) + len(element.text) > MAX_CONTEXT_CHARACTERS:
                    break
                layout.append(record)
                parts.append(element.text)
                size += len(serialized) + len(element.text)
            markdown = "\n\n".join(parts)

        gateway = self.gateway_factory(self.config)
        wire = gateway.chat_document(
            question,
            markdown,
            layout,
            history[-MAX_CHAT_TURN_PAIRS * 2 :],
        )
        known = {element.id for element in elements}
        wire.citations = [item for item in wire.citations if item.element_id in known]
        by_id = {element.id: element for element in elements}
        sources = []
        for item in wire.citations:
            element = by_id[item.element_id]
            sources.append(
                ChatSource(
                    element_id=element.id,
                    page=element.page,
                    text=element.text,
                )
            )
        confidence = wire.confidence if sources else "low"
        usage = getattr(gateway, "usage", RunUsage()).model_copy(deep=True)
        trace = list(getattr(gateway, "trace", []))
        return ChatAnswer(
            answer=wire.answer,
            sources=sources,
            confidence=confidence,
            usage=usage,
            trace=trace,
        )
