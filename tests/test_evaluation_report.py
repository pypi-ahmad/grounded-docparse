from __future__ import annotations

from grounded_docparse.benchmark import build_live_report


def test_live_report_groups_documents_and_marks_missing_grounding() -> None:
    documents = [
        {
            "id": "doc-1",
            "features": ["tables", "grounding"],
            "pages": 1,
            "metrics": {
                "semantic_text": {"word_accuracy": 1.0},
                "grounding": {"value": None, "reason": "no stable candidate regions"},
            },
            "telemetry": {
                "latency_seconds": 2.0,
                "pages": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "full_page_fallbacks": 0,
                "model_usage": {
                    "luna": {"calls": 1, "input_tokens": 100, "output_tokens": 20}
                },
                "retries": 0,
                "rate_limit_events": 0,
            },
        }
    ]

    report = build_live_report(
        corpus_id="fixture-v1",
        documents=documents,
        rate_card=None,
    )

    assert report["evaluation_mode"] == "live_pipeline"
    assert report["broad_production_claim"] is False
    assert report["classes"]["tables"]["document_ids"] == ["doc-1"]
    assert report["classes"]["tables"]["metrics"]["semantic_text"][
        "word_accuracy"
    ] == 1.0
    assert report["aggregate"]["metrics"]["grounding"]["value"] is None
    assert report["telemetry"]["model_calls"] == 1
    assert report["runtime"]["retries"] == 0
