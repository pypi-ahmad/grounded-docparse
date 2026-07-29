from __future__ import annotations

import pytest

from grounded_docparse.benchmark import (
    CorpusAnnotation,
    CorpusDocument,
    CorpusSource,
    canonical_document_pages,
    continuity_metrics,
    evaluate_live_document,
    grounding_metrics,
    hallucination_metrics,
    reading_order_metrics,
    schema_leaf_metrics,
    semantic_text_metrics,
    semantic_text_metrics_by_page,
    semantic_text_metrics_for_reference_pages,
    summarize_telemetry,
    table_cell_metrics,
)
from grounded_docparse.models import (
    AtomicEvidence,
    Block,
    BoundingBox,
    Document,
    NodeType,
    Page,
    TableCell,
    TableData,
    VerificationState,
)


def test_semantic_text_metrics_normalize_unicode_and_whitespace() -> None:
    metrics = semantic_text_metrics("Cafe\u0301\n  beta", "Caf\u00e9 beta")

    assert metrics == {
        "character_accuracy": 1.0,
        "character_error_rate": 0.0,
        "word_accuracy": 1.0,
        "word_error_rate": 0.0,
    }


def test_canonical_document_text_includes_markers_and_table_cells_once() -> None:
    document = Document(
        source_name="fixture.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="p1-b1",
                        type=NodeType.LIST_ITEM,
                        text="First item",
                        list_marker="1.",
                        bbox=BoundingBox(x0=0, y0=0, x1=1, y1=0.2),
                        reading_order=0,
                    ),
                    Block(
                        id="p1-b2",
                        type=NodeType.TABLE,
                        text="Item | Count",
                        table=TableData(
                            cells=[
                                TableCell(row=0, column=0, text="Item"),
                                TableCell(row=0, column=1, text="Count"),
                            ]
                        ),
                        bbox=BoundingBox(x0=0, y0=0.3, x1=1, y1=0.6),
                        reading_order=1,
                    ),
                    Block(
                        id="p1-b3",
                        type=NodeType.PARAGRAPH,
                        text="Rejected noise",
                        bbox=BoundingBox(x0=0, y0=0.7, x1=1, y1=0.8),
                        reading_order=2,
                        verification=VerificationState.REJECTED,
                    ),
                ],
            )
        ],
    )

    assert canonical_document_pages(document) == ["1. First item\nItem Count"]


def test_semantic_metrics_align_explicit_page_breaks_before_aggregation() -> None:
    metrics = semantic_text_metrics_by_page(
        ["Alpha page", "Beta page"],
        "Alpha page\n<!-- PAGE BREAK -->\nBeta page",
    )

    assert metrics["character_accuracy"] == 1.0
    assert metrics["word_accuracy"] == 1.0
    assert metrics["page_count"] == 2


def test_partial_page_metrics_use_original_source_page_numbers() -> None:
    metrics = semantic_text_metrics_for_reference_pages(
        ["page four", "page six"],
        {4: "page four", 5: "not selected", 6: "page six"},
        source_page_numbers=[4, 6],
    )

    assert metrics["word_accuracy"] == 1.0
    assert metrics["scored_pages"] == [4, 6]


