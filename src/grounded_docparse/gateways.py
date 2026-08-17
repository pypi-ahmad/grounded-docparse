from __future__ import annotations

import base64
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from openai import OpenAI, OpenAIError
from PIL import Image
from pydantic import BaseModel, ValidationError

from .config import ParserConfig
from .ingest import PageEvidence
from .models import (
    AgentRole,
    AgentTraceEvent,
    AgentUsage,
    ChatAnswerWire,
    CropInspectionRequest,
    DocumentClassification,
    FormSegmentationWire,
    MarkdownPresentationPlan,
    PageDraft,
    PageInspection,
    RunUsage,
    SchemaProposalWire,
    SpanRepairInspection,
    SpanRepairRequest,
    TableOfContents,
)
from .prompts import (
    CHAT_PROMPT,
    CLASSIFICATION_PROMPT,
    EXTRACTION_PROMPT,
    FORM_CLASSIFICATION_PROMPT,
    MARKDOWN_REFINEMENT_PROMPT,
    PROMPT_VERSION,
    SCHEMA_REPAIR_INSTRUCTION,
    TOC_PROMPT,
    secure_document_prompt,
)
from .runtime import ProviderRuntime

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)
_SCHEMA_FAILURE_MARKERS = (
    "schema",
    "validation",
    "no schema-valid result",
    "bounding box",
)


def _is_schema_failure(exc: Exception) -> bool:
    message = str(exc).casefold()
    return any(marker in message for marker in _SCHEMA_FAILURE_MARKERS)


