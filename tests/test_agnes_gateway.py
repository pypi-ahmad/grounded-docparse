from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from grounded_docparse.agnes_gateway import AgnesResponses


class Result(BaseModel):
    value: str


class Completions:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value":"ok"}'))],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=3,
                prompt_tokens_details=SimpleNamespace(cached_tokens=2),
            ),
        )


def test_agnes_responses_adapter_preserves_schema_images_and_usage() -> None:
    completions = Completions()
    responses = AgnesResponses(completions)

    result = responses.parse(
        text_format=Result,
        model="agnes-2.5-flash",
        input=[
            {"role": "system", "content": "Return JSON"},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Read"},
                    {"type": "input_image", "image_url": "data:image/png;base64,AA=="},
                ],
            },
        ],
        max_output_tokens=100_000,
    )

    assert result.output_parsed == Result(value="ok")
    assert result.usage.input_tokens == 12
    call = completions.calls[0]
    assert call["max_tokens"] == 65_536
    assert call["response_format"]["type"] == "json_schema"
    assert call["messages"][1]["content"][1]["type"] == "image_url"


def test_agnes_responses_adapter_caps_plain_response_output_tokens() -> None:
    completions = Completions()
    responses = AgnesResponses(completions)

    responses.create(
        model="agnes-2.5-flash",
        input=[{"role": "user", "content": "Return JSON"}],
        max_output_tokens=100_000,
    )

    assert completions.calls[0]["max_tokens"] == 65_536
