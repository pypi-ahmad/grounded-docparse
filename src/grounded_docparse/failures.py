from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable

from .models import DocumentTree, FailureCase, GroundingScope, RunRecord

_WARNING_RULES = (
    ("PaddleOCR-VL unavailable", "provider_unavailable", "layout", "paddle", "PaddleOCR-VL was unavailable."),
    ("PaddleOCR-VL chunk fallback", "provider_page_error", "layout", "paddle", "PaddleOCR-VL processing degraded for a source chunk."),
    ("GLM-OCR unavailable", "provider_unavailable", "region_ocr", "ollama", "GLM-OCR was unavailable."),
    ("GLM retry fallback", "provider_page_error", "region_ocr", "ollama", "The confirming GLM-OCR retry failed."),
    ("GLM fallback", "provider_page_error", "region_ocr", "ollama", "GLM-OCR failed for a region."),
    ("OpenAI unavailable", "provider_unavailable", "cloud", "openai", "OpenAI verification was unavailable."),
    ("Luna fallback", "provider_page_error", "page_verification", "openai", "Luna verification failed for a page."),
    ("Terra fallback", "provider_page_error", "document_resolution", "openai", "Terra document resolution failed."),
    ("unknown region ID", "cloud_response_rejected", "page_verification", "openai", "A cloud response referenced an unknown region."),
    ("unknown candidate ID", "cloud_response_rejected", "page_verification", "openai", "A cloud response referenced an unknown candidate."),
    ("Boundary before page", "boundary_adjudication_failed", "segmentation", "openai", "Cloud boundary adjudication failed."),
)

_REGION_FAILURES = {
    "unreadable": ("region_unreadable", "error", "unresolved", "OCR produced no usable text for the region."),
    "unresolved": ("region_unresolved", "error", "unresolved", "Candidate verification did not resolve the region."),
    "disputed": ("region_disputed", "warning", "degraded", "Local recognition candidates disagree."),
    "retry_confirmed": ("ocr_retry_required", "info", "recovered", "A confirming OCR retry was required."),
}


def _stable_id(tree: DocumentTree, parts: Iterable[object]) -> str:
    raw = "|".join([tree.source_sha256, *(str(part or "") for part in parts)])
    return f"failure-{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


def _model_for(
    tree: DocumentTree,
    provider: str | None,
    page_number: int | None,
    region_id: str | None,
) -> str | None:
    matches: list[RunRecord] = []
    for run in tree.model_runs:
        if provider and run.provider != provider:
            continue
        if page_number is not None and run.page_number not in {None, page_number}:
            continue
        if region_id is not None and run.region_id not in {None, region_id}:
            continue
        matches.append(run)
    return matches[-1].model if matches else None


def _provider_for_source(source: str | None) -> str | None:
    return {
        "glm": "ollama",
        "luna": "openai",
        "terra": "openai",
        "paddle": "paddle",
    }.get(source or "")


def _case(
    tree: DocumentTree,
    *,
    code: str,
    stage: str,
    severity: str,
    outcome: str,
    scope: str,
    message: str,
    page_number: int | None = None,
    segment_page_number: int | None = None,
    region_id: str | None = None,
    node_ids: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    attempt: int | None = None,
    exception_type: str | None = None,
    evidence_refs: list[str] | None = None,
) -> FailureCase:
    node_ids = node_ids or []
    evidence_refs = evidence_refs or []
    identity = (
        code,
        stage,
        outcome,
        scope,
        page_number,
        segment_page_number,
        region_id,
        ",".join(node_ids),
        provider,
        attempt,
        exception_type,
        ",".join(evidence_refs),
    )
    return FailureCase(
        id=_stable_id(tree, identity),
        code=code,
        stage=stage,
        severity=severity,
        outcome=outcome,
        scope=scope,
        message=message,
        page_number=page_number,
        segment_page_number=segment_page_number,
        region_id=region_id,
        node_ids=node_ids,
        provider=provider,
        model=model,
        attempt=attempt,
        exception_type=exception_type,
        evidence_refs=evidence_refs,
    )


def _warning_cases(
    tree: DocumentTree,
    page_numbers: set[int],
    segment_pages: dict[int, int | None],
) -> list[FailureCase]:
    cases: list[FailureCase] = []
    for warning in tree.warnings:
        page_match = re.search(r"\bPage (\d+)\b", warning)
        page_number = int(page_match.group(1)) if page_match else None
        if page_number is not None and page_number not in page_numbers:
            continue
        region_match = re.search(r"\bregion ([A-Za-z0-9_.:-]+)", warning)
        region_id = region_match.group(1).rstrip(":") if region_match else None
        exception_match = re.search(r"\(([A-Za-z_][A-Za-z0-9_.]*)\)\s*$", warning)
        exception_type = exception_match.group(1) if exception_match else None
        rule = next((item for item in _WARNING_RULES if item[0] in warning), None)
        if rule:
            _, code, stage, provider, message = rule
        else:
            code, stage, provider, message = (
                "parser_warning",
                "pipeline",
                None,
                "The parser completed with a warning.",
            )
        cases.append(
            _case(
                tree,
                code=code,
                stage=stage,
                severity="warning",
                outcome="degraded",
                scope="region" if region_id else "page" if page_number else "document",
                message=message,
                page_number=page_number,
                segment_page_number=segment_pages.get(page_number),
                region_id=region_id,
                provider=provider,
                model=_model_for(tree, provider, page_number, region_id),
                exception_type=exception_type,
            )
        )
    return cases


