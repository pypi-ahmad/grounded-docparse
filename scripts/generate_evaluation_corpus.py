from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

MANIFEST_SCHEMA_VERSION = "1.0"
ANNOTATION_SCHEMA_VERSION = "1.1"


def _save_pdf(path: Path, pages: list[list[tuple[float, float, str]]]) -> None:
    document = pymupdf.open()
    for page_items in pages:
        page = document.new_page(width=612, height=792)
        for x, y, text in page_items:
            page.insert_text((x, y), text, fontsize=11)
    document.set_metadata(
        {
            "title": f"Synthetic evaluation fixture: {path.stem}",
            "author": "Grounded DocParse test generator",
            "subject": "Public synthetic evaluation data",
            "keywords": "synthetic, evaluation",
        }
    )
    document.save(path)
    document.close()


def _save_degraded_scan(path: Path) -> None:
    image = Image.new("L", (1224, 1584), "white")
    draw = ImageDraw.Draw(image)
    draw.text((90, 100), "SYNTHETIC DEGRADED SCAN - PUBLIC TEST DATA", fill="black")
    draw.text((90, 180), "Batch ID: SCAN-042", fill="black")
    draw.text((90, 250), "Status: archived for evaluation only", fill="black")
    image = image.rotate(0.9, fillcolor="white")
    image = image.filter(ImageFilter.GaussianBlur(0.7))
    image = ImageEnhance.Contrast(image).enhance(0.68)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=45)
    degraded = Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
    degraded.save(path, "PDF", resolution=144)


def _annotation(
    document_id: str,
    reference_text: str | None,
    *,
    reference_basis: str = "synthetic_exact",
    **values: Any,
) -> dict[str, Any]:
    return {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "document_id": document_id,
        "reference_text": reference_text,
        "reference_basis": reference_basis,
        "reference_pages": {},
        "anchors": values.pop("anchors", []),
        "tables": values.pop("tables", []),
        "grounding_regions": values.pop("grounding_regions", {}),
        "schema_output": values.pop("schema_output", None),
        "continuity_pairs": values.pop("continuity_pairs", []),
        "forbidden_literals": values.pop("forbidden_literals", []),
        "rejected_block_ids": values.pop("rejected_block_ids", []),
        **values,
    }


def _write_schemas(schema_dir: Path) -> None:
    schema_dir.mkdir(parents=True, exist_ok=True)
    manifest_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "manifest-v1.schema.json",
        "title": "Grounded DocParse evaluation corpus manifest v1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "annotation_schema_version",
            "corpus_id",
            "documents",
        ],
        "properties": {
            "schema_version": {"const": MANIFEST_SCHEMA_VERSION},
            "annotation_schema_version": {"const": ANNOTATION_SCHEMA_VERSION},
            "corpus_id": {"type": "string", "minLength": 1},
            "documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "source", "features", "synthetic"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "source": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["kind", "path"],
                            "properties": {
                                "kind": {"enum": ["local", "external"]},
                                "path": {"type": "string", "minLength": 1},
                                "sha256": {
                                    "type": ["string", "null"],
                                    "pattern": "^[0-9a-f]{64}$",
                                },
                            },
                        },
                        "annotation_path": {"type": ["string", "null"]},
                        "legacy_expectations_path": {"type": ["string", "null"]},
                        "features": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "synthetic": {"type": "boolean"},
                    },
                },
            },
        },
    }
    annotation_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "annotation-v1.1.schema.json",
        "title": "Grounded DocParse evaluation annotation v1.1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "document_id"],
        "properties": {
            "schema_version": {"const": ANNOTATION_SCHEMA_VERSION},
            "document_id": {"type": "string", "minLength": 1},
            "reference_text": {"type": ["string", "null"]},
            "reference_basis": {
                "enum": [
                    "source_verified",
                    "synthetic_exact",
                    "generated",
                    "legacy",
                ]
            },
            "reference_pages": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "anchors": {"type": "array"},
            "tables": {"type": "array"},
            "grounding_regions": {"type": "object"},
            "schema_output": {"type": ["object", "null"]},
            "continuity_pairs": {"type": "array"},
            "forbidden_literals": {"type": "array"},
            "rejected_block_ids": {"type": "array"},
        },
    }
    (schema_dir / "manifest-v1.schema.json").write_text(
        json.dumps(manifest_schema, indent=2) + "\n", encoding="utf-8"
    )
    (schema_dir / "annotation-v1.1.schema.json").write_text(
        json.dumps(annotation_schema, indent=2) + "\n", encoding="utf-8"
    )


