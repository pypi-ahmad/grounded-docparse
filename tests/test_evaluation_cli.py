from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

from grounded_docparse.models import (
    AgenticAnalysis,
    AgentUsage,
    Document,
    DocumentClassification,
    Page,
    RunUsage,
)

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_corpus.py"
_SPEC = importlib.util.spec_from_file_location("evaluate_corpus", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
evaluate_corpus = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(evaluate_corpus)


def test_live_report_classifies_only_labeled_document(monkeypatch, tmp_path) -> None:
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"fake pdf")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "annotation_schema_version": "1.1",
                "corpus_id": "private-calibration-v1",
                "documents": [
                    {
                        "id": "invoice-001",
                        "source": {"kind": "external", "path": "invoice.pdf"},
                        "features": ["scanner-a"],
                        "synthetic": False,
                        "expected_document_type": "Invoice",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    parse_result = SimpleNamespace(
        document=Document(
            source_name="invoice.pdf",
            source_sha256="a" * 64,
            pages=[Page(number=1, width=100, height=100)],
        ),
        usage=RunUsage(),
        runtime_diagnostics=None,
        trace=[],
    )

    class FakeParser:
        def parse(self, *_args, **_kwargs):
            return parse_result

    class FakeAgent:
        def analyze(self, value, *, classify, generate_toc):
            assert value is parse_result
            assert classify is True
            assert generate_toc is False
            return AgenticAnalysis(
                classification=DocumentClassification(
                    primary_type="Invoice", confidence=0.92
                ),
                usage=RunUsage(
                    calls=[
                        AgentUsage(
                            agent="classification",
                            model="luna",
                            input_tokens=12,
                            output_tokens=3,
                        )
                    ]
                ),
            )

    monkeypatch.setattr(evaluate_corpus, "DocumentParser", FakeParser)
    monkeypatch.setattr(evaluate_corpus, "DocumentAgent", FakeAgent)
    args = Namespace(
        manifest=manifest,
        repository_root=tmp_path,
        external_source=[f"invoice-001={source}"],
        reference=[],
        reference_basis=[],
        page_subset=[],
        document=[],
        glm_only=False,
        artifacts_dir=None,
        rate_card=None,
        review_threshold=0.85,
    )

    report, had_error = evaluate_corpus._live_report(args)

    assert had_error is False
    assert report["classification"]["accuracy"] == 1.0
    assert report["classification"]["review"]["review_rate"] == 0.0
    assert report["telemetry"]["model_usage"]["luna"]["calls"] == 1


def test_main_writes_failed_regression_gate_before_nonzero_exit(
    monkeypatch, tmp_path
) -> None:
    output = tmp_path / "report.json"
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "rules": [
                    {
                        "name": "classification accuracy",
                        "path": "/classification/accuracy",
                        "direction": "higher_is_better",
                        "minimum": 0.9,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    candidate = {
        "schema_version": "1.0",
        "corpus_id": "private-holdout-v1",
        "evaluation_mode": "live_pipeline",
        "classification": {
            "accuracy": 0.8,
            "review": {"threshold": 0.85, "review_rate": 0.2},
        },
    }
    monkeypatch.setattr(evaluate_corpus, "_live_report", lambda _args: (candidate, False))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_corpus.py",
            "--live",
            "--output",
            str(output),
            "--thresholds",
            str(policy),
        ],
    )

    exit_code = evaluate_corpus.main()

    written = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert written["regression"]["passed"] is False
    assert written["regression"]["violations"][0]["rule"] == (
        "classification accuracy"
    )
