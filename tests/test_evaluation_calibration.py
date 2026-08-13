from __future__ import annotations

import pytest

from grounded_docparse.benchmark import build_live_report


def _document(
    document_id: str,
    *,
    expected: str | None,
    predicted: str | None,
    confidence: float | None,
    blocks: int,
    needs_review: int,
    rejected: int,
) -> dict:
    classification = None
    if predicted is not None and confidence is not None:
        classification = {
            "predicted_type": predicted,
            "confidence": confidence,
        }
    return {
        "id": document_id,
        "features": ["fixture"],
        "expected_document_type": expected,
        "classification": classification,
        "pages": 1,
        "metrics": {
            "semantic_text": {"word_accuracy": 1.0},
            "review_outcomes": {
                "block_count": blocks,
                "needs_review_count": needs_review,
                "rejected_count": rejected,
                "review_rate": needs_review / blocks if blocks else 0.0,
                "rejection_rate": rejected / blocks if blocks else 0.0,
            },
        },
        "telemetry": {
            "latency_seconds": 1.0,
            "pages": 1,
            "input_tokens": 0,
            "output_tokens": 0,
            "full_page_fallbacks": 0,
            "model_usage": {},
            "retries": 0,
            "rate_limit_events": 0,
        },
    }


def test_live_report_scores_classification_calibration_and_review_rate() -> None:
    documents = [
        _document(
            "invoice-correct",
            expected="Invoice",
            predicted="Invoice",
            confidence=0.9,
            blocks=10,
            needs_review=2,
            rejected=1,
        ),
        _document(
            "invoice-wrong",
            expected="Invoice",
            predicted="Report",
            confidence=0.8,
            blocks=2,
            needs_review=2,
            rejected=0,
        ),
        _document(
            "report-correct",
            expected="Report",
            predicted="Report",
            confidence=0.6,
            blocks=0,
            needs_review=0,
            rejected=0,
        ),
        _document(
            "unlabeled",
            expected=None,
            predicted=None,
            confidence=None,
            blocks=0,
            needs_review=0,
            rejected=0,
        ),
    ]

    report = build_live_report(
        corpus_id="private-holdout-v1",
        documents=documents,
        rate_card=None,
        review_threshold=0.85,
    )

    classification = report["classification"]
    assert classification["labeled_documents"] == 3
    assert classification["unlabeled_documents"] == 1
    assert classification["accuracy"] == pytest.approx(2 / 3)
    assert classification["macro_f1"] == pytest.approx(2 / 3)
    assert classification["calibration"]["top_label_brier_score"] == pytest.approx(
        0.27
    )
    assert classification["calibration"]["expected_calibration_error"] == (
        pytest.approx(13 / 30)
    )
    assert classification["review"]["threshold"] == 0.85
    assert classification["review"]["review_rate"] == pytest.approx(2 / 3)
    assert classification["review"]["auto_approved_accuracy"] == 1.0
    assert classification["confusion_matrix"]["Invoice"] == {
        "Invoice": 1,
        "Report": 1,
    }


def test_live_report_groups_metrics_and_micro_review_by_document_type() -> None:
    documents = [
        _document(
            "large",
            expected="Invoice",
            predicted="Invoice",
            confidence=0.9,
            blocks=10,
            needs_review=2,
            rejected=1,
        ),
        _document(
            "small",
            expected="Invoice",
            predicted="Invoice",
            confidence=0.9,
            blocks=2,
            needs_review=2,
            rejected=0,
        ),
    ]

    report = build_live_report(
        corpus_id="private-holdout-v1",
        documents=documents,
        rate_card=None,
    )

    review = report["review"]["ocr_blocks"]
    assert review["block_count"] == 12
    assert review["needs_review_count"] == 4
    assert review["review_rate"] == pytest.approx(1 / 3)
    assert review["rejected_count"] == 1
    invoice = report["document_types"]["Invoice"]
    assert invoice["document_ids"] == ["large", "small"]
    assert invoice["metrics"]["semantic_text"]["word_accuracy"] == 1.0
    assert invoice["review"]["ocr_blocks"]["review_rate"] == pytest.approx(1 / 3)