def generate_corpus(repository_root: Path) -> Path:
    root = repository_root.resolve()
    output = root / "benchmarks" / "corpus-v1"
    documents_dir = output / "documents"
    annotations_dir = output / "annotations"
    documents_dir.mkdir(parents=True, exist_ok=True)
    annotations_dir.mkdir(parents=True, exist_ok=True)

    fixtures: dict[str, dict[str, Any]] = {
        "native-text": {
            "pages": [[(54, 72, "Synthetic Native Text Fixture"), (54, 110, "Record NATIVE-001 is public test data."), (54, 135, "Status: complete")]],
            "features": ["native_text"],
            "annotation": _annotation(
                "native-text",
                "Synthetic Native Text Fixture Record NATIVE-001 is public test data. Status: complete",
                anchors=[
                    {"id": "native-title", "text": "Synthetic Native Text Fixture"},
                    {"id": "native-status", "text": "Status: complete"},
                ],
            ),
        },
        "unicode-identifiers": {
            "pages": [[(54, 72, "Unicode Identifier Register"), (54, 110, "Cafe-\u00c542"), (54, 135, "Resume-\u00c974"), (54, 160, "Naive-\u00dc18")]],
            "features": ["unicode_identifiers"],
            "annotation": _annotation(
                "unicode-identifiers",
                "Unicode Identifier Register Cafe-\u00c542 Resume-\u00c974 Naive-\u00dc18",
                forbidden_literals=["Cafe-A42"],
            ),
        },
        "multi-column": {
            "pages": [[(54, 72, "Two Column Bulletin"), (54, 120, "LEFT-1 Alpha"), (54, 150, "LEFT-2 Beta"), (330, 120, "RIGHT-1 Gamma"), (330, 150, "RIGHT-2 Delta")]],
            "features": ["multi_column", "reading_order"],
            "annotation": _annotation(
                "multi-column",
                "Two Column Bulletin LEFT-1 Alpha LEFT-2 Beta RIGHT-1 Gamma RIGHT-2 Delta",
                anchors=[
                    {"id": "column-title", "text": "Two Column Bulletin"},
                    {"id": "left-1", "text": "LEFT-1 Alpha"},
                    {"id": "left-2", "text": "LEFT-2 Beta"},
                    {"id": "right-1", "text": "RIGHT-1 Gamma"},
                    {"id": "right-2", "text": "RIGHT-2 Delta"},
                ],
            ),
        },
        "lists": {
            "pages": [[(54, 72, "Synthetic Checklist"), (72, 115, "1. Open the public fixture"), (72, 145, "2. Review the sample"), (72, 175, "3. Record the result")]],
            "features": ["lists"],
            "annotation": _annotation(
                "lists",
                "Synthetic Checklist 1. Open the public fixture 2. Review the sample 3. Record the result",
            ),
        },
        "tables": {
            "pages": [[(54, 72, "Synthetic Inventory Table"), (54, 120, "Item"), (250, 120, "Count"), (54, 150, "Widgets"), (250, 150, "12"), (54, 180, "Gadgets"), (250, 180, "7")]],
            "features": ["tables"],
            "annotation": _annotation(
                "tables",
                "Synthetic Inventory Table Item Count Widgets 12 Gadgets 7",
                tables=[
                    {
                        "page": 1,
                        "ordinal": 0,
                        "cells": [
                            {"row": 0, "column": 0, "text": "Item"},
                            {"row": 0, "column": 1, "text": "Count"},
                            {"row": 1, "column": 0, "text": "Widgets"},
                            {"row": 1, "column": 1, "text": "12"},
                            {"row": 2, "column": 0, "text": "Gadgets"},
                            {"row": 2, "column": 1, "text": "7"},
                        ],
                    }
                ],
            ),
        },
        "cross-page-table": {
            "pages": [
                [(54, 72, "Quarterly Table - Part 1"), (54, 120, "Quarter"), (250, 120, "Units"), (54, 150, "Q1"), (250, 150, "10")],
                [(54, 72, "Quarterly Table - Continued"), (54, 120, "Q2"), (250, 120, "14"), (54, 150, "Q3"), (250, 150, "16")],
            ],
            "features": ["tables", "cross_page_continuity"],
            "annotation": _annotation(
                "cross-page-table",
                "Quarterly Table - Part 1 Quarter Units Q1 10 Quarterly Table - Continued Q2 14 Q3 16",
                tables=[
                    {"page": 1, "ordinal": 0, "cells": [{"row": 0, "column": 0, "text": "Quarter"}, {"row": 0, "column": 1, "text": "Units"}, {"row": 1, "column": 0, "text": "Q1"}, {"row": 1, "column": 1, "text": "10"}]},
                    {"page": 2, "ordinal": 0, "cells": [{"row": 2, "column": 0, "text": "Q2"}, {"row": 2, "column": 1, "text": "14"}, {"row": 3, "column": 0, "text": "Q3"}, {"row": 3, "column": 1, "text": "16"}]},
                ],
                continuity_pairs=[["page-1-table-0", "page-2-table-0"]],
            ),
        },
        "form": {
            "pages": [[(54, 72, "Synthetic Intake Form"), (54, 120, "Record ID: FORM-204"), (54, 150, "Category: Public fixture"), (54, 180, "Approved: Yes")]],
            "features": ["forms", "schema_fields"],
            "annotation": _annotation(
                "form",
                "Synthetic Intake Form Record ID: FORM-204 Category: Public fixture Approved: Yes",
                schema_output={"record_id": "FORM-204", "category": "Public fixture", "approved": True},
            ),
        },
        "checkboxes": {
            "pages": [[(54, 72, "Synthetic Options"), (54, 120, "[x] Alpha option"), (54, 150, "[ ] Beta option"), (54, 180, "[x] Gamma option")]],
            "features": ["checkboxes", "rejection"],
            "annotation": _annotation(
                "checkboxes",
                "Synthetic Options [x] Alpha option [ ] Beta option [x] Gamma option",
                rejected_block_ids=["checkbox-noise"],
            ),
        },
        "figure-chart": {
            "pages": [[(54, 72, "Synthetic Bar Chart"), (54, 120, "Units by period"), (54, 160, "P1: 4"), (54, 190, "P2: 7"), (54, 220, "P3: 5")]],
            "features": ["figures", "charts", "grounding"],
            "annotation": _annotation(
                "figure-chart",
                "Synthetic Bar Chart Units by period P1: 4 P2: 7 P3: 5",
                grounding_regions={"chart-1": [0.08, 0.12, 0.72, 0.42]},
            ),
        },
    }

    for document_id, fixture in fixtures.items():
        path = documents_dir / f"{document_id}.pdf"
        _save_pdf(path, fixture["pages"])
    scan_id = "degraded-scan"
    _save_degraded_scan(documents_dir / f"{scan_id}.pdf")
    fixtures[scan_id] = {
        "features": ["degraded_scan", "ocr_required"],
        "annotation": _annotation(
            scan_id,
            "SYNTHETIC DEGRADED SCAN - PUBLIC TEST DATA Batch ID: SCAN-042 Status: archived for evaluation only",
        ),
    }

    existing = {
        "synthetic-report": {
            "path": root / "examples" / "synthetic-report.pdf",
            "features": ["native_text", "tables"],
            "annotation": _annotation(
                "synthetic-report",
                "Synthetic Clinical Operations Report 1. Summary This synthetic document contains no patient information. It exists only to exercise document parsing and reading-order behavior. Metric January February Reviewed forms 128 141 Average pages 4.2 4.5",
            ),
        },
        "synthetic-medical-fax": {
            "path": root / "examples" / "synthetic-medical-fax.pdf",
            "features": ["degraded_scan", "ocr_required"],
            "annotation": _annotation(
                "synthetic-medical-fax",
                "SYNTHETIC MEDICAL FAX - NO PHI FAX DATE: 2026-07-24 PAGES: 1 DOCUMENT TYPE: Referral test fixture Priority: Routine Requested service: Imaging review Clinical note: Synthetic text created for OCR evaluation. Medication list: None supplied Signature: [synthetic mark]",
            ),
        },
    }
    for document_id, fixture in {**fixtures, **existing}.items():
        annotation_path = annotations_dir / f"{document_id}.json"
        annotation_path.write_text(
            json.dumps(fixture["annotation"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    entries: list[dict[str, Any]] = []
    for document_id, fixture in fixtures.items():
        source_path = documents_dir / f"{document_id}.pdf"
        entries.append(
            {
                "id": document_id,
                "source": {
                    "kind": "local",
                    "path": source_path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                },
                "annotation_path": (annotations_dir / f"{document_id}.json")
                .relative_to(root)
                .as_posix(),
                "features": fixture["features"],
                "synthetic": True,
            }
        )
    for document_id, fixture in existing.items():
        source_path = fixture["path"]
        if not source_path.is_file():
            raise FileNotFoundError(f"required existing fixture is missing: {source_path}")
        entries.append(
            {
                "id": document_id,
                "source": {
                    "kind": "local",
                    "path": source_path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                },
                "annotation_path": (annotations_dir / f"{document_id}.json")
                .relative_to(root)
                .as_posix(),
                "features": fixture["features"],
                "synthetic": True,
            }
        )
    public_water_expectations = (
        root / "tests" / "fixtures" / "public_water_expectations.json"
    )
    if not public_water_expectations.is_file():
        raise FileNotFoundError(
            f"required Public Water expectations are missing: {public_water_expectations}"
        )
    expectations = json.loads(public_water_expectations.read_text(encoding="utf-8"))
    public_water_annotation = _annotation(
        "public-water-mass-mailing",
        None,
        reference_basis="source_verified",
        anchors=[
            {
                "id": f"p{page_number}-{index:02d}",
                "text": text,
            }
            for page_number in (4, 5, 6)
            for index, text in enumerate(
                expectations.get("required_by_page", {}).get(str(page_number), []), 1
            )
        ],
    )
    public_water_annotation_path = (
        annotations_dir / "public-water-mass-mailing.json"
    )
    public_water_annotation_path.write_text(
        json.dumps(public_water_annotation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    entries.append(
        {
            "id": "public-water-mass-mailing",
            "source": {"kind": "external", "path": "PublicWaterMassMailing.pdf"},
            "legacy_expectations_path": public_water_expectations.relative_to(root).as_posix(),
            "annotation_path": public_water_annotation_path.relative_to(root).as_posix(),
            "features": ["external_live_regression", "legacy_public_water"],
            "synthetic": False,
        }
    )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "annotation_schema_version": ANNOTATION_SCHEMA_VERSION,
        "corpus_id": "grounded-docparse-synthetic-v1",
        "documents": entries,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_schemas(root / "benchmarks" / "schemas")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the public Phase 1 evaluation corpus"
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    manifest = generate_corpus(args.repository_root)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
