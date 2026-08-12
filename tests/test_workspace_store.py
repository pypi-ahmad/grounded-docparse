from __future__ import annotations

from grounded_docparse.batch import build_batch_documents
from grounded_docparse.models import (
    AgenticAnalysis,
    Document,
    Page,
    ParseResult,
    RunUsage,
)
from grounded_docparse.native import (
    NativeDocument,
    NativeParseResult,
    PageRoute,
    ProcessingType,
    SourceFormat,
    SourceUnit,
)
from grounded_docparse.workspace_store import WorkspaceStore


def test_completed_batch_round_trips_across_store_instances(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    document = build_batch_documents(
        [("notice.pdf", b"original-pdf", "application/pdf")]
    )[0]
    result = ParseResult(
        document=Document(
            source_name="notice.pdf",
            source_sha256="a" * 64,
            pages=[Page(number=1, width=612, height=792)],
        ),
        markdown="# Notice\n",
        json='{"schema_version":"4.4.0"}',
        input_tokens=10,
        output_tokens=2,
        annotated_pdf=b"annotated-pdf",
        usage=RunUsage(),
    )

    store = WorkspaceStore(database)
    store.sync_documents(
        [document],
        settings={"ocr_engine_label": "GLM-OCR", "refine_markdown": True},
        result_version="4.6.0",
    )
    store.save_document(
        document.id,
        status="complete",
        selection_key="parse-key",
        analysis_key="analysis-key",
        parsed_source=b"selected-pdf",
        result=result,
        analysis=AgenticAnalysis(),
    )

    restored = WorkspaceStore(database).load(result_version="4.6.0")

    assert restored is not None
    assert restored.settings["refine_markdown"] is True
    assert len(restored.documents) == 1
    item = restored.documents[0]
    assert item.document.name == "notice.pdf"
    assert item.document.source == b"original-pdf"
    assert item.status == "complete"
    assert item.selection_key == "parse-key"
    assert item.analysis_key == "analysis-key"
    assert item.parsed_source == b"selected-pdf"
    assert item.result is not None
    assert item.result.markdown == "# Notice\n"
    assert item.result.annotated_pdf == b"annotated-pdf"
    assert item.analysis == AgenticAnalysis()


def test_processing_document_reopens_interrupted_with_progress(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    document = build_batch_documents(
        [("packet.pdf", b"packet", "application/pdf")]
    )[0]
    store = WorkspaceStore(database)
    store.sync_documents([document], settings={}, result_version="4.6.0")
    store.save_progress(
        document.id,
        status="processing",
        progress={
            "stage": "recognize",
            "current": 4,
            "total": 10,
            "message": "Recognizing page 4",
        },
    )

    restored = WorkspaceStore(database).load(result_version="4.6.0")

    assert restored is not None
    item = restored.documents[0]
    assert item.status == "interrupted"
    assert item.progress == {
        "stage": "recognize",
        "current": 4,
        "total": 10,
        "message": "Recognizing page 4",
    }


def test_native_v5_result_round_trips(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    source = b"%PDF-native"
    upload = build_batch_documents(
        [("native.pdf", source, "application/pdf")]
    )[0]
    document = NativeDocument(
        source_name="native.pdf",
        source_sha256="a" * 64,
        source_format=SourceFormat.PDF,
        requested_processing_type=ProcessingType.NATIVE_PDF,
        base_text="Notice",
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
        elements=[],
    )
    result = NativeParseResult(
        document=document,
        markdown="Notice",
        json='{"schema_version":"5.0.0"}',
        annotated_pdf=b"annotated",
    )
    store = WorkspaceStore(database)
    store.sync_documents([upload], settings={}, result_version="5.0.0")
    store.save_document(
        upload.id,
        status="complete",
        selection_key="native-key",
        parsed_source=source,
        result=result,
    )

    restored = WorkspaceStore(database).load(result_version="5.0.0")

    assert restored is not None
    restored_result = restored.documents[0].result
    assert isinstance(restored_result, NativeParseResult)
    assert restored_result.document.base_text == "Notice"
    assert restored_result.annotated_pdf == b"annotated"


def test_result_version_change_keeps_source_and_invalidates_results(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    document = build_batch_documents(
        [("notice.pdf", b"original", "application/pdf")]
    )[0]
    result = ParseResult(
        document=Document(
            source_name="notice.pdf",
            source_sha256="b" * 64,
            pages=[Page(number=1, width=10, height=10)],
        ),
        markdown="old",
        json="{}",
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"old",
    )
    store = WorkspaceStore(database)
    store.sync_documents([document], settings={}, result_version="4.6.0")
    store.save_document(
        document.id,
        status="complete",
        selection_key="old-parse",
        analysis_key="old-analysis",
        parsed_source=b"selected",
        result=result,
        analysis=AgenticAnalysis(),
    )

    restored = store.load(result_version="5.0.0")

    assert restored is not None
    item = restored.documents[0]
    assert item.document.source == b"original"
    assert item.status == "pending"
    assert item.result is None
    assert item.analysis is None
    assert item.parsed_source is None
    assert item.selection_key is None
    assert item.analysis_key is None


def test_workspace_settings_usage_and_clear_are_durable(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    document = build_batch_documents([("notice.pdf", b"source", "application/pdf")])[0]
    store = WorkspaceStore(database)
    store.sync_documents([document], settings={"ade_mode": "Fast"}, result_version="4.6.0")
    store.save_workspace(
        settings={"ade_mode": "Accurate"},
        usage=RunUsage(),
    )

    restored = WorkspaceStore(database).load(result_version="4.6.0")
    assert restored is not None
    assert restored.settings == {"ade_mode": "Accurate"}

    store.clear()

    assert WorkspaceStore(database).load(result_version="4.6.0") is None


def test_corrupt_result_isolated_as_document_failure(tmp_path) -> None:
    database = tmp_path / "studio.sqlite3"
    document = build_batch_documents([("notice.pdf", b"source", "application/pdf")])[0]
    result = ParseResult(
        document=Document(
            source_name="notice.pdf",
            source_sha256="c" * 64,
            pages=[Page(number=1, width=10, height=10)],
        ),
        markdown="notice",
        json="{}",
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"annotated",
    )
    store = WorkspaceStore(database)
    store.sync_documents([document], settings={}, result_version="4.6.0")
    store.save_document(
        document.id,
        status="complete",
        selection_key="parse",
        analysis_key="analysis",
        parsed_source=b"parsed",
        result=result,
        analysis=AgenticAnalysis(),
    )
    next((tmp_path / "workspaces").rglob("annotated.pdf")).unlink()

    restored = store.load(result_version="4.6.0")

    assert restored is not None
    item = restored.documents[0]
    assert item.status == "failed"
    assert item.error == "Saved parse result is corrupt or incomplete"
    assert item.document.source == b"source"
    assert item.result is None
