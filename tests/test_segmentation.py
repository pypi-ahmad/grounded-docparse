from __future__ import annotations

import io
import json
import zipfile

import pymupdf

from grounded_docparse import DocumentParser, DocumentProfile, ParserConfig
from grounded_docparse.segmentation import build_batch_manifest


def _document(pages: list[list[str]]) -> bytes:
    document = pymupdf.open()
    for lines in pages:
        page = document.new_page()
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + index * 24), line)
    data = document.tobytes()
    document.close()
    return data


def _tree(pages: list[list[str]]):
    config = ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
    )
    return DocumentParser(config).parse(_document(pages), "batch.pdf").tree


def test_changed_invoice_identifier_splits_contiguous_instances() -> None:
    tree = _tree(
        [
            ["INVOICE", "Invoice Number: INV-1"],
            ["INVOICE", "Invoice Number: INV-1", "Total: $10.00"],
            ["INVOICE", "Invoice Number: INV-2", "Total: $20.00"],
        ]
    )
    manifest = build_batch_manifest(tree, tree.processing_profile, DocumentProfile.AUTO)
    assert [(item.start_page, item.end_page) for item in manifest.subdocuments] == [
        (1, 2),
        (3, 3),
    ]
    assert manifest.boundaries[0].decision == "keep"
    assert manifest.boundaries[1].decision == "split"
    assert "changed_primary_identifier" in manifest.boundaries[1].reasons


def test_mixed_document_types_split() -> None:
    tree = _tree(
        [
            ["INVOICE", "Invoice Number: INV-1", "Amount Due: $10.00"],
            ["RECEIPT", "Transaction ID: TX-9", "Cashier: A", "Total: $10.00"],
        ]
    )
    manifest = build_batch_manifest(tree, tree.processing_profile, DocumentProfile.AUTO)
    assert [item.profile for item in manifest.subdocuments] == ["invoice", "receipt"]
    assert manifest.boundaries[0].decision == "split"


def test_repeated_noncontiguous_identifier_links_without_merging() -> None:
    tree = _tree(
        [
            ["INVOICE", "Invoice Number: INV-1"],
            ["RECEIPT", "Transaction ID: TX-9", "Cashier: A"],
            ["INVOICE", "Invoice Number: INV-1"],
        ]
    )
    manifest = build_batch_manifest(tree, tree.processing_profile, DocumentProfile.AUTO)
    assert len(manifest.subdocuments) == 3
    first, _, third = manifest.subdocuments
    assert third.id in first.related_segment_ids
    assert first.id in third.related_segment_ids


def test_parse_result_contains_master_and_split_document_exports() -> None:
    data = _document(
        [
            ["INVOICE", "Invoice Number: INV-1", "Total: $10.00"],
            ["INVOICE", "Invoice Number: INV-2", "Total: $20.00"],
        ]
    )
    config = ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
    )
    result = DocumentParser(config).parse(data, "batch.pdf")
    assert len(result.subdocuments) == 2
    assert result.tree.document_classification
    assert result.tree.document_classification.profile == "mixed-batch"
    with pymupdf.open(stream=result.subdocuments[0].source_pdf, filetype="pdf") as split:
        assert split.page_count == 1
    assert "segment_page=1" in result.subdocuments[0].llm_markdown
    with zipfile.ZipFile(io.BytesIO(result.bundle)) as archive:
        names = archive.namelist()
        assert "batch.manifest.json" in names
        assert "subdocuments/part-0001-invoice/source.pdf" in names
        assert "batch.failures.jsonl" in names
        assert "subdocuments/part-0001-invoice/part-0001-invoice.failures.jsonl" in names


def test_split_document_extractions_are_aggregated_and_bundled() -> None:
    data = _document(
        [
            ["INVOICE", "Invoice Number: INV-1", "Total: $10.00"],
            ["INVOICE", "Invoice Number: INV-2", "Total: $20.00"],
        ]
    )
    config = ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
    )
    schema = {
        "title": "Invoice extraction",
        "type": "object",
        "properties": {
            "total": {
                "type": "number",
                "x-docparse-aliases": ["invoice total"],
            }
        },
    }

    result = DocumentParser(config).parse(
        data,
        "batch.pdf",
        extraction_schema=schema,
    )

    extraction = json.loads(result.extraction_json)
    assert len(result.subdocuments) == 2
    assert len(result.tree.schema_extractions) == 2
    assert len(extraction["documents"]) == 2
    with zipfile.ZipFile(io.BytesIO(result.bundle)) as archive:
        names = archive.namelist()
        assert "extraction.manifest.json" in names
        assert (
            "subdocuments/part-0001-invoice/"
            "part-0001-invoice.extraction.json"
        ) in names
        assert (
            "subdocuments/part-0002-invoice/"
            "part-0002-invoice.extraction.json"
        ) in names


def test_subdocument_failures_keep_source_page_and_add_segment_page(
    monkeypatch,
) -> None:
    data = _document(
        [
            ["INVOICE", "Invoice Number: INV-1"],
            ["INVOICE", "Invoice Number: INV-2"],
        ]
    )
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: {
            1: {"_provider_error": "first"},
            2: {"_provider_error": "second"},
        },
    )
    config = ParserConfig(
        enable_paddle=True,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
    )

    result = DocumentParser(config).parse(data, "batch.pdf")

    assert len(result.subdocuments) == 2
    first = [
        item
        for item in result.subdocuments[0].tree.failure_cases
        if item.code == "provider_page_error"
    ]
    assert len(first) == 1
    assert first[0].page_number == 1
    assert first[0].segment_page_number == 1


def test_segmentation_can_be_disabled_without_losing_classification() -> None:
    tree = _tree(
        [
            ["INVOICE", "Invoice Number: INV-1"],
            ["INVOICE", "Invoice Number: INV-2"],
        ]
    )
    manifest = build_batch_manifest(
        tree, tree.processing_profile, DocumentProfile.AUTO, enabled=False
    )
    assert len(manifest.subdocuments) == 1
    assert manifest.boundaries[0].reasons == ["segmentation_disabled"]


def test_boundary_override_changes_only_the_target_boundary() -> None:
    tree = _tree(
        [
            ["Unclassified first page"],
            ["INVOICE", "Invoice Number: INV-1"],
        ]
    )
    manifest = build_batch_manifest(
        tree,
        tree.processing_profile,
        DocumentProfile.AUTO,
        boundary_overrides={2: ("keep", 0.91, "luna", "same visible form")},
    )
    assert len(manifest.subdocuments) == 1
    assert manifest.boundaries[0].adjudication == "luna"
    assert manifest.boundaries[0].confidence == 0.91
