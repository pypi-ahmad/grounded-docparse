from __future__ import annotations

import io
import json
import zipfile

import pymupdf
import pytest

from grounded_docparse.batch import (
    MAX_BATCH_BYTES,
    MAX_BATCH_FILES,
    BatchArchiveEntry,
    build_batch_documents,
    build_output_archive,
    build_split_archive,
)
from grounded_docparse.models import (
    Block,
    ClassifierCategory,
    ClassifierProfile,
    Document,
    FormClassificationResult,
    FormSegment,
    Page,
    ParseResult,
    VerificationState,
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


def test_split_archive_exports_each_approved_segment() -> None:
    with pymupdf.open() as source_document:
        for _ in range(3):
            source_document.new_page(width=100, height=100)
        source = source_document.tobytes()
    document = Document(
        source_name="packet.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=number,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id=f"p{number}-form",
                        type="paragraph",
                        text=text,
                        reading_order=0,
                        verification=VerificationState.VERIFIED,
                    )
                ],
            )
            for number, text in (
                (1, "First request"),
                (2, "Medical records"),
                (3, "Second request"),
            )
        ],
    )
    result = ParseResult(
        document=document,
        markdown="",
        json="{}",
        input_tokens=0,
        output_tokens=0,
        annotated_pdf=b"",
    )
    profile = ClassifierProfile(
        name="Routing",
        categories=[
            ClassifierCategory(
                key="newauth",
                description="New request",
                extract=True,
                schema_name="Authorization",
            ),
            ClassifierCategory(key="records", description="Medical records"),
        ],
    )
    categories = ["newauth", "records", "newauth"]
    classification = FormClassificationResult(
        profile=profile,
        profile_fingerprint="fingerprint",
        segments=[
            FormSegment(
                id=f"form-{index:03d}",
                predicted_start_page=index,
                predicted_end_page=index,
                predicted_category=category,
                start_page=index,
                end_page=index,
                category=category,
                confidence=0.95,
                approved=True,
                review_status="auto_approved",
                eligible=category == "newauth",
                schema_name="Authorization" if category == "newauth" else None,
            )
            for index, category in enumerate(categories, start=1)
        ],
    )

    archive = build_split_archive(source, "packet.pdf", result, classification)

    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = set(bundle.namelist())
        expected_stem = "001-form-001-newauth-pages-001-001"
        assert f"{expected_stem}.pdf" in names
        assert f"{expected_stem}.md" in names
        assert f"{expected_stem}.json" in names
        assert len([name for name in names if name.endswith(".pdf")]) == 3
        assert len([name for name in names if name.endswith(".md")]) == 3
        assert len([name for name in names if name.endswith(".json")]) == 4
        with pymupdf.open(stream=bundle.read(f"{expected_stem}.pdf"), filetype="pdf") as pdf:
            assert pdf.page_count == 1
        assert "First request" in bundle.read(f"{expected_stem}.md").decode()
        segment_json = json.loads(bundle.read(f"{expected_stem}.json"))
        assert segment_json["document"]["pages"][0]["number"] == 1
        manifest = json.loads(bundle.read("manifest.json"))

    assert manifest["version"] == 1
    assert manifest["source"]["name"] == "packet.pdf"
    assert [item["segment"]["category"] for item in manifest["segments"]] == categories
    assert manifest["segments"][1]["segment"]["eligible"] is False

    unapproved = classification.model_copy(deep=True)
    unapproved.segments[0].approved = False
    with pytest.raises(ValueError, match="approved"):
        build_split_archive(source, "packet.pdf", result, unapproved)

    incomplete = classification.model_copy(deep=True)
    incomplete.segments = incomplete.segments[:-1]
    with pytest.raises(ValueError, match="cover every parsed page exactly once"):
        build_split_archive(source, "packet.pdf", result, incomplete)
