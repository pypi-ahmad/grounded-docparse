"""Gemini adapter presenting the `.responses.parse`/`.create` surface gateways.py expects.

Wraps `google-genai` behind the same shape OpenAIDocumentGateway calls, plus
Gemini-specific handling: its structured-output schema needs an explicit
integer bounding-box definition (Gemini has no native box type), and its
JSON output can be truncated by MAX_TOKENS rather than cleanly failing
validation.

Must not: let a malformed or missing bounding box, or a MAX_TOKENS truncation,
surface as a plain validation error - those are raised as
RetryableProviderError so ProviderRuntime's retry loop (see runtime.py's
`_is_retryable`) picks them up instead of failing the page outright.

Next: agnes_gateway.py for the sibling (OpenAI-compatible, simpler) adapter,
or gateways.py for the interface both adapters implement.
"""

import base64
import json
import os
from types import SimpleNamespace
from typing import Any

from google import genai
from google.genai import types
from pydantic import ValidationError

from .config import ParserConfig
from .gateways import OpenAIDocumentGateway
from .models import PageDraft
from .runtime import RetryableProviderError

GEMINI_MAX_OUTPUT_TOKENS = 65_536

_GEMINI_BOX_DESCRIPTION = (
    "Required bounding box as [ymin, xmin, ymax, xmax], normalized to integer "
    "coordinates from 0 to 1000."
)


def _response_schema(text_format: type) -> dict[str, Any]:
    # PageDraft's bbox fields are normally untyped/opaque to the JSON Schema
    # Gemini receives; here they're pinned to an explicit 4-integer array in
    # Gemini's own coordinate space (see _GEMINI_BOX_DESCRIPTION: [ymin,
    # xmin, ymax, xmax], 0-1000) since that's what its structured output
    # actually returns - _normalize_page_draft_boxes converts it back to
    # this app's normalized 0-1 x0/y0/x1/y1 boxes afterward.
    schema = text_format.model_json_schema()
    if text_format is not PageDraft:
        return schema
    definitions = schema.get("$defs", {})
    definitions["DraftBoundingBox"] = {
        "type": "array",
        "items": {"type": "integer", "minimum": 0, "maximum": 1000},
        "minItems": 4,
        "maxItems": 4,
        "description": _GEMINI_BOX_DESCRIPTION,
    }
    for name in ("RegionDraft", "AtomicDraft", "TableCellDraft"):
        definition = definitions[name]
        definition["properties"]["bbox"] = {
            "$ref": "#/$defs/DraftBoundingBox",
            "description": _GEMINI_BOX_DESCRIPTION,
        }
        required = definition.setdefault("required", [])
        if "bbox" not in required:
            required.append("bbox")
    return schema


