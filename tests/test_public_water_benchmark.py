import pytest

from grounded_docparse.benchmark import (
    accuracy_threshold_failures,
    compare_markdown,
    evaluate_result,
)
from grounded_docparse.models import (
    AtomicEvidence,
    Block,
    BoundingBox,
    Citation,
    Document,
    FormData,
    Page,
    VerificationState,
)


def _grounded_block(**values) -> Block:
    box = BoundingBox(x0=0.1, y0=0.1, x1=0.9, y1=0.2)
    return Block(
        id=values.pop("id", "p1-b1"),
        bbox=box,
        citation=Citation(page=1, bbox=box),
        confidence=0.99,
        **values,
    )


def test_benchmark_accepts_grounded_literal_content() -> None:
    document = Document(
        source_name="water.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    _grounded_block(
                        type="list_item",
                        text="Call 573-751-3334\nwithin 24 hours.",
                        list_marker="1.",
                        reading_order=0,
                    )
                ],
            )
        ],
    )
    expectations = {
        "schema_version": "2.0.0",
        "page_count": 1,
        "page_break_count": 0,
        "minimum_word_count": 5,
        "required_by_page": {"1": ["573-751-3334 within 24 hours"]},
        "forbidden": ["within 4 hours"],
        "list_markers_by_page": {"1": ["1."]},
        "minimum_types_by_page": {"1": {"list_item": 1}},
        "figure_terms_by_page": {},
    }

    assert (
        evaluate_result(
            document, "1. Call 573-751-3334 within 24 hours.\n", expectations
        )
        == []
    )


def test_benchmark_reports_content_structure_and_grounding_failures() -> None:
    block = Block(
        id="p1-b1",
        type="list_item",
        text="Call within 4 hours.",
        list_marker="-",
        reading_order=0,
        verification=VerificationState.NOT_CHECKED,
    )
    document = Document(
        source_name="water.pdf",
        source_sha256="b" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )
    expectations = {
        "schema_version": "2.0.0",
        "page_count": 1,
        "page_break_count": 0,
        "minimum_word_count": 5,
        "required_by_page": {"1": ["within 24 hours"]},
        "forbidden": ["within 4 hours"],
        "list_markers_by_page": {"1": ["1."]},
        "minimum_types_by_page": {"1": {"form_field": 1}},
        "figure_terms_by_page": {},
    }

    failures = evaluate_result(document, "- Call within 4 hours.\n", expectations)

    assert any("missing required text" in failure for failure in failures)
    assert any("forbidden text" in failure for failure in failures)
    assert any("list markers" in failure for failure in failures)
    assert any("form_field" in failure for failure in failures)
    assert any("grounding" in failure for failure in failures)


def test_reference_comparison_reports_order_sensitive_and_token_metrics() -> None:
    candidate = "Alpha beta delta\n<!-- PAGE BREAK -->\nOne two\n"
    reference = "Alpha beta gamma\n<!-- PAGE BREAK -->\nOne two\n"

    report = compare_markdown(candidate, reference, text_dominant_pages=[2])

    assert report["strict_word_accuracy"] == pytest.approx(80.0)
    assert report["word_error_rate"] == pytest.approx(20.0)
    assert report["token_f1"] == pytest.approx(80.0)
    assert report["text_dominant_accuracy"] == pytest.approx(100.0)
    assert report["pages"]["1"]["accuracy"] == pytest.approx(100 * 2 / 3)
    assert report["pages"]["2"]["accuracy"] == pytest.approx(100.0)


def test_accuracy_thresholds_report_overall_and_page_regressions() -> None:
    metrics = {
        "strict_word_accuracy": 89.0,
        "token_f1": 97.0,
        "text_dominant_accuracy": 98.0,
        "pages": {"5": {"accuracy": 70.0}},
    }
    thresholds = {
        "strict_word_accuracy": 89.17,
        "token_f1": 96.44,
        "page_accuracy": {"5": 71.66},
    }

    failures = accuracy_threshold_failures(metrics, thresholds)

    assert failures == [
        "strict_word_accuracy was 89.0000, expected greater than 89.1700",
        "page 5 accuracy was 70.0000, expected greater than 71.6600",
    ]