class OpenAIDocumentGateway:
    def __init__(
        self,
        config: ParserConfig,
        client: Any | None = None,
        runtime: ProviderRuntime | None = None,
    ) -> None:
        if client is None and not os.getenv(config.cloud_model.api_key_name):
            raise RuntimeError(f"{config.cloud_model.api_key_name} is not set")
        self.config = config
        if client is None and config.cloud_model.value.startswith("gemini-"):
            from types import SimpleNamespace

            from google import genai

            from .gemini_gateway import _GeminiResponses

            client = SimpleNamespace(
                responses=_GeminiResponses(
                    genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
                )
            )
        if client is None and config.cloud_model.value == "agnes-2.5-flash":
            from types import SimpleNamespace

            from .agnes_gateway import AgnesResponses

            agnes = OpenAI(
                api_key=os.environ["AGNES_API_KEY"],
                base_url=os.getenv(
                    "AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1"
                ),
                max_retries=0,
            )
            client = SimpleNamespace(
                responses=AgnesResponses(agnes.chat.completions)
            )
        if client is None:
            client_options: dict[str, Any] = {"max_retries": 0}
            if os.getenv("OPENAI_BASE_URL"):
                client_options["base_url"] = os.environ["OPENAI_BASE_URL"]
            client = OpenAI(**client_options)
        self.client = client
        self.model = config.cloud_model.value
        self.reasoning_effort = config.cloud_model.reasoning_effort
        self.runtime = runtime or ProviderRuntime(config)
        self.input_tokens = 0
        self.output_tokens = 0
        self.usage = RunUsage()
        self.trace: list[AgentTraceEvent] = []

    def bind_runtime(self, runtime: ProviderRuntime) -> None:
        self.runtime = runtime

    def _provider_responses(self) -> Any:
        return self.client.responses

    def _provider_request(
        self,
        call: Callable[[], Any],
        *,
        stage: str,
        model: str,
        page_number: int | None,
        on_success: Callable[[Any], None] | None = None,
    ) -> Any:
        try:
            return self.runtime.request(
                call,
                model=model,
                stage=stage,
                page_number=page_number,
                on_success=on_success,
            )
        except OpenAIError as exc:
            exc.docparse_stage = stage
            exc.docparse_page_number = page_number
            exc.docparse_model = model
            raise

    @staticmethod
    def _image(path: Path) -> str:
        payload = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{payload}"

    def _record_usage(self, response: Any, *, agent: str, model: str) -> AgentUsage:
        usage = (
            response.get("usage")
            if isinstance(response, dict)
            else getattr(response, "usage", None)
        )
        if usage is None:
            call = AgentUsage(agent=agent, model=model, telemetry_available=False)
            self.usage.calls.append(call)
            return call
        get = (
            usage.get
            if isinstance(usage, dict)
            else lambda name, default: getattr(usage, name, default)
        )
        input_tokens = get("input_tokens", 0)
        output_tokens = get("output_tokens", 0)
        input_details = get("input_tokens_details", None)
        details_get = (
            input_details.get
            if isinstance(input_details, dict)
            else lambda name, default: getattr(input_details, name, default)
        )
        cached_input_tokens = details_get("cached_tokens", 0)
        valid_input_tokens = (
            input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else 0
        )
        valid_cached_input_tokens = (
            cached_input_tokens
            if isinstance(cached_input_tokens, int) and cached_input_tokens >= 0
            else 0
        )
        valid_cached_input_tokens = min(
            valid_cached_input_tokens, valid_input_tokens
        )
        if isinstance(input_tokens, int) and input_tokens >= 0:
            self.input_tokens += input_tokens
        if isinstance(output_tokens, int) and output_tokens >= 0:
            self.output_tokens += output_tokens
        call = AgentUsage(
            agent=agent,
            model=model,
            input_tokens=valid_input_tokens,
            cached_input_tokens=valid_cached_input_tokens,
            output_tokens=output_tokens
            if isinstance(output_tokens, int) and output_tokens >= 0
            else 0,
        )
        self.usage.calls.append(call)
        return call

    def _record_runtime_usage(
        self, response: Any, *, agent: str, model: str
    ) -> AgentUsage:
        usage = self._record_usage(response, agent=agent, model=model)
        self.runtime.record_usage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        return usage

    def _request(
        self,
        expected: type[T],
        *,
        agent: str,
        stage: str,
        page_number: int | None = None,
        target_ids: list[str] | None = None,
        image_paths: list[Path] | None = None,
        image_scope: str = "none",
        source_page_path: Path | None = None,
        source_page_pixels: int = 0,
        repair_round: int | None = None,
        prompt_version: str | None = None,
        **kwargs: Any,
    ) -> T:
        started = time.perf_counter()
        model = str(kwargs.get("model", "unknown"))
        reasoning = kwargs.get("reasoning")
        reasoning_effort = (
            str(reasoning.get("effort")) if isinstance(reasoning, dict) else None
        )
        responses = self.client.responses
        raw_api = getattr(responses, "with_raw_response", None)
        response: Any = None
        call_usage: AgentUsage | None = None

        def record_schema_failure(exc: Exception) -> None:
            if not _is_schema_failure(exc):
                return
            logger.warning(
                "Provider structured response rejected: model=%s stage=%s page=%s error=%s",
                model,
                stage,
                page_number,
                exc,
            )
            self.trace.append(
                AgentTraceEvent(
                    agent=agent,
                    model=model,
                    action=stage,
                    status="schema_invalid",
                    page=page_number,
                    target_ids=target_ids or [],
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    input_tokens=call_usage.input_tokens if call_usage else 0,
                    output_tokens=call_usage.output_tokens if call_usage else 0,
                    image_scope=image_scope,
                    image_count=len(image_paths or []),
                    source_page_pixels=source_page_pixels,
                    repair_round=repair_round,
                    prompt_version=prompt_version,
                    reasoning_effort=reasoning_effort,
                    summary=str(exc),
                )
            )

        try:
            if raw_api is None:

                def finalize_response(result: Any) -> None:
                    nonlocal call_usage
                    call_usage = self._record_runtime_usage(
                        result,
                        agent=agent,
                        model=model,
                    )

                response = self._provider_request(
                    lambda: self._provider_responses().parse(
                        text_format=expected,
                        **kwargs,
                    ),
                    stage=stage,
                    model=model,
                    page_number=page_number,
                    on_success=finalize_response,
                )
            else:

                def finalize_raw(raw: Any) -> None:
                    nonlocal response, call_usage
                    try:
                        response = raw.parse()
                    except ValidationError as exc:
                        try:
                            payload = json.loads(raw.content)
                        except (TypeError, ValueError):
                            payload = {}
                        call_usage = self._record_runtime_usage(
                            payload,
                            agent=agent,
                            model=model,
                        )
                        page = (
                            f" for page {page_number}"
                            if page_number is not None
                            else ""
                        )
                        request_id = getattr(raw, "request_id", None) or "unknown"
                        detail = exc.errors(include_url=False, include_input=False)[0]
                        location = (
                            ".".join(str(item) for item in detail.get("loc", ()))
                            or "response"
                        )
                        incomplete = payload.get("incomplete_details", {}).get("reason")
                        status = incomplete or payload.get("status", "invalid")
                        raise RuntimeError(
                            f"{stage}{page} using {kwargs.get('model')}: OpenAI response "
                            f"{status} failed schema validation at "
                            f"{location} ({detail.get('type', 'validation_error')}); "
                            f"request ID {request_id}"
                        ) from exc
                    call_usage = self._record_runtime_usage(
                        response,
                        agent=agent,
                        model=model,
                    )

                self._provider_request(
                    lambda: self._provider_responses().with_raw_response.parse(
                        text_format=expected,
                        **kwargs,
                    ),
                    stage=stage,
                    model=model,
                    page_number=page_number,
                    on_success=finalize_raw,
                )
        except (RuntimeError, ValidationError) as exc:
            record_schema_failure(exc)
            raise
        if call_usage is None:
            raise AssertionError("provider usage finalizer did not run")
        paths = image_paths or []
        image_pixels = 0
        for path in paths:
            try:
                with Image.open(path) as image:
                    image_pixels += image.width * image.height
            except (FileNotFoundError, OSError):
                continue
        if source_page_path is not None:
            try:
                with Image.open(source_page_path) as image:
                    source_page_pixels = image.width * image.height
            except (FileNotFoundError, OSError):
                pass
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, expected):
            for output in getattr(response, "output", []):
                for content in getattr(output, "content", []):
                    if getattr(content, "type", None) == "refusal":
                        raise RuntimeError(
                            f"OpenAI refused extraction: {content.refusal}"
                        )
                    candidate = getattr(content, "parsed", None)
                    if isinstance(candidate, expected):
                        parsed = candidate
                        break
                if isinstance(parsed, expected):
                    break
        if not isinstance(parsed, expected):
            exc = RuntimeError(f"{stage}: OpenAI returned no schema-valid result")
            record_schema_failure(exc)
            raise exc
        self.trace.append(
            AgentTraceEvent(
                agent=agent,
                model=model,
                action=stage,
                status="completed",
                page=page_number,
                target_ids=target_ids or [],
                duration_ms=round((time.perf_counter() - started) * 1000),
                input_tokens=call_usage.input_tokens,
                output_tokens=call_usage.output_tokens,
                image_scope=image_scope,
                image_count=len(paths),
                image_pixels=image_pixels,
                source_page_pixels=source_page_pixels,
                repair_round=repair_round,
                prompt_version=prompt_version,
                reasoning_effort=reasoning_effort,
            )
        )
        return parsed

    def _structured_document_request(
        self,
        expected: type[T],
        *,
        agent: str,
        stage: str,
        system_prompt: str,
        payload: dict[str, Any],
        max_output_tokens: int,
    ) -> T:
        for attempt in range(2):
            prompt = secure_document_prompt(system_prompt)
            if attempt:
                prompt = f"{prompt}\n\n{SCHEMA_REPAIR_INSTRUCTION}"
            try:
                return self._request(
                    expected,
                    agent=agent,
                    stage=stage,
                    model=self.model,
                    reasoning={"effort": self.reasoning_effort},
                    store=False,
                    prompt_version=PROMPT_VERSION,
                    input=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    max_output_tokens=max_output_tokens,
                )
            except (RuntimeError, ValidationError) as exc:
                if attempt or not _is_schema_failure(exc):
                    raise
        raise AssertionError("structured response retry did not return")

    def draft_page(self, page: PageEvidence) -> PageDraft:
        return self._request(
            PageDraft,
            agent="draft_parser",
            stage="page_draft",
            page_number=page.number,
            image_paths=[page.image_path],
            image_scope="full_page",
            source_page_path=page.image_path,
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": secure_document_prompt(
                        "Extract every visible element in semantic reading order. Include complete "
                        "paragraphs; ordered and unordered lists with their literal markers; forms "
                        "and field values; tables and cells; checkboxes; headings; headers; footers; "
                        "signatures; seals; figures; charts; formulas; images; and captions. Preserve "
                        "literal visible text without summarizing or omitting content. Join visual line wraps "
                        "Populate atoms with one normalized bounding box per visible text line, table cell, "
                        "or visual region so every literal can be grounded below the block level. "
                        "For an atom or table cell with uncertain glyphs, emit low_confidence_spans using "
                        "exact Unicode-codepoint start/end offsets and the uncertain substring, calibrated "
                        "confidence, and optional normalized bounding box. Do not emit a span for text that "
                        "is merely important or visually clear. "
                        "inside prose, but preserve wording, punctuation, identifiers, and real hyphens. "
                        "Do not correct spelling or infer obscured text. Emit one region per visible form field; "
                        "never combine a form section into one field. Populate form.label and form.value "
                        "explicitly, and put faint printed examples, templates, units, and instructions in "
                        "form.hint rather than treating them as entered values. Emit one region per checkbox. "
                        "Form labels are not headings. Classify text as a heading only when it is "
                        "typographically distinct from surrounding labels and body text. "
                        "and populate checkbox_group with the shared "
                        "prompt and checkbox_option with that box's option. Give substantive "
                        "and decorative visuals concise grounded descriptions that use exact visible terminology "
                        "from nearby labels instead of generic synonyms. Emit each visual immediately beside "
                        "its related procedure in reading order; never collect figures at the end of the page. "
                        "Emit each list option once, without repeating its label. Use normalized page "
                        "coordinates."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": self._image(page.image_path),
                            "detail": "original",
                        },
                    ],
                },
            ],
            max_output_tokens=self.config.luna_max_output_tokens,
        )

    def inspect_crops(
        self,
        crops: list[CropInspectionRequest],
        *,
        page_number: int | None = None,
        agent_role: AgentRole = AgentRole.EVIDENCE_CRITIC,
        stage: str = "crop_batch_inspection",
        repair_round: int | None = None,
    ) -> PageInspection:
        manifest = [
            {
                "region_id": crop.region_id,
                "candidate_region": crop.candidate_region.model_dump(mode="json"),
                "evidence_ref": crop.evidence_ref,
                "image_index": index,
            }
            for index, crop in enumerate(crops)
        ]
        content: list[dict[str, str]] = [
            {"type": "input_text", "text": json.dumps(manifest, ensure_ascii=False)}
        ]
        content.extend(
            {
                "type": "input_image",
                "image_url": self._image(Path(crop.crop_path)),
                "detail": "original",
            }
            for crop in crops
        )
        return self._request(
            PageInspection,
            agent=agent_role.value,
            stage=stage,
            page_number=page_number,
            target_ids=[crop.region_id for crop in crops],
            image_paths=[Path(crop.crop_path) for crop in crops],
            image_scope="crop_batch",
            source_page_pixels=crops[0].source_page_pixels if crops else 0,
            repair_round=repair_round,
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": secure_document_prompt(
                        f"Act as the {agent_role.value}. Verify each candidate against its "
                        "corresponding source crop. Accept, return a high-confidence text-only "
                        "correction, or mark the crop inconclusive. "
                        "Read ambiguous glyphs in emails, URLs, identifiers, and placeholders exactly. "
                        "For critical literals—phone numbers, NPIs, MRNs, dates, IDs, DOBs, tax IDs, "
                        "policy numbers, and account numbers—preserve exact glyphs, punctuation, "
                        "separators, and leading zeros. Do not infer unclear digits; return illegible "
                        "or inconclusive when exact reading is impossible. "
                        "For every visual, return a complete figure_description covering visible objects, "
                        "actions, spatial relationships, arrows, labels, callouts, numbered markers, "
                        "prohibition marks, and functional features. Correct an incomplete visual description "
                        "even when its existing summary is broadly accurate. For a barcode, describe its "
                        "orientation and associated visible labels or identifiers, but do not infer or claim "
                        "to decode its encoded value. "
                        "Do not repeat literal text already captured in the candidate or nearby blocks. "
                        "Keep non-instructional visual descriptions under 25 words and instructional "
                        "figures under 75 words. "
                        "A corrected_region must preserve the supplied ID and may change only textual "
                        "fields. Geometry, type, reading order, confidence, and structural fields are "
                        "owned by GLM-OCR and ignored. Set confidence to at least 0.85 only when every "
                        "corrected glyph is clearly visible. "
                        "For tables containing form controls, inspect every visible checkbox. In "
                        "corrected_region.table_cells, prefix every existing option with [x] or [ ] "
                        "and use the same row_index and column_index as the candidate cell. If multiple "
                        "controls share one cell, preserve every marker and label in that cell. Never "
                        "infer an unclear state; mark the crop inconclusive instead. "
                        "For rejections, set geometry_only=true only when rejection is exclusively caused "
                        "by invalid, missing, or clipped bounding-box geometry; set it false for semantic, "
                        "unsupported, ambiguous, or mixed failures. "
                        "Return one decision per crop and "
                        "preserve every supplied region ID and evidence reference."
                    ),
                },
                {
                    "role": "user",
                    "content": content,
                },
            ],
            max_output_tokens=min(16_000, self.config.luna_max_output_tokens),
        )

    def inspect_quality_crops(
        self,
        crops: list[CropInspectionRequest],
        *,
        page_number: int,
    ) -> PageInspection:
        manifest = [
            {
                "region_id": crop.region_id,
                "candidate_region": crop.candidate_region.model_dump(mode="json"),
                "evidence_ref": crop.evidence_ref,
                "image_index": index,
            }
            for index, crop in enumerate(crops)
        ]
        content: list[dict[str, str]] = [
            {"type": "input_text", "text": json.dumps(manifest, ensure_ascii=False)}
        ]
        content.extend(
            {
                "type": "input_image",
                "image_url": self._image(Path(crop.crop_path)),
                "detail": "original",
            }
            for crop in crops
        )
        return self._request(
            PageInspection,
            agent=AgentRole.EVIDENCE_CRITIC.value,
            stage="quality_crop_inspection",
            page_number=page_number,
            target_ids=[crop.region_id for crop in crops],
            image_paths=[Path(crop.crop_path) for crop in crops],
            image_scope="crop_batch",
            source_page_pixels=crops[0].source_page_pixels if crops else 0,
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": secure_document_prompt(
                        "Verify each candidate against its corresponding high-resolution source crop. "
                        "Return exactly one accept, high-confidence text-only correction, or inconclusive "
                        "decision per crop. "
                        "Never invent obscured or unsupported content. Preserve exact visible identifiers, "
                        "dates, measurements, phone numbers, emails, URLs, list markers, table cells, and "
                        "checkbox states. For critical literals—phone numbers, NPIs, MRNs, dates, IDs, "
                        "DOBs, tax IDs, policy numbers, and account numbers—preserve exact glyphs, "
                        "punctuation, separators, and leading zeros. Do not infer unclear digits; return "
                        "illegible or inconclusive when exact reading is impossible. For rejections, set "
                        "geometry_only=true only when rejection is "
                        "exclusively caused by invalid, missing, or clipped bounding-box geometry; set it "
                        "false for semantic, unsupported, ambiguous, or mixed failures. A corrected_region "
                        "may change only textual fields and must preserve the supplied ID. Geometry, type, "
                        "reading order, confidence, and structural fields are owned by GLM-OCR and ignored. "
                        "Set confidence to at least 0.85 only when every corrected glyph is clearly visible."
                    ),
                },
                {"role": "user", "content": content},
            ],
            max_output_tokens=min(16_000, self.config.luna_max_output_tokens),
        )

    def repair_spans(
        self,
        requests: list[SpanRepairRequest],
        *,
        page_number: int,
    ) -> SpanRepairInspection:
        manifest: list[dict[str, object]] = []
        image_paths: list[Path] = []
        for request in requests:
            image_index = len(image_paths)
            image_paths.append(Path(request.crop_path))
            item: dict[str, object] = {
                **request.target.model_dump(mode="json"),
                "image_index": image_index,
            }
            manifest.append(item)
        content: list[dict[str, str]] = [
            {"type": "input_text", "text": json.dumps(manifest, ensure_ascii=False)}
        ]
        content.extend(
            {
                "type": "input_image",
                "image_url": self._image(path),
                "detail": "original",
            }
            for path in image_paths
        )
        return self._request(
            SpanRepairInspection,
            agent=AgentRole.EVIDENCE_CRITIC.value,
            stage="targeted_span_repair",
            page_number=page_number,
            target_ids=[request.target.target_id for request in requests],
            image_paths=image_paths,
            image_scope="crop_batch",
            source_page_pixels=requests[0].source_page_pixels if requests else 0,
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": secure_document_prompt(
                        "Resolve only each supplied uncertain literal against its matching crop. "
                        "When context_image_index is present, use that second image only to locate "
                        "and disambiguate the literal; the tight crop remains the repair target. "
                        "Confirm it when exact, replace only that literal when the crop is conclusive, "
                        "or return unresolved. Never rewrite context, adjacent text, layout, structure, "
                        "or any text outside start:end. Preserve target_id and evidence_ref. Do not "
                        "infer obscured glyphs."
                    ),
                },
                {"role": "user", "content": content},
            ],
            max_output_tokens=min(8_000, self.config.luna_max_output_tokens),
        )

    def refine_markdown(
        self,
        anchored_markdown: str,
        layout: list[dict[str, Any]],
    ) -> MarkdownPresentationPlan:
        """Return presentation-only instructions; document text is never accepted."""

        return self._structured_document_request(
            MarkdownPresentationPlan,
            agent="markdown_refiner",
            stage="markdown_refinement",
            system_prompt=MARKDOWN_REFINEMENT_PROMPT,
            payload={"anchored_markdown": anchored_markdown, "layout_tree": layout},
            max_output_tokens=min(16_000, self.config.luna_max_output_tokens),
        )

    def classify_document(
        self,
        markdown: str,
        layout: list[dict[str, Any]],
    ) -> DocumentClassification:
        return self._structured_document_request(
            DocumentClassification,
            agent="document_classifier",
            stage="document_classification",
            system_prompt=CLASSIFICATION_PROMPT,
            payload={"document_markdown": markdown, "layout_tree": layout},
            max_output_tokens=min(2_000, self.config.luna_max_output_tokens),
        )

    def classify_forms(
        self,
        markdown: str,
        layout: list[dict[str, Any]],
        profile: dict[str, Any],
        *,
        issues: list[str] | None = None,
    ) -> FormSegmentationWire:
        payload = {
            "routing_profile": profile,
            "document_markdown": markdown,
            "layout_tree": layout,
        }
        if issues:
            payload["validation_issues"] = issues
        return self._structured_document_request(
            FormSegmentationWire,
            agent="custom_form_classifier",
            stage="custom_form_classification",
            system_prompt=FORM_CLASSIFICATION_PROMPT,
            payload=payload,
            max_output_tokens=min(8_000, self.config.luna_max_output_tokens),
        )

    def generate_toc(
        self,
        markdown: str,
        layout: list[dict[str, Any]],
    ) -> TableOfContents:
        return self._structured_document_request(
            TableOfContents,
            agent="toc_generator",
            stage="toc_generation",
            system_prompt=TOC_PROMPT,
            payload={"document_markdown": markdown, "layout_tree": layout},
            max_output_tokens=min(8_000, self.config.luna_max_output_tokens),
        )

    def chat_document(
        self,
        question: str,
        markdown: str,
        layout: list[dict[str, Any]],
        history: list[dict[str, str]],
    ) -> ChatAnswerWire:
        return self._structured_document_request(
            ChatAnswerWire,
            agent="document_chat",
            stage="document_chat",
            system_prompt=CHAT_PROMPT,
            payload={
                "document_markdown": markdown,
                "layout_tree": layout,
                "chat_history": history,
                "question": question,
            },
            max_output_tokens=min(4_000, self.config.luna_max_output_tokens),
        )

    def propose_schema(
        self,
        instruction: str,
        parse_payload: dict[str, Any],
    ) -> SchemaProposalWire:
        markdown = str(parse_payload.get("markdown", ""))
        return self._request(
            SchemaProposalWire,
            agent="schema_architect",
            stage="schema_proposal",
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": secure_document_prompt(
                        "Convert the user's extraction request into strict JSON Schema. "
                        "Return the schema as schema_text. The root must be an object, every "
                        "object must set additionalProperties to false and require every property, "
                        "and every field below the root must accept null so absent document values "
                        "can be represented without invention. Use only object, array, string, "
                        "number, integer, boolean, null, enum, properties, required, items, and "
                        "description."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instruction": instruction,
                            "document_excerpt": markdown[:50_000],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=min(8_000, self.config.luna_max_output_tokens),
        )

    def extract_document(
        self,
        parse_payload: dict[str, Any],
        schema: dict[str, Any],
        *,
        repair: bool = False,
        issues: list[str] | None = None,
    ) -> dict[str, Any]:
        evidence_item = {
            "type": "object",
            "properties": {
                "pointer": {"type": "string"},
                "block_ids": {"type": "array", "items": {"type": "string"}},
                "atom_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["pointer", "block_ids", "atom_ids"],
            "additionalProperties": False,
        }
        envelope = {
            "type": "object",
            "properties": {
                "data": schema,
                "evidence": {"type": "array", "items": evidence_item},
            },
            "required": ["data", "evidence"],
            "additionalProperties": False,
        }
        agent = "extraction_critic" if repair else "extractor"
        model = self.model
        for format_attempt in range(2):
            started = time.perf_counter()
            call_usage: AgentUsage | None = None

            def finalize_response(result: Any) -> None:
                nonlocal call_usage
                call_usage = self._record_runtime_usage(
                    result,
                    agent=agent,
                    model=model,
                )

            system_prompt = secure_document_prompt(EXTRACTION_PROMPT)
            if format_attempt:
                system_prompt = f"{system_prompt}\n\n{SCHEMA_REPAIR_INSTRUCTION}"
            response = self._provider_request(
                lambda prompt=system_prompt: self._provider_responses().create(
                    model=model,
                    reasoning={"effort": self.reasoning_effort},
                    store=False,
                    input=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "document": parse_payload,
                                    "repair_issues": issues or [],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "grounded_extraction",
                            "strict": True,
                            "schema": envelope,
                        }
                    },
                    max_output_tokens=self.config.luna_max_output_tokens,
                ),
                stage="extract_document",
                model=model,
                page_number=None,
                on_success=finalize_response,
            )
            if call_usage is None:
                raise AssertionError("provider usage finalizer did not run")
            output_text = getattr(response, "output_text", None)
            try:
                if not isinstance(output_text, str):
                    raise TypeError("no JSON output")
                payload = json.loads(output_text)
                if not isinstance(payload, dict):
                    raise TypeError("non-object result")
            except (json.JSONDecodeError, TypeError) as exc:
                self.trace.append(
                    AgentTraceEvent(
                        agent=agent,
                        model=model,
                        action="extract_document",
                        status="schema_invalid",
                        duration_ms=round((time.perf_counter() - started) * 1000),
                        input_tokens=call_usage.input_tokens,
                        output_tokens=call_usage.output_tokens,
                        prompt_version=PROMPT_VERSION,
                        reasoning_effort=self.reasoning_effort,
                        summary=str(exc),
                    )
                )
                if format_attempt:
                    raise RuntimeError(
                        "extract_document: OpenAI returned invalid JSON twice"
                    ) from exc
                continue
            self.trace.append(
                AgentTraceEvent(
                    agent=agent,
                    model=model,
                    action="extract_document",
                    status="completed",
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    input_tokens=call_usage.input_tokens,
                    output_tokens=call_usage.output_tokens,
                    prompt_version=PROMPT_VERSION,
                    reasoning_effort=self.reasoning_effort,
                )
            )
            return payload
        raise AssertionError("extraction response retry did not return")
