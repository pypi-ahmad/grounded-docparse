from __future__ import annotations

import pymupdf
import pytest

from grounded_docparse import DocumentParser, ParserConfig, evaluate_tree
from grounded_docparse.extraction import (
    build_table_exports,
    extract_schema_data,
    validate_extraction_schema,
)


def offline_parser() -> DocumentParser:
    return DocumentParser(
        ParserConfig(enable_paddle=False, enable_glm=False, enable_openai=False, render_dpi=72)
    )


def document_with_lines(lines: list[str]) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 24), line)
    data = document.tobytes()
    document.close()
    return data


def test_nested_schema_extracts_typed_grounded_values() -> None:
    tree = offline_parser().parse(
        document_with_lines(["Invoice Number: INV-42", "Total: $1,234.50"]),
        "invoice.pdf",
    ).tree
    schema = {
        "title": "Invoice extraction",
        "type": "object",
        "properties": {
            "invoice": {
                "type": "object",
                "properties": {
                    "number": {"type": "string", "x-docparse-aliases": ["invoice.number"]},
                    "total": {"type": "number", "x-docparse-aliases": ["invoice.total"]},
                },
                "required": ["number", "total"],
                "additionalProperties": False,
            }
        },
        "required": ["invoice"],
        "additionalProperties": False,
    }
    result = extract_schema_data(tree, schema)
    assert result.status == "complete"
    assert result.data == {"invoice": {"number": "INV-42", "total": 1234.5}}
    assert result.provenance["/invoice/total"].citations[0].bbox is not None


def test_parser_exposes_schema_extraction_and_bundle() -> None:
    import io
    import json
    import zipfile

    schema = {
        "title": "Invoice",
        "type": "object",
        "properties": {
            "number": {"type": "string", "x-docparse-aliases": ["invoice.number"]}
        },
        "required": ["number"],
        "additionalProperties": False,
    }
    result = offline_parser().parse(
        document_with_lines(["Invoice Number: INV-42"]),
        "invoice.pdf",
        extraction_schema=schema,
    )
    assert json.loads(result.extraction_json)["data"] == {"number": "INV-42"}
    assert result.tree.grounded_fields
    assert result.tree.schema_extractions
    assert result.subdocuments[0].extraction_json
    report = evaluate_tree(result.tree, result.tree.model_copy(deep=True))
    assert report.metrics["schema_extraction"]["f1"] == 1
    with zipfile.ZipFile(io.BytesIO(result.bundle)) as archive:
        assert "extraction.manifest.json" in archive.namelist()
        assert any(name.endswith(".extraction.json") for name in archive.namelist())


def test_missing_required_value_is_partial_not_invented() -> None:
    tree = offline_parser().parse(document_with_lines(["Invoice Number: INV-42"]), "invoice.pdf").tree
    schema = {
        "type": "object",
        "properties": {"total": {"type": "number"}},
        "required": ["total"],
        "additionalProperties": False,
    }
    result = extract_schema_data(tree, schema)
    assert result.data == {}
    assert result.status == "partial"
    assert result.validation_errors


def test_schema_rejects_references_and_unsupported_composition() -> None:
    with pytest.raises(ValueError, match="Unsupported extraction schema keywords"):
        validate_extraction_schema(
            {"type": "object", "properties": {}, "$ref": "https://example.com/schema"}
        )
    with pytest.raises(ValueError, match="Unsupported extraction schema keywords"):
        validate_extraction_schema(
            {"type": "object", "properties": {"x": {"oneOf": [{"type": "string"}]}}}
        )