def test_reference_normalization_removes_html_tags_and_splits_punctuation() -> None:
    report = compare_markdown(
        "<figure>Max-fill line</figure>",
        "Max fill line",
    )

    assert report["strict_word_accuracy"] == pytest.approx(100.0)
    assert report["token_f1"] == pytest.approx(100.0)


def test_document_metrics_normalize_each_page_before_aggregation() -> None:
    candidate = "<div\n<!-- PAGE BREAK -->\nAlpha> retained"
    reference = "div\n<!-- PAGE BREAK -->\nAlpha retained"

    report = compare_markdown(candidate, reference)

    assert report["strict_word_accuracy"] == pytest.approx(100.0)
    assert report["token_f1"] == pytest.approx(100.0)


def test_required_content_search_includes_structured_form_hints() -> None:
    block = _grounded_block(
        type="form_field",
        text="Collected Time:",
        form=FormData(label="Collected Time", hint="24 hour format hh:mm"),
        reading_order=0,
    )
    document = Document(
        source_name="form.pdf",
        source_sha256="d" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )
    expectations = {
        "schema_version": "2.0.0",
        "page_count": 1,
        "page_break_count": 0,
        "minimum_word_count": 1,
        "required_by_page": {"1": ["24 hour format hh:mm"]},
        "forbidden": [],
        "list_markers_by_page": {},
        "minimum_types_by_page": {},
        "figure_terms_by_page": {},
    }

    assert (
        evaluate_result(
            document, "**Collected Time:** 24 hour format hh:mm\n", expectations
        )
        == []
    )


def test_visual_fact_groups_allow_alternatives_but_require_one_complete_block() -> None:
    step = _grounded_block(
        id="p1-b1",
        type="figure",
        figure_description="Circled number 6 beneath a tap with running water.",
        reading_order=0,
    )
    separate_cap = _grounded_block(
        id="p1-b2",
        type="figure",
        figure_description="A hand holds the bottle cap.",
        reading_order=1,
    )
    document = Document(
        source_name="instructions.pdf",
        source_sha256="e" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[step, separate_cap])],
    )
    expectations = {
        "schema_version": "2.0.0",
        "page_count": 1,
        "page_break_count": 0,
        "minimum_word_count": 1,
        "required_by_page": {},
        "forbidden": [],
        "list_markers_by_page": {},
        "minimum_types_by_page": {},
        "figure_terms_by_page": {},
        "visual_fact_groups_by_page": {
            "1": [
                [
                    ["step 6", "number 6", "circled 6"],
                    ["faucet", "tap"],
                    ["cap", "lid"],
                ]
            ]
        },
    }

    failures = evaluate_result(document, "Visual instructions\n", expectations)

    assert failures == ["page 1 has no visual block matching semantic fact group 1"]

    step.figure_description = (
        "Circled number 6 beneath a tap; another hand holds the cap."
    )

    assert evaluate_result(document, "Visual instructions\n", expectations) == []


def test_visual_fact_groups_search_atomic_visual_labels() -> None:
    visual = _grounded_block(
        id="p1-b1",
        type="figure",
        figure_description="A numbered collection step.",
        reading_order=0,
    )
    visual.atoms = [
        AtomicEvidence(kind="label", text="6"),
        AtomicEvidence(kind="label", text="faucet"),
        AtomicEvidence(kind="label", text="cap"),
    ]
    document = Document(
        source_name="instructions.pdf",
        source_sha256="e" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[visual])],
    )
    expectations = {
        "schema_version": "2.0.0",
        "page_count": 1,
        "page_break_count": 0,
        "minimum_word_count": 1,
        "required_by_page": {},
        "forbidden": [],
        "list_markers_by_page": {},
        "minimum_types_by_page": {},
        "figure_terms_by_page": {},
        "visual_fact_groups_by_page": {"1": [[["6"], ["faucet"], ["cap"]]]},
    }

    assert evaluate_result(document, "Visual instructions\n", expectations) == []
