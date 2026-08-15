from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from grounded_docparse.gemini_gateway import _GeminiResponses
from grounded_docparse.runtime import RetryableProviderError


class _StructuredResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, str]


def test_parse_uses_json_schema_for_pydantic_models() -> None:
    captured = {}

    class Models:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                parsed=None,
                text='{"values":{"name":"example"}}',
                usage_metadata=None,
            )

    responses = _GeminiResponses(SimpleNamespace(models=Models()))

    result = responses.parse(
        text_format=_StructuredResult,
        model="gemini-test",
        input=[{"role": "user", "content": "extract values"}],
        max_output_tokens=128_000,
    )

    config = captured["config"]
    assert config.response_schema is None
    assert config.response_json_schema == _StructuredResult.model_json_schema()
    assert config.max_output_tokens == 65_536
    assert result.output_parsed.values == {"name": "example"}


def test_parse_validates_sdk_parsed_dict_as_pydantic_model() -> None:
    class Models:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(
                parsed={"values": {"name": "example"}},
                text=None,
                usage_metadata=None,
            )

    responses = _GeminiResponses(SimpleNamespace(models=Models()))

    result = responses.parse(
        text_format=_StructuredResult,
        model="gemini-test",
        input=[{"role": "user", "content": "extract values"}],
    )

    assert isinstance(result.output_parsed, _StructuredResult)
    assert result.output_parsed.values == {"name": "example"}


def test_parse_marks_max_tokens_truncation_as_retryable() -> None:
    class Models:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(
                parsed=None,
                text='{"values": {"name": "truncated',
                candidates=[
                    SimpleNamespace(
                        finish_reason=SimpleNamespace(name="MAX_TOKENS")
                    )
                ],
                usage_metadata=None,
            )

    responses = _GeminiResponses(SimpleNamespace(models=Models()))

    with pytest.raises(RetryableProviderError, match="output token limit"):
        responses.parse(
            text_format=_StructuredResult,
            model="gemini-test",
            input=[{"role": "user", "content": "extract values"}],
        )