def test_large_cross_page_table_is_stitched_and_exported(monkeypatch) -> None:
    document = pymupdf.open()
    for _ in range(3):
        document.new_page()
    data = document.tobytes()
    document.close()
    payload: dict[int, dict] = {}
    expected_rows = 2_500
    offset = 0
    for page_number, count in enumerate((834, 833, 833), start=1):
        rows = [[{"text": "Item", "header": True}, {"text": "Amount", "header": True}]]
        for index in range(count):
            value = offset + index
            rows.append(
                [
                    {"text": f"SKU-{value}", "bbox": [0.1, 0.1, 0.5, 0.2]},
                    {"text": str(value), "bbox": [0.5, 0.1, 0.9, 0.2]},
                ]
            )
        offset += count
        payload[page_number] = {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.0, 0.9, 1.0],
                    "block_label": "table",
                    "block_order": 0,
                    "block_content": "Item Amount",
                    "table_rows": rows,
                }
            ]
        }
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    parser = DocumentParser(
        ParserConfig(enable_paddle=True, enable_glm=False, enable_openai=False, render_dpi=72)
    )
    tree = parser.parse(data, "large-table.pdf").tree
    assert len(tree.logical_tables) == 1
    assert tree.logical_tables[0].row_count == expected_rows
    schema = {
        "title": "Line items",
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "x-docparse-kind": "table",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "amount": {"type": "integer"},
                    },
                    "required": ["item", "amount"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    extraction = extract_schema_data(tree, schema)
    assert len(extraction.data["items"]) == expected_rows
    assert extraction.data["items"][-1] == {"item": "SKU-2499", "amount": 2499}
    last = extraction.provenance["/items/2499/amount"].citations[0]
    assert last.page_number == 3
    assert last.logical_table_id == tree.logical_tables[0].id
    exports = build_table_exports(extraction, schema)
    jsonl = next(value for key, value in exports.items() if key.endswith(".jsonl"))
    assert len(jsonl.decode().splitlines()) == expected_rows


def test_hybrid_cloud_can_only_select_literal_grounded_values(monkeypatch) -> None:
    from grounded_docparse.models import (
        ExtractionDecisions,
        ExtractionSelection,
        PageVerification,
        ProcessingProfile,
        RunRecord,
    )

    class FakeOpenAI:
        def __init__(self, _config):
            pass

        def verify_page(self, _page, _regions):
            return PageVerification(), RunRecord(
                provider="openai", model="luna", stage="page_verification"
            )

        def resolve_extraction(self, _schema, evidence, **_kwargs):
            node = next(item for item in evidence if "Acme Corporation" in item["text"])
            return ExtractionDecisions(
                selections=[
                    ExtractionSelection(
                        path="/vendor",
                        source_node_ids=[node["id"]],
                        literal_value="Acme Corporation",
                        confidence=0.95,
                    )
                ]
            ), RunRecord(provider="openai", model="luna", stage="schema_extraction")

    monkeypatch.setattr("grounded_docparse.pipeline.OpenAIDocumentGateway", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    schema = {
        "type": "object",
        "properties": {"vendor": {"type": "string"}},
        "required": ["vendor"],
        "additionalProperties": False,
    }
    parser = DocumentParser(
        ParserConfig(enable_paddle=False, enable_glm=False, enable_openai=True, render_dpi=72)
    )
    result = parser.parse(
        document_with_lines(["Supplier is Acme Corporation"]),
        "vendor.pdf",
        profile=ProcessingProfile.HYBRID,
        extraction_schema=schema,
    )
    extraction = result.tree.schema_extractions[0]
    assert extraction.data["vendor"] == "Acme Corporation"
    assert extraction.provenance["/vendor"].method == "luna"


def test_merged_table_cells_propagate_value_with_origin_citation(
    monkeypatch,
) -> None:
    data = document_with_lines(["table"])
    payload = {
        1: {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.1, 0.9, 0.8],
                    "block_label": "table",
                    "block_order": 0,
                    "block_content": "Category Item",
                    "table_rows": [
                        [{"text": "Category", "header": True}, {"text": "Item", "header": True}],
                        [{"text": "A", "rowspan": 2}, {"text": "X"}],
                        [{"text": "Y"}],
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    tree = DocumentParser(
        ParserConfig(enable_paddle=True, enable_glm=False, enable_openai=False, render_dpi=72)
    ).parse(data, "merged.pdf").tree
    schema = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "x-docparse-kind": "table",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "item": {"type": "string"},
                    },
                    "required": ["category", "item"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["rows"],
        "additionalProperties": False,
    }
    extraction = extract_schema_data(tree, schema)
    assert extraction.data["rows"] == [
        {"category": "A", "item": "X"},
        {"category": "A", "item": "Y"},
    ]
    assert (
        extraction.provenance["/rows/0/category"].citations[0].node_id
        == extraction.provenance["/rows/1/category"].citations[0].node_id
    )
