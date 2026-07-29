from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pymupdf

from grounded_docparse.benchmark import (
    ReferenceBasis,
    build_live_report,
    evaluate_live_document,
    live_telemetry_record,
    load_corpus_manifest,
)
from grounded_docparse.extraction import DocumentExtractor
from grounded_docparse.pipeline import DocumentParser


def _path_mappings(values: list[str], *, option: str) -> dict[str, Path]:
    mappings: dict[str, Path] = {}
    for value in values:
        document_id, separator, path = value.partition("=")
        if not separator or not document_id or not path:
            raise ValueError(f"{option} requires DOCUMENT_ID=PATH")
        mappings[document_id] = Path(path)
    return mappings


def _reference_basis_mappings(values: list[str]) -> dict[str, ReferenceBasis]:
    mappings: dict[str, ReferenceBasis] = {}
    for value in values:
        document_id, separator, basis = value.partition("=")
        if not separator or not document_id or not basis:
            raise ValueError("--reference-basis requires DOCUMENT_ID=BASIS")
        mappings[document_id] = ReferenceBasis(basis)
    return mappings


def _page_subset_mappings(values: list[str]) -> dict[str, list[int]]:
    mappings: dict[str, list[int]] = {}
    for value in values:
        document_id, separator, page_list = value.partition("=")
        if not separator or not document_id or not page_list:
            raise ValueError("--page-subset requires DOCUMENT_ID=PAGE[,PAGE...]")
        pages = [int(page) for page in page_list.split(",")]
        if any(page < 1 for page in pages) or len(pages) != len(set(pages)):
            raise ValueError("page subsets require unique positive page numbers")
        mappings[document_id] = sorted(pages)
    return mappings


def _subset_pdf(data: bytes, pages: list[int]) -> bytes:
    source = pymupdf.open(stream=data, filetype="pdf")
    try:
        if any(page > source.page_count for page in pages):
            raise ValueError("page subset exceeds source page count")
        subset = pymupdf.open()
        try:
            for page in pages:
                subset.insert_pdf(source, from_page=page - 1, to_page=page - 1)
            return subset.tobytes()
        finally:
            subset.close()
    finally:
        source.close()


def _subset_reference(reference: str, pages: list[int]) -> str:
    reference_pages = reference.split("<!-- PAGE BREAK -->")
    if any(page > len(reference_pages) for page in pages):
        raise ValueError("page subset exceeds reference page count")
    return "<!-- PAGE BREAK -->".join(reference_pages[page - 1] for page in pages)


def _schema_node(value: Any, *, root: bool = False) -> dict[str, Any]:
    if isinstance(value, dict):
        properties = {
            name: _schema_node(child)
            for name, child in value.items()
        }
        return {
            "type": "object" if root else ["object", "null"],
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        item = value[0] if value else ""
        return {"type": ["array", "null"], "items": _schema_node(item)}
    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, int):
        kind = "integer"
    elif isinstance(value, float):
        kind = "number"
    else:
        kind = "string"
    return {"type": [kind, "null"]}


def _live_report(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    manifest = load_corpus_manifest(
        args.manifest, repository_root=args.repository_root.resolve()
    )
    external_sources = _path_mappings(args.external_source, option="--external-source")
    references = _path_mappings(args.reference, option="--reference")
    reference_bases = _reference_basis_mappings(args.reference_basis)
    page_subsets = _page_subset_mappings(args.page_subset)
    selected = set(args.document)
    documents: list[dict[str, Any]] = []
    had_error = False
    for corpus_document in manifest.documents:
        if selected and corpus_document.id not in selected:
            continue
        source_path = corpus_document.source_path or external_sources.get(corpus_document.id)
        if source_path is None:
            documents.append(
                {
                    "id": corpus_document.id,
                    "features": corpus_document.features,
                    "pages": 0,
                    "status": "source_unavailable",
                    "metrics": {},
                    "telemetry": {
                        "latency_seconds": 0.0,
                        "pages": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "full_page_fallbacks": 0,
                        "model_usage": {},
                        "retries": 0,
                        "rate_limit_events": 0,
                    },
                }
            )
            continue
        print(f"Evaluating {corpus_document.id}", flush=True)
        started = time.perf_counter()
        try:
            source_data = source_path.read_bytes()
            source_pages = page_subsets.get(corpus_document.id)
            parse_data = (
                _subset_pdf(source_data, source_pages)
                if source_pages is not None
                else source_data
            )
            parse_name = (
                f"{source_path.stem}.pages-{'-'.join(map(str, source_pages))}.pdf"
                if source_pages is not None
                else source_path.name
            )
            parse_result = DocumentParser().parse(
                parse_data, parse_name
            )
            extraction_result = None
            if (
                corpus_document.annotation is not None
                and corpus_document.annotation.schema_output is not None
            ):
                extraction_result = DocumentExtractor().extract(
                    parse_result,
                    _schema_node(corpus_document.annotation.schema_output, root=True),
                )
            telemetry = live_telemetry_record(
                parse_result,
                extraction_result=extraction_result,
                latency_seconds=time.perf_counter() - started,
            )
            reference_path = references.get(corpus_document.id)
            reference_text = (
                reference_path.read_text(encoding="utf-8")
                if reference_path is not None
                else None
            )
            if reference_text is not None and source_pages is not None:
                reference_text = _subset_reference(reference_text, source_pages)
            record = evaluate_live_document(
                corpus_document,
                parse_result.document,
                telemetry=telemetry,
                extraction_data=extraction_result.data if extraction_result else None,
                reference_text=reference_text,
                reference_is_markdown=bool(
                    reference_path is not None and reference_path.suffix.casefold() == ".md"
                ),
                reference_basis=reference_bases.get(corpus_document.id),
                source_page_numbers=source_pages,
            )
            record["status"] = "evaluated"
            if source_pages is not None:
                record["source_page_numbers"] = source_pages
            documents.append(record)
        except Exception as exc:  # noqa: BLE001 - corpus reports isolated failures
            had_error = True
            documents.append(
                {
                    "id": corpus_document.id,
                    "features": corpus_document.features,
                    "pages": 0,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "metrics": {},
                    "telemetry": {
                        "latency_seconds": time.perf_counter() - started,
                        "pages": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "full_page_fallbacks": 0,
                        "model_usage": {},
                        "retries": 0,
                        "rate_limit_events": 0,
                    },
                }
            )
    rate_card = (
        json.loads(args.rate_card.read_text(encoding="utf-8"))
        if args.rate_card is not None
        else None
    )
    return (
        build_live_report(
            corpus_id=manifest.corpus_id,
            documents=documents,
            rate_card=rate_card,
        ),
        had_error,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a corpus with existing offline native ingest evidence"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/corpus-v1/manifest.json"),
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--output",
        type=Path,
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--document", action="append", default=[])
    parser.add_argument("--external-source", action="append", default=[])
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument(
        "--page-subset",
        action="append",
        default=[],
        help="DOCUMENT_ID=PAGE[,PAGE...] for targeted live experiments",
    )
    parser.add_argument(
        "--reference-basis",
        action="append",
        default=[],
        help=(
            "DOCUMENT_ID=source_verified|synthetic_exact|generated; "
            "external references default to generated"
        ),
    )
    parser.add_argument("--rate-card", type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error("visual-only evaluation requires --live")
    report, had_error = _live_report(args)
    output = args.output or Path("output/evaluation-corpus-live.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(output)
    return int(had_error)


if __name__ == "__main__":
    raise SystemExit(main())
