from __future__ import annotations

import io
import json
import zipfile

import pymupdf

from grounded_docparse import DocumentParser, ParserConfig
from grounded_docparse.review import (
    build_batch_bundle,
    build_quality_report,
    render_annotated_page,
    render_annotated_pdf,
)


def _config() -> ParserConfig:
    return ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
    )


def test_quality_report_is_page_grounded(simple_pdf: bytes) -> None:
    result = DocumentParser(_config()).parse(simple_pdf, "test.pdf")
    report = build_quality_report(result.tree)
    assert report.document_id == result.tree.document_id
    assert report.summary["ocr_coverage"] == 1
    assert report.summary["unresolved_count"] == 0
    assert report.pages[0]["page_number"] == 1
    assert report.pages[0]["provider_candidates"]["digital"] >= 1


def test_annotated_pdf_and_page_preview(simple_pdf: bytes) -> None:
    result = DocumentParser(_config()).parse(simple_pdf, "test.pdf")
    annotated = render_annotated_pdf(simple_pdf, "test.pdf", result.tree)
    with pymupdf.open(stream=annotated, filetype="pdf") as document:
        assert document.page_count == 1
        assert len(document[0].get_drawings()) >= 1
    preview = render_annotated_page(annotated, 1)
    assert preview.startswith(b"\x89PNG")


def test_batch_bundle_is_prefixed_and_records_failures(simple_pdf: bytes) -> None:
    result = DocumentParser(_config()).parse(simple_pdf, "same.pdf")
    bundle = build_batch_bundle(
        [("same.pdf", result, None), ("same.pdf", None, "ValueError")]
    )
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = archive.namelist()
        assert "batch.manifest.json" in names
        assert any(name.startswith("documents/0001-same/") for name in names)
        manifest = json.loads(archive.read("batch.manifest.json"))
    assert manifest["documents"][0]["status"] == "complete"
    assert manifest["documents"][1]["error_code"] == "ValueError"
