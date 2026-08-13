from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from grounded_docparse.models import SchemaField, StoredSchema
from grounded_docparse.native import (
    NativeDocument,
    NativeElement,
    NativeParseResult,
    PageRoute,
    ProcessingType,
    SourceFormat,
    SourceSpan,
    SourceUnit,
    TextSourceAnchor,
    render_native_combined_result,
)
from grounded_docparse.native_extraction import (
    LangExtractNativeExtractor,
    translate_stored_schema,
)


def _result(text: str = "Invoice 42 true") -> NativeParseResult:
    document = NativeDocument(
        source_name="invoice.html",
        source_sha256="a" * 64,
        source_format=SourceFormat.HTML,
        requested_processing_type=ProcessingType.OTHER_NATIVE,
        base_text=text,
        units=[
            SourceUnit(
                id="document-1",
                kind="document",
                index=1,
                requested_route=PageRoute.NATIVE,
                effective_route=PageRoute.NATIVE,
                parser="docling",
            )
        ],
        elements=[
            NativeElement(
                id="text-1",
                type="text",
                text=text,
                reading_order=0,
                source=SourceSpan(
                    start=0,
                    end=len(text),
                    element_id="text-1",
                    anchor=TextSourceAnchor(
                        unit_id="document-1",
                        start_line=1,
                        end_line=1,
                        start_column=1,
                        end_column=len(text) + 1,
                    ),
                ),
            )
        ],
    )
    return NativeParseResult(document=document, markdown="# Refined content", json="{}")


def _extraction(name: str, text: str, start: int | None, end: int | None, **extra):
    interval = (
        None
        if start is None
        else SimpleNamespace(start_pos=start, end_pos=end)
    )
    return SimpleNamespace(
        extraction_class=name,
        extraction_text=text,
        char_interval=interval,
        **extra,
    )


def _schema() -> StoredSchema:
    return StoredSchema(
        name="invoice",
        fields=[
            SchemaField(name="number", type="integer"),
            SchemaField(name="paid", type="boolean"),
        ],
    )


def test_native_extraction_uses_only_base_text_and_fixed_model(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")

    def fake_extract(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            extractions=[
                _extraction("field_0001", "42", 8, 10),
                _extraction("field_0002", "true", 11, 15),
            ]
        )

    result = LangExtractNativeExtractor(extract_func=fake_extract).extract(
        _result(), _schema()
    )

    call = calls[0]
    assert call["text_or_documents"] == "Invoice 42 true"
    assert "Refined" not in call["text_or_documents"]
    assert call["config"]["model_id"] == "gpt-5.6-luna"
    assert call["config"]["provider_kwargs"]["reasoning_effort"] == "medium"
    assert call["config"]["provider_kwargs"]["base_url"] == "https://example.invalid/v1"
    assert call["fetch_urls"] is False
    assert call["resolver_params"]["enable_fuzzy_alignment"] is False
    assert result.data == {"number": 42, "paid": True}
    assert result.values[0].evidence.source_text == "42"
    assert result.values[0].evidence.source_spans[0].element_id == "text-1"


@pytest.mark.parametrize(
    "item,warning",
    [
        (_extraction("field_0001", "42", None, None), "char_interval"),
        (_extraction("field_0001", "99", 8, 10), "non-exact"),
        (_extraction("field_0001", "42", 8, 99), "char_interval"),
    ],
)
def test_native_extraction_rejects_ungrounded_values(
    monkeypatch, item, warning
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    extractor = LangExtractNativeExtractor(
        extract_func=lambda **_kwargs: SimpleNamespace(extractions=[item])
    )

    result = extractor.extract(_result(), _schema())

    assert result.data == {"number": None, "paid": None}
    assert result.values == []
    assert warning in result.warnings[0]


def test_native_extraction_rejects_unknown_class(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    extractor = LangExtractNativeExtractor(
        extract_func=lambda **_kwargs: SimpleNamespace(
            extractions=[_extraction("invented_field", "42", 8, 10)]
        )
    )

    result = extractor.extract(_result(), _schema())

    assert result.values == []
    assert result.data == {"number": None, "paid": None}
    assert "unknown extraction class" in result.warnings[0]


def test_native_extraction_rejects_partially_unanchored_interval(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    parse_result = _result()
    parse_result.document.elements[0].source.end = 9
    extractor = LangExtractNativeExtractor(
        extract_func=lambda **_kwargs: SimpleNamespace(
            extractions=[_extraction("field_0001", "42", 8, 10)]
        )
    )

    result = extractor.extract(parse_result, _schema())

    assert result.values == []
    assert result.data["number"] is None
    assert "unresolved source anchor" in result.warnings[0]


def test_schema_translation_supports_flat_arrays_and_rejects_nested_arrays() -> None:
    flat = StoredSchema(
        version=2,
        name="lines",
        json_schema={
            "type": "object",
            "properties": {
                "lines": {
                    "type": ["array", "null"],
                    "items": {
                        "type": ["object", "null"],
                        "properties": {
                            "description": {"type": ["string", "null"]},
                            "quantity": {"type": ["integer", "null"]},
                        },
                        "required": ["description", "quantity"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["lines"],
            "additionalProperties": False,
        },
    )
    translated = translate_stored_schema(flat)
    assert [field.pointer_template for field in translated.groups[0].fields] == [
        "/lines/*/description",
        "/lines/*/quantity",
    ]

    nested = flat.model_copy(deep=True)
    nested.json_schema["properties"]["lines"]["items"]["properties"]["tags"] = {
        "type": ["array", "null"],
        "items": {"type": ["string", "null"]},
    }
    nested.json_schema["properties"]["lines"]["items"]["required"].append("tags")
    with pytest.raises(ValueError, match="nested arrays"):
        translate_stored_schema(nested)


def test_combined_native_export_contains_grounded_extraction(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    extracted = LangExtractNativeExtractor(
        extract_func=lambda **_kwargs: SimpleNamespace(
            extractions=[_extraction("field_0001", "42", 8, 10)]
        )
    ).extract(_result(), _schema())

    payload = json.loads(render_native_combined_result(_result(), extracted))

    assert payload["schema_version"] == "5.1.0"
    assert payload["extraction"]["values"][0]["evidence"]["source_text"] == "42"
