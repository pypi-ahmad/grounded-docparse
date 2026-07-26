from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, TypeVar

import ollama
from openai import OpenAI
from pydantic import BaseModel

from .config import ParserConfig
from .ingest import PageEvidence
from .models import (
    BoundaryAdjudication,
    DocumentResolution,
    ExtractionDecisions,
    InspectionDecision,
    NodeType,
    PageDraft,
    PageInspection,
    PageVerification,
    RecognitionCandidate,
    RegionEvidence,
    RunRecord,
)

PROMPT_VERSION = "grounded-v1"
GLM_PROMPT_VERSION = "glm-region-v1"
T = TypeVar("T", bound=BaseModel)


class GlmOcrGateway:
    def __init__(self, config: ParserConfig) -> None:
        self.config = config
        self.client = ollama.Client(host=config.ollama_host)

    @staticmethod
    def prompt_for(node_type: NodeType) -> str:
        if node_type == NodeType.TABLE:
            return "Table Recognition:"
        if node_type == NodeType.FORMULA:
            return "Formula Recognition:"
        if node_type in {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}:
            return "Figure Recognition:"
        return "Text Recognition:"

    def recognize(self, image_path: Path) -> tuple[str, RunRecord]:
        candidate, run = self.recognize_region(
            image_path,
            NodeType.OCR_BLOCK,
            region_id="full-page",
            pass_number=1,
        )
        return candidate.text, run

    def recognize_region(
        self,
        image_path: Path,
        node_type: NodeType,
        *,
        region_id: str,
        pass_number: int,
    ) -> tuple[RecognitionCandidate, RunRecord]:
        started = time.monotonic()
        prompt = self.prompt_for(node_type)
        response = self.client.chat(
            model=self.config.glm_model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                    "images": [str(image_path)],
                }
            ],
            options={
                "temperature": 0,
                "num_predict": self.config.glm_max_output_tokens,
            },
            keep_alive="5m",
        )
        content = response.message.content or ""
        candidate = RecognitionCandidate(
            id=f"{region_id}:glm:{pass_number}",
            source="glm",
            task=prompt.removesuffix(":").casefold().replace(" recognition", ""),
            prompt_version=GLM_PROMPT_VERSION,
            pass_number=pass_number,
            text=content[:100_000],
        )
        return candidate, RunRecord(
            provider="ollama",
            model=self.config.glm_model,
            stage="region_ocr" if region_id != "full-page" else "ocr",
            region_id=region_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=getattr(response, "prompt_eval_count", None),
            output_tokens=getattr(response, "eval_count", None),
        )

    def unload(self) -> None:
        try:
            self.client.generate(
                model=self.config.glm_model,
                prompt="",
                keep_alive=0,
            )
        except Exception:  # noqa: BLE001,S110 - cleanup must never mask parse result
            pass


