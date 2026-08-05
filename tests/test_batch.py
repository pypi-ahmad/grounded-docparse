from __future__ import annotations

import io
import json
import zipfile

import pytest

from grounded_docparse.batch import (
    MAX_BATCH_BYTES,
    MAX_BATCH_FILES,
    BatchArchiveEntry,
    build_batch_documents,
    build_output_archive,
)


def test_batch_documents_are_stable_and_preserve_duplicate_uploads() -> None:
    documents = build_batch_documents(
        [
            ("notice.pdf", b"first", "application/pdf"),
            ("notice.pdf", b"second", "application/pdf"),
            ("notice.pdf", b"first", "application/pdf"),
        ]
    )

    assert [item.display_name for item in documents] == [
        "notice.pdf (1)",
        "notice.pdf (2)",
        "notice.pdf (3)",
    ]
    assert len({item.id for item in documents}) == 3
    assert documents[0].id.endswith(":1")
    assert documents[2].id.endswith(":2")


def test_batch_upload_limits_are_enforced() -> None:
    with pytest.raises(ValueError, match=f"at most {MAX_BATCH_FILES}"):
        build_batch_documents(
            [(f"{index}.pdf", b"x", "application/pdf") for index in range(21)]
        )

    with pytest.raises(ValueError, match="1 GB"):
        build_batch_documents(
            [("large.pdf", b"x", "application/pdf")],
            total_size=MAX_BATCH_BYTES + 1,
        )


def test_output_archive_contains_originals_outputs_and_failure_manifest() -> None:
    archive = build_output_archive(
        [
            BatchArchiveEntry(
                name="../notice.pdf",
                source=b"original",
                status="complete",
                markdown="# Notice\n",
                annotated_pdf=b"annotated",
                full_json='{"document": {}}',
                extraction_json='{"member_id": "123"}',
            ),
            BatchArchiveEntry(
                name="failed.pdf",
                source=b"failed-original",
                status="failed",
                error="OCR unavailable",
            ),
        ]
    )

    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = set(bundle.namelist())
        assert "manifest.json" in names
        assert "01-notice/original/notice.pdf" in names
        assert "01-notice/notice.md" in names
        assert "01-notice/notice.annotated.pdf" in names
        assert "01-notice/notice.full.json" in names
        assert "01-notice/notice.extract.json" in names
        assert "02-failed/original/failed.pdf" in names
        assert all(".." not in name for name in names)
        manifest = json.loads(bundle.read("manifest.json"))

    assert manifest["version"] == 1
    assert [item["status"] for item in manifest["documents"]] == [
        "complete",
        "failed",
    ]
    assert manifest["documents"][1]["error"] == "OCR unavailable"