def _window_cases(tree: DocumentTree) -> list[FailureCase]:
    cases: list[FailureCase] = []
    for window in tree.window_runs:
        if window.status != "degraded":
            continue
        cases.append(
            _case(
                tree,
                code="window_degraded",
                stage="window",
                severity="warning",
                outcome="degraded",
                scope="document",
                message="A page-processing window exhausted its retry budget.",
                attempt=window.attempts,
                evidence_refs=[f"pages:{window.start_page}-{window.end_page}"],
            )
        )
    return cases


def _node_cases(
    tree: DocumentTree, segment_pages: dict[int, int | None]
) -> list[FailureCase]:
    cases: list[FailureCase] = []
    content_nodes = {
        node_id: tree.nodes[node_id]
        for page in tree.pages
        for node_id in page.content_node_ids
    }
    for node in content_nodes.values():
        status = node.verification_status or ""
        region_rule = _REGION_FAILURES.get(status)
        if region_rule:
            code, severity, outcome, message = region_rule
            selected = next(
                (
                    candidate
                    for candidate in node.recognition_candidates
                    if candidate.id == node.selected_candidate_id
                ),
                None,
            )
            provider = _provider_for_source(selected.source if selected else None)
            cases.append(
                _case(
                    tree,
                    code=code,
                    stage="region_ocr",
                    severity=severity,
                    outcome=outcome,
                    scope="region",
                    message=message,
                    page_number=node.page_number,
                    segment_page_number=segment_pages.get(node.page_number),
                    region_id=node.id,
                    node_ids=[node.id],
                    provider=provider,
                    model=_model_for(tree, provider, node.page_number, node.id),
                    attempt=2 if status == "retry_confirmed" else None,
                    evidence_refs=[item.id for item in node.recognition_candidates],
                )
            )
        if not node.citations:
            cases.append(
                _case(
                    tree,
                    code="citation_missing",
                    stage="grounding",
                    severity="error",
                    outcome="unresolved",
                    scope="node",
                    message="The content node has no source citation.",
                    page_number=node.page_number,
                    segment_page_number=segment_pages.get(node.page_number),
                    node_ids=[node.id],
                )
            )
        elif any(
            str(citation.grounding_scope) == GroundingScope.UNRESOLVED.value
            for citation in node.citations
        ):
            cases.append(
                _case(
                    tree,
                    code="citation_unresolved",
                    stage="grounding",
                    severity="error",
                    outcome="unresolved",
                    scope="node",
                    message="The content node has unresolved source grounding.",
                    page_number=node.page_number,
                    segment_page_number=segment_pages.get(node.page_number),
                    node_ids=[node.id],
                    evidence_refs=[citation.id for citation in node.citations],
                )
            )
    return cases


def _validation_cases(tree: DocumentTree) -> list[FailureCase]:
    cases: list[FailureCase] = []
    for finding in tree.validation_findings:
        severity = finding.severity if finding.severity in {"error", "warning", "info"} else "warning"
        cases.append(
            _case(
                tree,
                code="validation_finding",
                stage="validation",
                severity=severity,
                outcome="unresolved" if severity == "error" else "degraded",
                scope="node" if finding.source_node_ids else "document",
                message="Document validation produced a finding.",
                node_ids=finding.source_node_ids,
                evidence_refs=[finding.code, *finding.field_paths],
            )
        )
    return cases


def _schema_extraction_cases(tree: DocumentTree) -> list[FailureCase]:
    cases: list[FailureCase] = []
    for extraction in tree.schema_extractions:
        if not extraction.validation_errors:
            continue
        cases.append(
            _case(
                tree,
                code="schema_validation_error",
                stage="schema_extraction",
                severity="error",
                outcome="unresolved",
                scope="document",
                message="Schema extraction contains validation errors.",
                evidence_refs=[
                    extraction.schema_sha256,
                    extraction.subdocument_id or extraction.document_id,
                ],
            )
        )
    return cases


def _segmentation_cases(
    tree: DocumentTree, segment_pages: dict[int, int | None]
) -> list[FailureCase]:
    cases: list[FailureCase] = []
    if tree.batch_manifest:
        for boundary in tree.batch_manifest.boundaries:
            if boundary.decision != "uncertain":
                continue
            cases.append(
                _case(
                    tree,
                    code="segmentation_uncertain",
                    stage="segmentation",
                    severity="warning",
                    outcome="unresolved",
                    scope="page",
                    message="A document boundary remains uncertain.",
                    page_number=boundary.before_page,
                    segment_page_number=segment_pages.get(boundary.before_page),
                    evidence_refs=[f"before-page:{boundary.before_page}"],
                )
            )
    return cases


def derive_failure_cases(tree: DocumentTree) -> list[FailureCase]:
    page_numbers = {page.number for page in tree.pages}
    segment_pages = {page.number: page.segment_page_number for page in tree.pages}
    cases = _warning_cases(tree, page_numbers, segment_pages)
    cases.extend(_window_cases(tree))
    cases.extend(_node_cases(tree, segment_pages))
    cases.extend(_validation_cases(tree))
    cases.extend(_schema_extraction_cases(tree))
    cases.extend(_segmentation_cases(tree, segment_pages))

    unique = {case.id: case for case in cases}
    return sorted(
        unique.values(),
        key=lambda item: (
            item.page_number or 0,
            item.stage,
            item.code,
            item.id,
        ),
    )


def render_failures_jsonl(tree: DocumentTree) -> str:
    lines = [
        json.dumps(
            {
                "schema_version": "1.0.0",
                "document_id": tree.document_id,
                "source_sha256": tree.source_sha256,
                "failure": item.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in tree.failure_cases
    ]
    return "\n".join(lines) + ("\n" if lines else "")
