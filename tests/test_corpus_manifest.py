from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from pydantic import ValidationError

from grounded_docparse.benchmark import ReferenceBasis, load_corpus_manifest


def _write_annotation(path: Path, *, document_id: str, version: str = "1.1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": version,
                "document_id": document_id,
                "reference_text": "Alpha beta",
                "anchors": [
                    {"id": "alpha", "text": "Alpha"},
                    {"id": "beta", "text": "beta"},
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_manifest(
    root: Path,
    *,
    documents: list[dict[str, object]] | None = None,
) -> Path:
    source = root / "documents" / "sample.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF- synthetic fixture")
    annotation = root / "annotations" / "sample.json"
    _write_annotation(annotation, document_id="sample")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "annotation_schema_version": "1.1",
                "corpus_id": "test-corpus-v1",
                "documents": documents
                or [
                    {
                        "id": "sample",
                        "source": {
                            "kind": "local",
                            "path": "documents/sample.pdf",
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        },
                        "annotation_path": "annotations/sample.json",
                        "features": ["native_text"],
                        "synthetic": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_load_manifest_validates_local_sources_and_annotations(tmp_path: Path) -> None:
    manifest = load_corpus_manifest(_write_manifest(tmp_path), repository_root=tmp_path)

    assert manifest.corpus_id == "test-corpus-v1"
    assert manifest.documents[0].annotation.document_id == "sample"
    assert manifest.documents[0].source_path == tmp_path / "documents" / "sample.pdf"


def test_load_manifest_accepts_reference_provenance(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["annotation_schema_version"] = "1.1"
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    annotation_path = tmp_path / "annotations" / "sample.json"
    annotation_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    annotation_payload.update(
        {
            "schema_version": "1.1",
            "reference_basis": "source_verified",
            "reference_pages": {"1": "Alpha beta"},
        }
    )
    annotation_path.write_text(json.dumps(annotation_payload), encoding="utf-8")

    manifest = load_corpus_manifest(manifest_path, repository_root=tmp_path)

    annotation = manifest.documents[0].annotation
    assert annotation is not None
    assert annotation.reference_basis is ReferenceBasis.SOURCE_VERIFIED
    assert annotation.reference_pages == {1: "Alpha beta"}


def test_load_manifest_accepts_expected_document_type(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.1"
    payload["documents"][0]["expected_document_type"] = "Invoice"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    manifest = load_corpus_manifest(manifest_path, repository_root=tmp_path)

    assert manifest.documents[0].expected_document_type == "Invoice"


def test_load_manifest_rejects_unknown_expected_document_type(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.1"
    payload["documents"][0]["expected_document_type"] = "Receipt"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="expected_document_type"):
        load_corpus_manifest(manifest_path, repository_root=tmp_path)


def test_load_manifest_v1_rejects_document_type_label(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["documents"][0]["expected_document_type"] = "Invoice"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="requires manifest schema version 1.1"):
        load_corpus_manifest(manifest_path, repository_root=tmp_path)


def test_load_manifest_rejects_duplicate_document_ids(tmp_path: Path) -> None:
    source = tmp_path / "documents" / "sample.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF- duplicate fixture")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    _write_annotation(tmp_path / "annotations" / "sample.json", document_id="sample")
    entry = {
        "id": "sample",
        "source": {
            "kind": "local",
            "path": "documents/sample.pdf",
            "sha256": digest,
        },
        "annotation_path": "annotations/sample.json",
        "features": [],
        "synthetic": True,
    }

    with pytest.raises(ValidationError, match="duplicate document id"):
        load_corpus_manifest(
            _write_manifest(tmp_path, documents=[entry, entry]),
            repository_root=tmp_path,
        )


def test_load_manifest_rejects_unsupported_manifest_annotation_schema_version(
    tmp_path: Path,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["annotation_schema_version"] = "999.0"
    payload["documents"] = []
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="unsupported annotation schema version"):
        load_corpus_manifest(manifest_path, repository_root=tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "does not exist"),
        ("checksum", "checksum"),
        ("traversal", "repository path traversal"),
        ("annotation_version", "annotation schema version"),
    ],
)
def test_load_manifest_rejects_unsafe_or_inconsistent_files(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = payload["documents"][0]
    if mutation == "missing":
        entry["source"]["path"] = "documents/missing.pdf"
    elif mutation == "checksum":
        entry["source"]["sha256"] = "0" * 64
    elif mutation == "traversal":
        entry["source"]["path"] = "../outside.pdf"
    else:
        _write_annotation(
            tmp_path / "annotations" / "sample.json",
            document_id="sample",
            version="2.0",
        )
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises((ValueError, ValidationError), match=message):
        load_corpus_manifest(manifest_path, repository_root=tmp_path)


def test_load_manifest_rejects_duplicate_annotation_anchor_ids(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    annotation_path = tmp_path / "annotations" / "sample.json"
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    payload["anchors"][1]["id"] = "alpha"
    annotation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="duplicate anchor id"):
        load_corpus_manifest(manifest_path, repository_root=tmp_path)


def test_generator_builds_twelve_local_documents_and_external_public_water(
    tmp_path: Path,
) -> None:
    examples = tmp_path / "examples"
    examples.mkdir()
    for filename in ("synthetic-report.pdf", "synthetic-medical-fax.pdf"):
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), f"Synthetic fixture {filename}")
        document.save(examples / filename)
        document.close()
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_evaluation_corpus.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--repository-root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    manifest_path = tmp_path / "benchmarks" / "corpus-v1" / "manifest.json"
    manifest = load_corpus_manifest(manifest_path, repository_root=tmp_path)

    local_documents = [
        document for document in manifest.documents if document.source.kind == "local"
    ]
    assert len(manifest.documents) == 13
    assert len(local_documents) == 12
    assert len(list((manifest_path.parent / "documents").glob("*.pdf"))) == 10
    assert len(list((manifest_path.parent / "annotations").glob("*.json"))) == 13
    assert manifest.documents[-1].id == "public-water-mass-mailing"
    assert manifest.documents[-1].source.kind == "external"
    assert manifest.documents[-1].annotation.reference_basis is ReferenceBasis.SOURCE_VERIFIED
