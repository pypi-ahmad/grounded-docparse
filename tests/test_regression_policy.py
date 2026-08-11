from __future__ import annotations

import pytest

from grounded_docparse.benchmark import evaluate_regression_policy


def _report(*, accuracy: float, review_rate: float) -> dict:
    return {
        "schema_version": "1.0",
        "corpus_id": "private-holdout-v1",
        "evaluation_mode": "live_pipeline",
        "classification": {
            "accuracy": accuracy,
            "review": {"threshold": 0.85, "review_rate": review_rate},
        },
    }


POLICY = {
    "schema_version": "1.0",
    "rules": [
        {
            "name": "classification accuracy",
            "path": "/classification/accuracy",
            "direction": "higher_is_better",
            "minimum": 0.85,
            "max_regression": 0.03,
        },
        {
            "name": "classification review rate",
            "path": "/classification/review/review_rate",
            "direction": "lower_is_better",
            "maximum": 0.15,
            "max_regression": 0.03,
        },
    ],
}


def test_regression_policy_passes_absolute_and_baseline_limits() -> None:
    result = evaluate_regression_policy(
        _report(accuracy=0.88, review_rate=0.12),
        POLICY,
        baseline=_report(accuracy=0.9, review_rate=0.1),
    )

    assert result["passed"] is True
    assert result["evaluated_rules"] == 2
    assert result["violations"] == []
    assert [rule["passed"] for rule in result["rules"]] == [True, True]


def test_regression_policy_reports_each_failed_constraint() -> None:
    result = evaluate_regression_policy(
        _report(accuracy=0.84, review_rate=0.14),
        POLICY,
        baseline=_report(accuracy=0.9, review_rate=0.1),
    )

    assert result["passed"] is False
    assert {violation["rule"] for violation in result["violations"]} == {
        "classification accuracy",
        "classification review rate",
    }
    accuracy = result["rules"][0]
    assert accuracy["absolute_passed"] is False
    assert accuracy["regression_passed"] is False
    assert result["rules"][1]["absolute_passed"] is True
    assert result["rules"][1]["regression_passed"] is False


def test_regression_policy_fails_closed_for_missing_metric() -> None:
    result = evaluate_regression_policy(
        _report(accuracy=0.9, review_rate=0.1),
        {
            "schema_version": "1.0",
            "rules": [
                {
                    "name": "required support",
                    "path": "/classification/labeled_documents",
                    "direction": "higher_is_better",
                    "minimum": 20,
                }
            ],
        },
    )

    assert result["passed"] is False
    assert result["violations"][0]["reason"] == "candidate metric is missing"


def test_regression_policy_rejects_incompatible_baseline() -> None:
    baseline = _report(accuracy=0.9, review_rate=0.1)
    baseline["corpus_id"] = "different-corpus"

    with pytest.raises(ValueError, match="corpus_id"):
        evaluate_regression_policy(
            _report(accuracy=0.9, review_rate=0.1), POLICY, baseline=baseline
        )


def test_regression_policy_requires_matching_baseline_review_threshold() -> None:
    baseline = _report(accuracy=0.9, review_rate=0.1)
    del baseline["classification"]["review"]["threshold"]

    with pytest.raises(ValueError, match="review threshold"):
        evaluate_regression_policy(
            _report(accuracy=0.9, review_rate=0.1), POLICY, baseline=baseline
        )