class OpenAIDocumentGateway:
    def __init__(self, config: ParserConfig, client: Any | None = None) -> None:
        if client is None and not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")
        self.config = config
        self.client = client or OpenAI()

    @staticmethod
    def _image_data_url(path: Path) -> str:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _parsed(response: Any, expected: type[T]) -> T:
        parsed = getattr(response, "output_parsed", None)
        if isinstance(parsed, expected):
            return parsed
        for output in getattr(response, "output", []):
            if getattr(output, "type", None) != "message":
                continue
            for item in getattr(output, "content", []):
                if getattr(item, "type", None) == "refusal":
                    raise RuntimeError(
                        f"OpenAI refused document parsing: {item.refusal}"
                    )
                value = getattr(item, "parsed", None)
                if isinstance(value, expected):
                    return value
        raise RuntimeError("OpenAI returned no schema-valid parsed result")

    @staticmethod
    def _usage(response: Any) -> tuple[int | None, int | None]:
        usage = getattr(response, "usage", None)
        return (
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )

    def draft_page(self, page: PageEvidence) -> tuple[PageDraft, RunRecord]:
        prompt = (
            "Parse the page into a hierarchical, visually grounded item tree. "
            "Return literal visible text only. Include headers, footers, sections, "
            "tables, table cells, figures, charts, forms, and checkboxes when visible. "
            "Every region must use normalized page coordinates and explicit reading "
            "order. Never infer missing text or facts."
        )
        started = time.monotonic()
        response = self.client.responses.parse(
            model=self.config.luna_model,
            reasoning={"effort": "low"},
            temperature=0.0,
            store=False,
            prompt_cache_key=f"docparse:luna-draft:{PROMPT_VERSION}:0",
            prompt_cache_options={"mode": "explicit", "ttl": "24h"},
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                            "prompt_cache_breakpoint": {"type": "default"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": page.digital_text[:200_000]
                            or "No embedded PDF text is available.",
                        },
                        {
                            "type": "input_image",
                            "image_url": self._image_data_url(page.image_path),
                            "detail": "original",
                        },
                    ],
                },
            ],
            text_format=PageDraft,
            max_output_tokens=self.config.luna_max_output_tokens,
        )
        input_tokens, output_tokens = self._usage(response)
        return self._parsed(response, PageDraft), RunRecord(
            provider="openai",
            model=self.config.luna_model,
            stage="page_draft",
            page_number=page.number,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_version=PROMPT_VERSION,
        )

    def inspect_page(
        self,
        page: PageEvidence,
        draft: PageDraft,
        *,
        region_ids: list[str],
    ) -> tuple[PageInspection, RunRecord]:
        prompt = (
            "Independently inspect each supplied draft region against the page image. "
            "For every region return accept, correct, reject, or inspect_crop. "
            "Corrections must be literal visible text. Reject unsupported content and "
            "request a crop when the page image is insufficient. Never invent IDs, "
            "coordinates, text, or facts."
        )
        regions = []
        for index, region in enumerate(draft.regions):
            region_id = (
                region_ids[index] if index < len(region_ids) else f"region-{index + 1}"
            )
            regions.append({"region_id": region_id, **region.model_dump(mode="json")})
        started = time.monotonic()
        response = self.client.responses.parse(
            model=self.config.terra_model,
            reasoning={"effort": "low"},
            temperature=0.0,
            store=False,
            prompt_cache_key=f"docparse:terra-inspection:{PROMPT_VERSION}:0",
            prompt_cache_options={"mode": "explicit", "ttl": "24h"},
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                            "prompt_cache_breakpoint": {"type": "default"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(regions, ensure_ascii=False)[:700_000],
                        },
                        {
                            "type": "input_image",
                            "image_url": self._image_data_url(page.image_path),
                            "detail": "original",
                        },
                    ],
                },
            ],
            text_format=PageInspection,
            max_output_tokens=self.config.terra_max_output_tokens,
        )
        input_tokens, output_tokens = self._usage(response)
        return self._parsed(response, PageInspection), RunRecord(
            provider="openai",
            model=self.config.terra_model,
            stage="page_inspection",
            page_number=page.number,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_version=PROMPT_VERSION,
        )

    def inspect_crop(
        self,
        crop_path: Path,
        *,
        region_id: str,
        candidate_text: str,
        evidence_ref: str,
        attempt: int,
    ) -> tuple[InspectionDecision, RunRecord]:
        prompt = (
            "Inspect this high-resolution source crop. Accept only when the candidate "
            "is literally visible. Correct only with literal text from the crop, reject "
            "unsupported content, or request another crop when still ambiguous. Preserve "
            "the supplied region ID and evidence reference."
        )
        started = time.monotonic()
        response = self.client.responses.parse(
            model=self.config.terra_model,
            reasoning={"effort": "low"},
            temperature=0.0,
            store=False,
            prompt_cache_key=f"docparse:terra-crop:{PROMPT_VERSION}:0",
            prompt_cache_options={"mode": "explicit", "ttl": "24h"},
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                            "prompt_cache_breakpoint": {"type": "default"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "region_id": region_id,
                                    "candidate_text": candidate_text,
                                    "evidence_ref": evidence_ref,
                                    "attempt": attempt,
                                },
                                ensure_ascii=False,
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": self._image_data_url(crop_path),
                            "detail": "original",
                        },
                    ],
                },
            ],
            text_format=InspectionDecision,
            max_output_tokens=min(4_000, self.config.terra_max_output_tokens),
        )
        decision = self._parsed(response, InspectionDecision)
        if decision.region_id != region_id or evidence_ref not in decision.evidence_refs:
            raise RuntimeError("Crop inspection returned mismatched evidence")
        input_tokens, output_tokens = self._usage(response)
        return decision, RunRecord(
            provider="openai",
            model=self.config.terra_model,
            stage="crop_inspection",
            region_id=region_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_version=PROMPT_VERSION,
        )

    def verify_page(
        self,
        page: PageEvidence,
        regions: list[RegionEvidence],
    ) -> tuple[PageVerification, RunRecord]:
        evidence = [region.model_dump(mode="json") for region in regions]
        prompt = (
            "Verify OCR candidates against the page image. For each supplied region, "
            "select an existing candidate ID when literal text matches. Set needs_retry "
            "when candidates disagree or are wrong. proposed_text is allowed only for "
            "literal visible text and will not be trusted until local OCR confirms it. "
            "You may refine semantic_role. Never invent regions, IDs, facts, or text."
        )
        started = time.monotonic()
        response = self.client.responses.parse(
            model=self.config.luna_model,
            reasoning={"effort": "low"},
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(evidence, ensure_ascii=False)[:700_000],
                        },
                        {
                            "type": "input_image",
                            "image_url": self._image_data_url(page.image_path),
                            "detail": "original",
                        },
                    ],
                },
            ],
            text_format=PageVerification,
            max_output_tokens=self.config.luna_max_output_tokens,
        )
        input_tokens, output_tokens = self._usage(response)
        return self._parsed(response, PageVerification), RunRecord(
            provider="openai",
            model=self.config.luna_model,
            stage="page_verification",
            page_number=page.number,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def resolve_document(
        self, node_summary: list[dict[str, Any]]
    ) -> tuple[DocumentResolution, RunRecord]:
        prompt = (
            "Resolve cross-page document structure from grounded nodes. Only update "
            "heading roles/levels and add explicit relationships such as continues, "
            "caption_of, footnote_of, references, and same_table. Do not rewrite text, "
            "invent nodes, or reference unknown IDs."
        )
        started = time.monotonic()
        response = self.client.responses.parse(
            model=self.config.terra_model,
            reasoning={"effort": "high"},
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(node_summary, ensure_ascii=False)[:700_000],
                },
            ],
            text_format=DocumentResolution,
            max_output_tokens=self.config.terra_max_output_tokens,
        )
        input_tokens, output_tokens = self._usage(response)
        return self._parsed(response, DocumentResolution), RunRecord(
            provider="openai",
            model=self.config.terra_model,
            stage="document_resolution",
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def resolve_extraction(
        self,
        schema: dict[str, Any],
        evidence: list[dict[str, Any]],
        *,
        unresolved_paths: list[str],
        use_terra: bool = False,
    ) -> tuple[ExtractionDecisions, RunRecord]:
        prompt = (
            "Map requested scalar JSON Pointer paths to literal values in the supplied "
            "grounded nodes. Return only existing node IDs and literal visible values. "
            "Do not infer missing values, invent IDs, rewrite evidence, or provide coordinates. "
            "Omit any path that is not directly supported."
        )
        model = self.config.terra_model if use_terra else self.config.luna_model
        started = time.monotonic()
        payload = json.dumps(
            {
                "schema": schema,
                "requested_paths": unresolved_paths,
                "evidence": evidence,
            },
            ensure_ascii=False,
        )[:700_000]
        response = self.client.responses.parse(
            model=model,
            reasoning={"effort": "medium" if use_terra else "low"},
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": payload},
            ],
            text_format=ExtractionDecisions,
            max_output_tokens=(
                self.config.terra_max_output_tokens
                if use_terra
                else self.config.luna_max_output_tokens
            ),
        )
        input_tokens, output_tokens = self._usage(response)
        return self._parsed(response, ExtractionDecisions), RunRecord(
            provider="openai",
            model=model,
            stage="schema_extraction",
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_version="schema-extraction-v1",
        )

    def adjudicate_boundary(
        self,
        previous_page: PageEvidence,
        current_page: PageEvidence,
        evidence: dict[str, Any],
        *,
        use_terra: bool = False,
    ) -> tuple[BoundaryAdjudication, RunRecord]:
        model = self.config.terra_model if use_terra else self.config.luna_model
        prompt = (
            "Decide whether the current page begins a new contiguous document. "
            "Use only supplied classifications, identifiers, node IDs, and visible "
            "page evidence. Return split, keep, or uncertain. Never invent text, "
            "identifiers, or facts. Repeated primary identifiers strongly imply keep; "
            "a changed primary identifier strongly implies split."
        )
        started = time.monotonic()
        response = self.client.responses.parse(
            model=model,
            reasoning={"effort": "high" if use_terra else "low"},
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(evidence, ensure_ascii=False)[:100_000],
                        },
                        {
                            "type": "input_image",
                            "image_url": self._image_data_url(previous_page.image_path),
                            "detail": "low",
                        },
                        {
                            "type": "input_image",
                            "image_url": self._image_data_url(current_page.image_path),
                            "detail": "low",
                        },
                    ],
                },
            ],
            text_format=BoundaryAdjudication,
            max_output_tokens=min(2_000, self.config.terra_max_output_tokens if use_terra else self.config.luna_max_output_tokens),
        )
        input_tokens, output_tokens = self._usage(response)
        return self._parsed(response, BoundaryAdjudication), RunRecord(
            provider="openai",
            model=model,
            stage="boundary_adjudication",
            page_number=current_page.number,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