def _normalize_page_draft_boxes(value: Any) -> Any:
    # Recursively converts every "bbox" in the raw (untrusted) Gemini
    # payload from its [ymin, xmin, ymax, xmax] / 0-1000 coordinate space to
    # this app's normalized {x0,y0,x1,y1} 0-1 space. A box that's malformed,
    # out of range, or degenerate (zero/negative width or height) raises
    # RetryableProviderError rather than being silently coerced, so the
    # retry loop gets a chance at a better response instead of grounding
    # evidence against a bad box.
    if isinstance(value, list):
        return [_normalize_page_draft_boxes(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {}
    for key, item in value.items():
        if key != "bbox" or not isinstance(item, list):
            normalized[key] = _normalize_page_draft_boxes(item)
            continue
        if (
            len(item) != 4
            or any(isinstance(number, bool) or not isinstance(number, (int, float)) for number in item)
            or any(number < 0 or number > 1000 for number in item)
        ):
            raise RetryableProviderError("Gemini returned an invalid bounding box")
        ymin, xmin, ymax, xmax = item
        if ymax <= ymin or xmax <= xmin:
            raise RetryableProviderError("Gemini returned an invalid bounding box")
        normalized[key] = {
            "x0": xmin / 1000,
            "y0": ymin / 1000,
            "x1": xmax / 1000,
            "y1": ymax / 1000,
        }
    return normalized


def _validate_page_draft_grounding(draft: PageDraft) -> None:
    # A region/atom/table cell with no bbox at all can't be grounded, so
    # (like an invalid box above) this is treated as retryable rather than
    # accepted with missing evidence.
    missing = 0
    for region in draft.regions:
        missing += region.bbox is None
        missing += sum(atom.bbox is None for atom in region.atoms)
        missing += sum(cell.bbox is None for cell in region.table_cells)
    if missing:
        raise RetryableProviderError(
            f"Gemini omitted {missing} required bounding box(es)"
        )


def _max_output_tokens(value: Any) -> Any:
    return min(value, GEMINI_MAX_OUTPUT_TOKENS) if isinstance(value, int) else value


def _finish_reason(response: Any) -> str | None:
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    return getattr(reason, "name", None)


def _parts(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value]
    result: list[Any] = []
    for item in value or []:
        if item.get("type") == "input_text":
            result.append(item.get("text", ""))
        elif item.get("type") == "input_image":
            header, payload = item["image_url"].split(",", 1)
            mime_type = header.removeprefix("data:").split(";", 1)[0]
            result.append(types.Part.from_bytes(data=base64.b64decode(payload), mime_type=mime_type))
    return result


def _contents(messages: list[dict[str, Any]]) -> tuple[str | None, list[Any]]:
    system: list[str] = []
    contents: list[Any] = []
    for message in messages:
        if message.get("role") == "system":
            system.extend(str(part) for part in _parts(message.get("content")))
        else:
            contents.extend(_parts(message.get("content")))
    return ("\n\n".join(system) or None), contents


class _GeminiResponses:
    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _usage(response: Any) -> Any:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return None
        return SimpleNamespace(
            input_tokens=getattr(metadata, "prompt_token_count", 0) or 0,
            output_tokens=getattr(metadata, "candidates_token_count", 0) or 0,
            input_tokens_details=SimpleNamespace(cached_tokens=getattr(metadata, "cached_content_token_count", 0) or 0),
        )

    def parse(self, *, text_format: type, **kwargs: Any) -> Any:
        system, contents = _contents(kwargs["input"])
        effort = kwargs.get("reasoning", {}).get("effort", "medium")
        response = self._client.models.generate_content(
            model=kwargs["model"],
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=_response_schema(text_format),
                max_output_tokens=_max_output_tokens(kwargs.get("max_output_tokens")),
                thinking_config=types.ThinkingConfig(thinking_level=effort),
            ),
        )
        try:
            sdk_parsed = getattr(response, "parsed", None)
            payload = sdk_parsed if sdk_parsed is not None else json.loads(response.text)
            if text_format is PageDraft:
                payload = _normalize_page_draft_boxes(payload)
            parsed = text_format.model_validate(payload)
            if isinstance(parsed, PageDraft):
                _validate_page_draft_grounding(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            # A MAX_TOKENS finish reason means the JSON was cut off mid-output
            # rather than genuinely malformed - worth a retry (a fresh call
            # may complete within the token budget) instead of surfacing as
            # a hard schema failure.
            if _finish_reason(response) == "MAX_TOKENS":
                raise RetryableProviderError(
                    "Gemini reached its output token limit before completing JSON"
                ) from exc
            raise
        return SimpleNamespace(output_parsed=parsed, output=[], usage=self._usage(response))

    def create(self, **kwargs: Any) -> Any:
        system, contents = _contents(kwargs["input"])
        schema = kwargs.get("text", {}).get("format", {}).get("schema")
        response = self._client.models.generate_content(
            model=kwargs["model"],
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema,
                max_output_tokens=_max_output_tokens(kwargs.get("max_output_tokens")),
            ),
        )
        return SimpleNamespace(output_text=response.text, output=[], usage=self._usage(response))


class GeminiDocumentGateway(OpenAIDocumentGateway):
    def __init__(self, config: ParserConfig, client: Any | None = None, runtime=None) -> None:
        if client is None and not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("GOOGLE_API_KEY is not set")
        google_client = client or genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        shim = SimpleNamespace(responses=_GeminiResponses(google_client))
        super().__init__(config, client=shim, runtime=runtime)


def document_gateway(config: ParserConfig, *, runtime=None) -> OpenAIDocumentGateway:
    if config.cloud_model.value.startswith("gemini-"):
        return GeminiDocumentGateway(config, runtime=runtime)
    return OpenAIDocumentGateway(config, runtime=runtime)
