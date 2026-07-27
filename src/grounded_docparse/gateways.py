from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from .config import ParserConfig
from .ingest import PageEvidence
from .models import (
    AgentRole,
    AgentTraceEvent,
    AgentUsage,
    CropInspectionRequest,
    PageDraft,
    PageInspection,
    PagePlan,
    RunUsage,
    SchemaProposalWire,
)

T = TypeVar("T", bound=BaseModel)


class OpenAIDocumentGateway:
    def __init__(self, config: ParserConfig, client: Any | None = None) -> None:
        if client is None and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.config = config
        self.client = client or OpenAI()
        self.input_tokens = 0
        self.output_tokens = 0
        self.usage = RunUsage()
        self.trace: list[AgentTraceEvent] = []

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
            call = AgentUsage(agent=agent, model=model)
            self.usage.calls.append(call)
            return call
        get = usage.get if isinstance(usage, dict) else lambda name, default: getattr(usage, name, default)
        input_tokens = get("input_tokens", 0)
        output_tokens = get("output_tokens", 0)
        if isinstance(input_tokens, int) and input_tokens >= 0:
            self.input_tokens += input_tokens
        if isinstance(output_tokens, int) and output_tokens >= 0:
            self.output_tokens += output_tokens
        call = AgentUsage(
            agent=agent,
            model=model,
            input_tokens=input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else 0,
            output_tokens=output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else 0,
        )
        self.usage.calls.append(call)
        return call

    def _request(
        self,
        expected: type[T],
        *,
        agent: str,
        stage: str,
        page_number: int | None = None,
        target_ids: list[str] | None = None,
        **kwargs: Any,
    ) -> T:
        started = time.perf_counter()
        model = str(kwargs.get("model", "unknown"))
        responses = self.client.responses
        raw_api = getattr(responses, "with_raw_response", None)
        if raw_api is None:
            response = responses.parse(text_format=expected, **kwargs)
            call_usage = self._record_usage(response, agent=agent, model=model)
        else:
            try:
                raw = raw_api.parse(text_format=expected, **kwargs)
            except OpenAIError as exc:
                exc.docparse_stage = stage
                exc.docparse_page_number = page_number
                exc.docparse_model = kwargs.get("model")
                raise
            try:
                response = raw.parse()
            except ValidationError as exc:
                try:
                    payload = json.loads(raw.content)
                except (TypeError, ValueError):
                    payload = {}
                self._record_usage(payload, agent=agent, model=model)
                page = f" for page {page_number}" if page_number is not None else ""
                request_id = getattr(raw, "request_id", None) or "unknown"
                detail = exc.errors(include_url=False, include_input=False)[0]
                location = ".".join(str(item) for item in detail.get("loc", ())) or "response"
                incomplete = payload.get("incomplete_details", {}).get("reason")
                status = incomplete or payload.get("status", "invalid")
                raise RuntimeError(
                    f"{stage}{page} using {kwargs.get('model')}: OpenAI response "
                    f"{status} failed schema validation at "
                    f"{location} ({detail.get('type', 'validation_error')}); "
                    f"request ID {request_id}"
                ) from exc
            call_usage = self._record_usage(response, agent=agent, model=model)
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
            )
        )
        parsed = getattr(response, "output_parsed", None)
        if isinstance(parsed, expected):
            return parsed
        for output in getattr(response, "output", []):
            for content in getattr(output, "content", []):
                if getattr(content, "type", None) == "refusal":
                    raise RuntimeError(f"OpenAI refused extraction: {content.refusal}")
                parsed = getattr(content, "parsed", None)
                if isinstance(parsed, expected):
                    return parsed
        raise RuntimeError(f"{stage}: OpenAI returned no schema-valid result")

    def draft_page(self, page: PageEvidence) -> PageDraft:
        return self._request(
            PageDraft,
            agent="draft_parser",
            stage="page_draft",
            page_number=page.number,
            model=self.config.luna_model,
            reasoning={"effort": "medium"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Extract every visible element in semantic reading order. Include complete "
                        "paragraphs; ordered and unordered lists with their literal markers; forms "
                        "and field values; tables and cells; checkboxes; headings; headers; footers; "
                        "signatures; seals; figures; charts; formulas; images; and captions. Preserve "
                        "literal visible text without summarizing or omitting content. Join visual line wraps "
                        "Populate atoms with one normalized bounding box per visible text line, table cell, "
                        "or visual region so every literal can be grounded below the block level. "
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
                        {"type": "input_text", "text": page.digital_text[:200_000] or "No embedded text."},
                        {"type": "input_image", "image_url": self._image(page.image_path), "detail": "original"},
                    ],
                },
            ],
            max_output_tokens=self.config.luna_max_output_tokens,
        )

    def inspect_page(
        self,
        page: PageEvidence,
        draft: PageDraft,
        *,
        region_ids: list[str],
        target_region_ids: list[str] | None = None,
        agent_role: AgentRole = AgentRole.EVIDENCE_CRITIC,
        use_terra: bool = False,
    ) -> PageInspection:
        if len(region_ids) != len(draft.regions):
            raise ValueError("region IDs must match the complete page manifest")
        targets = target_region_ids or region_ids
        regions = [
            {"region_id": region_ids[index], **region.model_dump(mode="json")}
            for index, region in enumerate(draft.regions)
        ]
        return self._request(
            PageInspection,
            agent=agent_role.value,
            stage="page_inspection",
            page_number=page.number,
            target_ids=targets,
            model=self.config.terra_model if use_terra else self.config.luna_model,
            reasoning={"effort": "medium"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Compare every proposed block with the source image. Accept literal matches, "
                        f"Act as the {agent_role.value}. "
                        "reject unsupported content, or request a crop when genuinely ambiguous. When "
                        "anything is wrong, return a complete corrected region including type, text, "
                        "bounding box, reading order, marker, form or checkbox structure, table cells, "
                        "and visual description as applicable. Correct visual descriptions that replace exact "
                        "visible terminology with generic synonyms. Do not accept a figure description that "
                        "omits an annotated label, functional feature, or the nearby heading or label that "
                        "identifies its subject; correct it or request a crop. "
                        "Distinguish entered form values from printed hints and placeholders. Corrections must "
                        "be literally visible. Inspect the complete manifest for any omitted visible region and "
                        "return each omission in additional_regions with a temporary unique region ID and a "
                        "precise normalized bounding box. Return ordered_region_ids as a complete permutation "
                        "of all supplied and added region IDs in semantic reading order; place each visual beside "
                        "its related instruction rather than at the page end. Return decisions only for the "
                        "target_region_ids. Preserve every supplied region ID."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "regions": regions,
                                    "target_region_ids": targets,
                                },
                                ensure_ascii=False,
                            ),
                        },
                        {"type": "input_image", "image_url": self._image(page.image_path), "detail": "original"},
                    ],
                },
            ],
            max_output_tokens=self.config.terra_max_output_tokens,
        )

    def inspect_crops(
        self,
        crops: list[CropInspectionRequest],
        *,
        use_terra: bool = False,
        page_number: int | None = None,
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
            agent=AgentRole.VISUAL.value,
            stage="crop_batch_inspection",
            page_number=page_number,
            target_ids=[crop.region_id for crop in crops],
            model=self.config.terra_model if use_terra else self.config.luna_model,
            reasoning={"effort": "medium"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Verify each candidate against its corresponding source crop. Accept, "
                        "visibly correct by returning a complete corrected region, or reject each one. "
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
                        "A crop correction must not change the candidate bounding box or reading order. "
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
            max_output_tokens=min(16_000, self.config.terra_max_output_tokens),
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
            model=self.config.terra_model,
            reasoning={"effort": "medium"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Verify each candidate against its corresponding high-resolution source crop. "
                        "Return exactly one accept, complete literal correction, or rejection per crop. "
                        "Never invent obscured or unsupported content. Preserve exact visible identifiers, "
                        "dates, measurements, phone numbers, emails, URLs, list markers, table cells, and "
                        "checkbox states. For critical literals—phone numbers, NPIs, MRNs, dates, IDs, "
                        "DOBs, tax IDs, policy numbers, and account numbers—preserve exact glyphs, "
                        "punctuation, separators, and leading zeros. Do not infer unclear digits; return "
                        "illegible or inconclusive when exact reading is impossible. For rejections, set "
                        "geometry_only=true only when rejection is "
                        "exclusively caused by invalid, missing, or clipped bounding-box geometry; set it "
                        "false for semantic, unsupported, ambiguous, or mixed failures. Preserve every "
                        "supplied region ID, evidence reference, bounding "
                        "box, and reading order."
                    ),
                },
                {"role": "user", "content": content},
            ],
            max_output_tokens=min(16_000, self.config.terra_max_output_tokens),
        )

    def plan_page(
        self,
        page: PageEvidence,
        draft: PageDraft,
        *,
        region_ids: list[str],
        target_region_ids: list[str],
        repair_round: int,
        prior_inspections: list[dict[str, Any]] | None = None,
    ) -> PagePlan:
        if repair_round not in {1, 2}:
            raise ValueError("repair_round must be 1 or 2")
        if len(region_ids) != len(draft.regions):
            raise ValueError("region IDs must match the complete page manifest")
        manifest = [
            {"region_id": region_ids[index], **region.model_dump(mode="json")}
            for index, region in enumerate(draft.regions)
        ]
        return self._request(
            PagePlan,
            agent="document_manager",
            stage="page_plan",
            page_number=page.number,
            model=self.config.luna_model,
            reasoning={"effort": "medium"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are the document manager. Decide which bounded specialist subagents "
                        "must inspect the target regions: layout_text_specialist, "
                        "table_form_specialist, visual_specialist, or evidence_critic. "
                        "Delegate only work needed to establish literal fidelity, complete coverage, "
                        "reading order, and grounding. Use Terra only when a Luna review could not "
                        "resolve complex or critical evidence. Return at most two delegations. "
                        "Set finish when the page can be finalized after these delegations."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "repair_round": repair_round,
                            "target_region_ids": target_region_ids,
                            "regions": manifest,
                            "prior_inspections": prior_inspections or [],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_output_tokens=min(8_000, self.config.luna_max_output_tokens),
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
            model=self.config.luna_model,
            reasoning={"effort": "medium"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
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
        use_terra: bool,
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
        agent = "extraction_critic" if use_terra else "extractor"
        model = self.config.terra_model if use_terra else self.config.luna_model
        started = time.perf_counter()
        response = self.client.responses.create(
            model=model,
            reasoning={"effort": "medium"},
            store=False,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Extract only values supported by the grounded document. Return null when "
                        "a value is absent or ambiguous. For every non-null scalar, include evidence "
                        "at its RFC 6901 JSON Pointer using only supplied block_ids and atom_ids. "
                        "Never invent identifiers or values."
                    ),
                },
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
            max_output_tokens=self.config.terra_max_output_tokens
            if use_terra
            else self.config.luna_max_output_tokens,
        )
        call_usage = self._record_usage(response, agent=agent, model=model)
        self.trace.append(
            AgentTraceEvent(
                agent=agent,
                model=model,
                action="extract_document",
                status="completed",
                duration_ms=round((time.perf_counter() - started) * 1000),
                input_tokens=call_usage.input_tokens,
                output_tokens=call_usage.output_tokens,
            )
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str):
            raise RuntimeError(  # noqa: TRY004 - malformed provider response
                "extract_document: OpenAI returned no JSON output"
            )
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("extract_document: OpenAI returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(  # noqa: TRY004 - malformed provider response
                "extract_document: OpenAI returned a non-object result"
            )
        return payload
