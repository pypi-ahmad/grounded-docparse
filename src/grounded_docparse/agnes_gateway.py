from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any


def _chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            output.append({"role": message.get("role", "user"), "content": content})
            continue
        parts: list[dict[str, Any]] = []
        for item in content or []:
            if item.get("type") == "input_text":
                parts.append({"type": "text", "text": item.get("text", "")})
            elif item.get("type") == "input_image":
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": item.get("image_url", "")},
                    }
                )
        output.append({"role": message.get("role", "user"), "content": parts})
    return output


def _usage(completion: Any) -> Any:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "prompt_tokens_details", None)
    return SimpleNamespace(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        input_tokens_details=SimpleNamespace(
            cached_tokens=getattr(details, "cached_tokens", 0) or 0
        ),
    )


class AgnesResponses:
    """Responses-shaped adapter over Agnes' OpenAI-compatible chat API."""

    def __init__(self, completions: Any) -> None:
        self._completions = completions

    def parse(self, *, text_format: type, **kwargs: Any) -> Any:
        completion = self._completions.create(
            model=kwargs["model"],
            messages=_chat_messages(kwargs["input"]),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": text_format.__name__,
                    "strict": True,
                    "schema": text_format.model_json_schema(),
                },
            },
            temperature=0,
            max_tokens=kwargs.get("max_output_tokens"),
        )
        content = completion.choices[0].message.content
        parsed = text_format.model_validate_json(content)
        return SimpleNamespace(
            output_parsed=parsed,
            output=[],
            usage=_usage(completion),
        )

    def create(self, **kwargs: Any) -> Any:
        schema = kwargs.get("text", {}).get("format", {}).get("schema")
        request: dict[str, Any] = {
            "model": kwargs["model"],
            "messages": _chat_messages(kwargs["input"]),
            "temperature": 0,
            "max_tokens": kwargs.get("max_output_tokens"),
        }
        if schema is not None:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": kwargs["text"]["format"].get("name", "response"),
                    "strict": True,
                    "schema": schema,
                },
            }
        completion = self._completions.create(**request)
        content = completion.choices[0].message.content
        json.loads(content)
        return SimpleNamespace(
            output_text=content,
            output=[],
            usage=_usage(completion),
        )
