from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from grounded_docparse.gemini_gateway import _GeminiResponses
from grounded_docparse.models import PageDraft
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


def test_page_draft_uses_required_gemini_boxes_and_normalizes_them() -> None:
    captured = {}

    class Models:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                parsed={
                    "regions": [
                        {
                            "type": "paragraph",
                            "bbox": [100, 200, 300, 800],
                            "reading_order": 0,
                            "text": "Grounded text",
                            "atoms": [
                                {
                                    "kind": "text",
                                    "text": "Grounded text",
                                    "bbox": [110, 210, 290, 790],
                                }
                            ],
                            "table_cells": [
                                {
                                    "row_index": 0,
                                    "column_index": 0,
                                    "text": "Cell",
                                    "bbox": [120, 220, 280, 780],
                                }
                            ],
                        }
                    ],
                    "warnings": [],
                },
                text=None,
                usage_metadata=None,
            )

    result = _GeminiResponses(SimpleNamespace(models=Models())).parse(
        text_format=PageDraft,
        model="gemini-test",
        input=[{"role": "user", "content": "extract page"}],
    )

    schema = captured["config"].response_json_schema
    box_schema = schema["$defs"]["DraftBoundingBox"]
    assert box_schema["minItems"] == box_schema["maxItems"] == 4
    assert box_schema["items"] == {"type": "integer", "minimum": 0, "maximum": 1000}
    for definition in ("RegionDraft", "AtomicDraft", "TableCellDraft"):
        assert "bbox" in schema["$defs"][definition]["required"]
    assert result.output_parsed.regions[0].bbox.model_dump() == {
        "x0": 0.2,
        "y0": 0.1,
        "x1": 0.8,
        "y1": 0.3,
    }
    assert result.output_parsed.regions[0].atoms[0].bbox.model_dump() == {
        "x0": 0.21,
        "y0": 0.11,
        "x1": 0.79,
        "y1": 0.29,
    }
    assert result.output_parsed.regions[0].table_cells[0].bbox.model_dump() == {
        "x0": 0.22,
        "y0": 0.12,
        "x1": 0.78,
        "y1": 0.28,
    }


@pytest.mark.parametrize(
    "bbox",
    [None, [100, 200, 100, 800], [100, 200, 300], [100, -1, 300, 800]],
)
def test_page_draft_rejects_missing_or_invalid_gemini_boxes(bbox) -> None:
    class Models:
        def generate_content(self, **_kwargs):
            region = {
                "type": "paragraph",
                "reading_order": 0,
                "text": "Ungrounded text",
                "atoms": [],
                "table_cells": [],
            }
            if bbox is not None:
                region["bbox"] = bbox
            return SimpleNamespace(
                parsed={"regions": [region], "warnings": []},
                text=None,
                usage_metadata=None,
            )

    responses = _GeminiResponses(SimpleNamespace(models=Models()))

    with pytest.raises(RetryableProviderError, match="bounding box"):
        responses.parse(
            text_format=PageDraft,
            model="gemini-test",
            input=[{"role": "user", "content": "extract page"}],
        )


def test_blank_gemini_page_draft_does_not_require_boxes() -> None:
    class Models:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(
                parsed={"regions": [], "warnings": []},
                text=None,
                usage_metadata=None,
            )

    result = _GeminiResponses(SimpleNamespace(models=Models())).parse(
        text_format=PageDraft,
        model="gemini-test",
        input=[{"role": "user", "content": "extract blank page"}],
    )

    assert result.output_parsed.regions == []
