import json

import pytest
from pydantic import ValidationError

from grounded_docparse.native import (
    NativeDocument,
    NativeElement,
    NativeParseResult,
    PageRoute,
    PdfSourceAnchor,
    ProcessingType,
    SourceAnchor,
    SourceFormat,
    SourceSpan,
    SourceUnit,
    StructuralSourceAnchor,
    render_native_document,
)


def _document() -> NativeDocument:
    return NativeDocument(
        source_name="notice.pdf",
        source_sha256="a" * 64,
        source_format=SourceFormat.PDF,
        requested_processing_type=ProcessingType.NATIVE_PDF,
        base_text="Public notice",
        units=[
            SourceUnit(
                id="page-1",
                kind="page",
                index=1,
                requested_route=PageRoute.NATIVE,
                effective_route=PageRoute.NATIVE,
                parser="pdf-inspector",
            )
        ],
        elements=[
            NativeElement(
                id="page-1-item-1",
                type="text",
                text="Public notice",
                reading_order=0,
                source=SourceSpan(
                    start=0,
                    end=13,
                    element_id="page-1-item-1",
                    anchor=PdfSourceAnchor(
                        unit_id="page-1",
                        page=1,
                        bbox=(0.1, 0.1, 0.5, 0.2),
                    ),
                ),
            )
        ],
    )


def test_native_v5_contract_uses_immutable_base_text_ranges() -> None:
    rendered = render_native_document(_document(), markdown="# Public notice")
    payload = json.loads(rendered.json)

    assert payload["schema_version"] == "5.0.0"
    assert payload["base_text"] == "Public notice"
    assert payload["metadata"]["range_target"] == "base_text"
    assert payload["metadata"]["range_units"] == "unicode_codepoints"
    assert payload["document"]["units"][0]["effective_route"] == "native"
    assert payload["elements"][0]["source"]["anchor"]["kind"] == "pdf"


def test_native_document_rejects_out_of_range_span() -> None:
    document = _document().model_dump()
    document["elements"][0]["source"]["end"] = 99

    with pytest.raises(ValidationError, match="outside base_text"):
        NativeDocument.model_validate(document)


def test_native_document_rejects_unknown_anchor_unit() -> None:
    document = _document().model_dump()
    document["elements"][0]["source"]["anchor"] = StructuralSourceAnchor(
        unit_id="missing",
        path="#/texts/0",
    ).model_dump()

    with pytest.raises(ValidationError, match="unknown unit"):
        NativeDocument.model_validate(document)


def test_native_document_rejects_mismatched_element_id() -> None:
    document = _document().model_dump()
    document["elements"][0]["source"]["element_id"] = "different"

    with pytest.raises(ValidationError, match="element_id"):
        NativeDocument.model_validate(document)


def test_processing_type_values_and_source_anchor_are_public() -> None:
    assert [item.value for item in ProcessingType] == [
        "native-pdf",
        "scanned-pdf",
        "mixed-pdf",
        "word",
        "powerpoint",
        "excel",
        "csv",
        "image",
        "other-native",
    ]
    assert SourceAnchor is not None


def test_base_text_is_immutable() -> None:
    document = _document()

    with pytest.raises(ValidationError, match="Field is frozen"):
        document.base_text = "changed"


def test_character_range_maps_to_all_intersecting_source_spans() -> None:
    document = _document()
    second = NativeElement(
        id="page-1-item-2",
        type="text",
        text="notice",
        reading_order=1,
        source=SourceSpan(
            start=7,
            end=13,
            element_id="page-1-item-2",
            anchor=PdfSourceAnchor(unit_id="page-1", page=1),
        ),
    )
    document.elements.append(second)

    assert [span.element_id for span in document.source_spans_for(6, 9)] == [
        "page-1-item-1",
        "page-1-item-2",
    ]


@pytest.mark.parametrize("start,end", [(-1, 1), (1, 1), (0, 99)])
def test_character_range_rejects_invalid_bounds(start: int, end: int) -> None:
    with pytest.raises(ValueError, match="within base_text"):
        _document().source_spans_for(start, end)


def test_annotated_pdf_is_optional_for_native_results() -> None:
    rendered = render_native_document(_document(), markdown="Public notice")

    result = NativeParseResult(
        document=_document(),
        markdown=rendered.markdown,
        json=rendered.json,
    )

    assert result.annotated_pdf is None