def test_recognized_text_excludes_figure_prose_but_keeps_literal_atoms() -> None:
    block = Block(
        id="p1-b1",
        type=NodeType.FIGURE,
        text="",
        figure_description="A generated description of a bottle.",
        reading_order=0,
        atoms=[AtomicEvidence(kind="label", text="MAX FILL LINE")],
    )
    document = Document(
        source_name="figure.pdf",
        source_sha256="a" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    assert canonical_document_pages(document, recognized_text_only=True) == [
        "MAX FILL LINE"
    ]


def test_live_metrics_separate_verified_and_generated_references() -> None:
    document = Document(
        source_name="figure.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="p1-b1",
                        type=NodeType.FIGURE,
                        figure_description="Generated bottle prose",
                        reading_order=0,
                        atoms=[AtomicEvidence(kind="label", text="MAX FILL LINE")],
                    )
                ],
            )
        ],
    )
    corpus_document = CorpusDocument(
        id="figure",
        source=CorpusSource(kind="local", path="figure.pdf", sha256="a" * 64),
        features=["figures"],
        synthetic=False,
        annotation=CorpusAnnotation(
            schema_version="1.1",
            document_id="figure",
            reference_text="MAX FILL LINE",
            reference_basis="source_verified",
        ),
    )

    verified = evaluate_live_document(corpus_document, document, telemetry={})
    generated = evaluate_live_document(
        corpus_document,
        document,
        telemetry={},
        reference_text="MAX FILL LINE",
    )

    assert verified["metrics"]["source_verified_text"]["word_accuracy"] == 1.0
    assert verified["metrics"]["legacy_reference_agreement"]["value"] is None
    assert generated["metrics"]["source_verified_text"]["value"] is None
    assert (
        generated["metrics"]["legacy_reference_agreement"]["reference_basis"]
        == "generated"
    )


def test_markdown_reference_scores_all_text_after_removing_presentation_syntax() -> (
    None
):
    document = Document(
        source_name="fixture.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=100,
                height=100,
                blocks=[
                    Block(
                        id="p1-b1",
                        type=NodeType.PARAGRAPH,
                        text="Heading Bold bottle description",
                        reading_order=0,
                    )
                ],
            )
        ],
    )
    corpus_document = CorpusDocument(
        id="markdown-reference",
        source=CorpusSource(kind="external", path="fixture.pdf"),
        features=["ocr_required"],
        synthetic=False,
    )

    result = evaluate_live_document(
        corpus_document,
        document,
        telemetry={},
        reference_text=(
            "# Heading\n\n**Bold**\n\n"
            "<figure><description>bottle description</description></figure>"
        ),
        reference_is_markdown=True,
        reference_basis="source_verified",
    )

    semantic = result["metrics"]["semantic_text"]
    assert semantic["character_accuracy"] == 1.0
    assert semantic["word_accuracy"] == 1.0


def test_reading_order_reports_pairwise_accuracy_and_anchor_coverage() -> None:
    metrics = reading_order_metrics(
        candidate_anchor_ids=["title", "right-column"],
        reference_anchor_ids=["title", "left-column", "right-column"],
    )

    assert metrics["pairwise_order_accuracy"] == pytest.approx(1.0)
    assert metrics["anchor_coverage"] == pytest.approx(2 / 3)


def test_tables_match_by_page_and_ordinal_then_cell_coordinates() -> None:
    reference = [
        {
            "page": 2,
            "ordinal": 1,
            "cells": [
                {"row": 0, "column": 0, "text": "Item"},
                {"row": 0, "column": 1, "text": "Count"},
            ],
        }
    ]
    candidate = [
        {
            "page": 2,
            "ordinal": 1,
            "cells": [
                {"row": 0, "column": 0, "text": "Item"},
                {"row": 0, "column": 1, "text": "Total"},
            ],
        },
        {"page": 2, "ordinal": 0, "cells": []},
    ]

    metrics = table_cell_metrics(candidate, reference)

    assert metrics["matched_tables"] == 1
    assert metrics["table_coverage"] == pytest.approx(1.0)
    assert metrics["cell_exact_accuracy"] == pytest.approx(0.5)


def test_grounding_reports_mean_iou_and_recall_at_half_overlap() -> None:
    metrics = grounding_metrics(
        candidate_regions={
            "a": [0.0, 0.0, 1.0, 1.0],
            "b": [0.0, 0.0, 0.25, 0.25],
        },
        reference_regions={
            "a": [0.0, 0.0, 1.0, 1.0],
            "b": [0.0, 0.0, 0.5, 0.5],
        },
    )

    assert metrics["mean_iou"] == pytest.approx(0.625)
    assert metrics["recall_at_0_5"] == pytest.approx(0.5)


