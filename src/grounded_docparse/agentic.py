from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterable
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
    Document,
    DocumentClassification,
    Element,
    ExtractedField,
    ExtractionResult,
    NodeType,
    ParseResult,
    RunUsage,
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
    page_count: int,
) -> TableOfContents:
    flat = []
    for section in _flatten_sections(toc.sections):
        title = re.sub(r"^\s{0,3}#{1,6}[ \t]+", "", section.title).strip()
        if not title:
            raise ValueError("TOC title is empty after Markdown normalization")
        section = section.model_copy(update={"title": title})
        if section.page > page_count:
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
                    generated, elements, len(parse_result.document.pages)
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
                len(parse_result.document.pages),
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
                    features[name].warnings.append("Using grounded GLM heading fallback")
        return AgenticAnalysis(
            classification=classification,
            toc=toc,
            features=features,
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
