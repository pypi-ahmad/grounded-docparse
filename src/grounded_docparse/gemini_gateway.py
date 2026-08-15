from __future__ import annotations

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
from .runtime import RetryableProviderError

GEMINI_MAX_OUTPUT_TOKENS = 65_536


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
                response_json_schema=text_format.model_json_schema(),
                max_output_tokens=_max_output_tokens(kwargs.get("max_output_tokens")),
                thinking_config=types.ThinkingConfig(thinking_level=effort),
            ),
        )
        try:
            sdk_parsed = getattr(response, "parsed", None)
            parsed = (
                text_format.model_validate(sdk_parsed)
                if sdk_parsed is not None
                else text_format.model_validate_json(response.text)
            )
        except ValidationError as exc:
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