def test_schema_leaf_comparison_requires_pointer_value_and_json_type() -> None:
    metrics = schema_leaf_metrics(
        candidate={"amount": "2", "ok": True, "extra": None},
        reference={"amount": 2, "ok": True},
    )

    assert metrics["exact_matches"] == 1
    assert metrics["exact_match"] is False
    assert metrics["precision"] == pytest.approx(1 / 3)
    assert metrics["recall"] == pytest.approx(0.5)
    assert metrics["f1"] == pytest.approx(0.4)


def test_cross_page_continuity_uses_pair_precision_recall_and_f1() -> None:
    metrics = continuity_metrics(
        candidate_pairs=[("p1-table", "p2-table"), ("extra", "link")],
        reference_pairs=[("p1-table", "p2-table"), ("p2-table", "p3-table")],
    )

    assert metrics == {"precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_hallucination_separates_insertions_forbidden_rejections_and_false_accepts() -> (
    None
):
    metrics = hallucination_metrics(
        candidate_text="alpha beta invented",
        reference_text="alpha beta",
        forbidden_literals=["invented", "secret"],
        rejected_block_ids=["r1", "r2"],
        accepted_block_ids=["r1", "kept"],
    )

    assert metrics == {
        "word_insertions": 1,
        "candidate_words": 3,
        "hallucination_rate": pytest.approx(1 / 3),
        "forbidden_literal_count": 1,
        "rejected_block_count": 2,
        "false_accept_count": 1,
        "false_accept_rate": pytest.approx(0.5),
    }


def test_telemetry_uses_median_nearest_rank_and_optional_rate_card() -> None:
    records = [
        {
            "latency_seconds": 1.0,
            "pages": 1,
            "input_tokens": 100,
            "output_tokens": 50,
            "full_page_fallbacks": 0,
            "model_usage": {
                "luna": {"calls": 1, "input_tokens": 100, "output_tokens": 50}
            },
        },
        {
            "latency_seconds": 2.0,
            "pages": 2,
            "input_tokens": 200,
            "output_tokens": 100,
            "full_page_fallbacks": 1,
            "model_usage": {
                "luna": {"calls": 2, "input_tokens": 200, "output_tokens": 100},
            },
        },
        {
            "latency_seconds": 100.0,
            "pages": 1,
            "input_tokens": 10,
            "output_tokens": 10,
            "full_page_fallbacks": 2,
            "model_usage": {
                "unpriced": {"calls": 2, "input_tokens": 10, "output_tokens": 10}
            },
        },
    ]
    rate_card = {
        "schema_version": "1.0",
        "models": {"luna": {"input_per_million": 2.0, "output_per_million": 4.0}},
    }

    metrics = summarize_telemetry(records, rate_card=rate_card)

    assert metrics["latency_seconds"] == {"p50": 2.0, "p95": 100.0}
    assert metrics["input_tokens"] == 310
    assert metrics["output_tokens"] == 160
    assert metrics["model_calls"] == 5
    assert metrics["full_page_fallbacks"] == 3
    assert metrics["cost_per_page"] is None
    assert "unpriced" in metrics["cost_unavailable_reason"]


def test_telemetry_cost_aggregates_luna_usage_per_page() -> None:
    metrics = summarize_telemetry(
        [
            {
                "latency_seconds": 2.0,
                "pages": 2,
                "input_tokens": 300,
                "output_tokens": 100,
                "full_page_fallbacks": 1,
                "model_usage": {
                    "luna": {"calls": 3, "input_tokens": 300, "output_tokens": 100},
                },
            }
        ],
        rate_card={
            "schema_version": "1.0",
            "models": {
                "luna": {"input_per_million": 2.0, "output_per_million": 4.0},
            },
        },
    )

    assert metrics["model_calls"] == 3
    assert metrics["cost_per_page"] == pytest.approx(0.0005)
    assert metrics["cost_unavailable_reason"] is None
