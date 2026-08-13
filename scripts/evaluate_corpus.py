from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pymupdf

from grounded_docparse.agentic import DocumentAgent
from grounded_docparse.benchmark import (
    ReferenceBasis,
    build_live_report,
    evaluate_live_document,
    evaluate_regression_policy,
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


def _unit_interval(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
    return parsed


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
        properties = {name: _schema_node(child) for name, child in value.items()}
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


def _glm_only_proof(parse_result) -> dict[str, Any]:
    metadata = parse_result.metadata
    luna_calls = list(parse_result.usage.calls) if parse_result.usage else []
    proof = {
        "visual_recovery_enabled": metadata.visual_recovery_enabled,
        "recovery_log_entries": len(parse_result.recovery_log),
        "luna_time": metadata.luna_time,
        "luna_calls": len(luna_calls),
    }
    if (
        proof["visual_recovery_enabled"]
        or proof["recovery_log_entries"]
        or proof["luna_time"]
        or proof["luna_calls"]
    ):
        raise RuntimeError(f"GLM-only evaluation used Luna: {proof}")
    return proof


def _write_artifacts(
    directory: Path,
    document_id: str,
    parse_result,
    *,
    pipeline_mode: str,
    glm_only_proof: dict[str, Any] | None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{document_id}.md").write_text(
        parse_result.markdown, encoding="utf-8"
    )
    (directory / f"{document_id}.parse.json").write_text(
        parse_result.json.rstrip() + "\n", encoding="utf-8"
    )
    provenance = {
        "pipeline_mode": pipeline_mode,
        "glm_only_proof": glm_only_proof,
        "metadata": parse_result.metadata.model_dump(mode="json"),
        "usage": (
            parse_result.usage.model_dump(mode="json") if parse_result.usage else None
        ),
        "recovery_log": [
            item.model_dump(mode="json") for item in parse_result.recovery_log
        ],
    }
    (directory / f"{document_id}.run.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
        source_path = corpus_document.source_path or external_sources.get(
            corpus_document.id
        )
        if source_path is None:
            documents.append(
                {
                    "id": corpus_document.id,
                    "features": corpus_document.features,
                    "expected_document_type": corpus_document.expected_document_type,
                    "classification": (
                        {
                            "value": None,
                            "reason": "source is unavailable",
                        }
                        if corpus_document.expected_document_type is not None
                        else None
                    ),
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
                parse_data,
                parse_name,
                refine_markdown=not args.glm_only,
                visual_recovery=not args.glm_only,
            )
            glm_only_proof = _glm_only_proof(parse_result) if args.glm_only else None
            analysis_result = None
            if corpus_document.expected_document_type is not None and not args.glm_only:
                analysis_result = DocumentAgent().analyze(
                    parse_result,
                    classify=True,
                    generate_toc=False,
                )
            extraction_result = None
            if (
                not args.glm_only
                and corpus_document.annotation is not None
                and corpus_document.annotation.schema_output is not None
            ):
                extraction_result = DocumentExtractor().extract(
                    parse_result,
                    _schema_node(corpus_document.annotation.schema_output, root=True),
                )
            telemetry = live_telemetry_record(
                parse_result,
                analysis_result=analysis_result,
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
                classification=(
                    analysis_result.classification
                    if analysis_result is not None
                    else None
                ),
                extraction_data=extraction_result.data if extraction_result else None,
                reference_text=reference_text,
                reference_is_markdown=bool(
                    reference_path is not None
                    and reference_path.suffix.casefold() == ".md"
                ),
                reference_basis=reference_bases.get(corpus_document.id),
                source_page_numbers=source_pages,
            )
            record["status"] = "evaluated"
            record["pipeline_mode"] = "glm_only" if args.glm_only else "full"
            if (
                corpus_document.expected_document_type is not None
                and record["classification"] is None
            ):
                status = (
                    analysis_result.features.get("classification")
                    if analysis_result is not None
                    else None
                )
                reason = "classification result is unavailable"
                if args.glm_only:
                    reason = "classification is disabled by --glm-only"
                elif status is not None:
                    reason = f"classification status: {status.status}"
                record["classification"] = {
                    "value": None,
                    "reason": reason,
                }
            if glm_only_proof is not None:
                record["glm_only_proof"] = glm_only_proof
            if source_pages is not None:
                record["source_page_numbers"] = source_pages
            if args.artifacts_dir is not None:
                _write_artifacts(
                    args.artifacts_dir,
                    corpus_document.id,
                    parse_result,
                    pipeline_mode=record["pipeline_mode"],
                    glm_only_proof=glm_only_proof,
                )
            documents.append(record)
        except Exception as exc:  # noqa: BLE001 - corpus reports isolated failures
            had_error = True
            documents.append(
                {
                    "id": corpus_document.id,
                    "features": corpus_document.features,
                    "expected_document_type": corpus_document.expected_document_type,
                    "classification": (
                        {"value": None, "reason": "document evaluation failed"}
                        if corpus_document.expected_document_type is not None
                        else None
                    ),
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
            review_threshold=args.review_threshold,
        ),
        had_error,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run live corpus evaluation and optional regression gates"
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
    parser.add_argument(
        "--glm-only",
        action="store_true",
        help="Disable Luna recovery, refinement, and extraction, and verify no Luna usage",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="Write candidate Markdown, parse JSON, and run provenance per document",
    )
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
    parser.add_argument(
        "--review-threshold",
        type=_unit_interval,
        default=0.85,
        help="Confidence below this value requires document-type review",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        help="Regression policy JSON with absolute and optional baseline limits",
    )
    parser.add_argument("--baseline", type=Path, help="Prior compatible report JSON")
    args = parser.parse_args()
    if not args.live:
        parser.error("visual-only evaluation requires --live")
    report, had_error = _live_report(args)
    gate_failed = False
    if args.thresholds is not None:
        policy = json.loads(args.thresholds.read_text(encoding="utf-8"))
        baseline = (
            json.loads(args.baseline.read_text(encoding="utf-8"))
            if args.baseline is not None
            else None
        )
        report["regression"] = evaluate_regression_policy(
            report, policy, baseline=baseline
        )
        gate_failed = not report["regression"]["passed"]
    elif args.baseline is not None:
        parser.error("--baseline requires --thresholds")
    output = args.output or Path("output/evaluation-corpus-live.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(output)
    return int(had_error or gate_failed)


if __name__ == "__main__":
    raise SystemExit(main())
