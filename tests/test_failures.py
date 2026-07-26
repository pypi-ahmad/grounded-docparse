from __future__ import annotations

import json

from grounded_docparse import DocumentParser, ParserConfig
from grounded_docparse.failures import derive_failure_cases, render_failures_jsonl
from grounded_docparse.models import (
    BoundaryDecision,
    SchemaExtraction,
    ValidationFinding,
    WindowRun,
)


def _offline_config() -> ParserConfig:
    return ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=False,
        render_dpi=150,
    )


def test_failure_derivation_is_structured_deterministic_and_sanitized(
    simple_pdf: bytes,
) -> None:
    tree = DocumentParser(_offline_config()).parse(simple_pdf, "failure.pdf").tree
    node = tree.nodes[tree.pages[0].content_node_ids[0]]
    node.verification_status = "unresolved"
    node.citations = []
    tree.warnings = [
        "Page 1 region private-region GLM fallback (SensitiveRuntimeError)"
    ]
    tree.window_runs = [WindowRun(start_page=1, end_page=1, attempts=3, status="degraded")]
    tree.validation_findings = [
        ValidationFinding(
            code="test-finding",
            severity="warning",
            message="private validation text",
            field_paths=["invoice.total"],
            source_node_ids=[node.id],
        )
    ]

    first = derive_failure_cases(tree)
    second = derive_failure_cases(tree)
    assert first == second
    assert {
        "provider_page_error",
        "window_degraded",
        "region_unresolved",
        "citation_missing",
        "validation_finding",
    } <= {item.code for item in first}

    tree.failure_cases = first
    rendered = render_failures_jsonl(tree)
    assert "private validation text" not in rendered
    assert node.text not in rendered
    assert "SensitiveRuntimeError" in rendered
    records = [json.loads(line) for line in rendered.splitlines()]
    assert all(record["source_sha256"] == tree.source_sha256 for record in records)


def test_confirmed_retry_is_a_recovered_failure_case(simple_pdf: bytes) -> None:
    tree = DocumentParser(_offline_config()).parse(simple_pdf, "retry.pdf").tree
    node = tree.nodes[tree.pages[0].content_node_ids[0]]
    node.verification_status = "retry_confirmed"

    cases = derive_failure_cases(tree)
    recovered = next(item for item in cases if item.code == "ocr_retry_required")
    assert recovered.outcome == "recovered"
    assert recovered.attempt == 2
    assert recovered.node_ids == [node.id]


def test_schema_and_segmentation_failures_are_stable_sorted_and_sanitized(
    simple_pdf: bytes,
) -> None:
    tree = DocumentParser(_offline_config()).parse(simple_pdf, "failures.pdf").tree
    tree.schema_extractions = [
        SchemaExtraction(
            schema_name="Test schema",
            schema_sha256="0" * 64,
            document_id=tree.document_id,
            status="partial",
            validation_errors=["private schema validation detail"],
        )
    ]
    assert tree.batch_manifest is not None
    tree.batch_manifest.boundaries.append(
        BoundaryDecision(
            before_page=2,
            score=0.6,
            decision="uncertain",
            confidence=0.2,
            reasons=["private boundary detail"],
        )
    )

    first = derive_failure_cases(tree)
    second = derive_failure_cases(tree)

    assert first == second
    assert {"schema_validation_error", "segmentation_uncertain"} <= {
        item.code for item in first
    }
    assert first == sorted(
        first,
        key=lambda item: (item.page_number or 0, item.stage, item.code, item.id),
    )
    rendered = "\n".join(item.model_dump_json() for item in first)
    assert "private schema validation detail" not in rendered
    assert "private boundary detail" not in rendered
