from __future__ import annotations

import pytest

from grounded_docparse import (
    DocumentParser,
    ParserConfig,
    evaluate_tree,
    load_gold_tree,
)
from grounded_docparse.models import BoundingBox, NodeType


def offline_parser() -> DocumentParser:
    return DocumentParser(
        ParserConfig(
            enable_paddle=False,
            enable_glm=False,
            enable_openai=False,
            render_dpi=150,
        )
    )


def test_identical_tree_has_perfect_metrics(simple_pdf: bytes) -> None:
    tree = offline_parser().parse(simple_pdf, "test.pdf").tree
    report = evaluate_tree(tree, tree.model_copy(deep=True))
    assert report.metrics["text"]["character_error_rate"] == 0
    assert report.metrics["text"]["word_error_rate"] == 0
    assert report.metrics["node_type"]["f1"] == 1
    assert report.metrics["layout"]["mean_bbox_iou"] == 1
    assert report.metrics["reading_order"]["pairwise_accuracy"] == 1
    assert report.metrics["hierarchy"]["path_accuracy"] == 1
    assert report.metrics["document_profile"]["accuracy"] == 1
    assert report.metrics["grounded_fields"]["f1"] == 1
    assert report.metrics["visual_structure"]["node_recall"] == 1
    assert report.metrics["relationships"]["precision"] == 1
    assert report.metrics["segmentation"]["boundary_f1"] == 1
    assert report.metrics["segmentation"]["page_assignment_accuracy"] == 1


def test_metrics_detect_text_type_box_order_and_hierarchy_errors(simple_pdf: bytes) -> None:
    gold = offline_parser().parse(simple_pdf, "test.pdf").tree
    candidate = gold.model_copy(deep=True)
    content_ids = candidate.pages[0].content_node_ids
    first = candidate.nodes[content_ids[0]]
    second = candidate.nodes[content_ids[1]]
    first.text = "Incorrect transcription"
    first.type = NodeType.FORMULA.value
    first.bbox = BoundingBox(x0=0, y0=0, x1=0.01, y1=0.01)
    first.reading_order, second.reading_order = second.reading_order, first.reading_order
    old_parent = candidate.nodes[first.parent_id]
    old_parent.children_ids.remove(first.id)
    first.parent_id = candidate.root_id
    candidate.nodes[candidate.root_id].children_ids.append(first.id)

    report = evaluate_tree(candidate, gold)
    assert report.metrics["text"]["character_error_rate"] > 0
    assert report.metrics["node_type"]["f1"] < 1
    assert report.metrics["layout"]["mean_bbox_iou"] < 1
    assert report.metrics["reading_order"]["pairwise_accuracy"] < 1
    assert report.metrics["hierarchy"]["path_accuracy"] < 1
    assert report.discrepancies


def test_gold_loader_rejects_invalid_graph_and_source_mismatch(
    simple_pdf: bytes, monkeypatch
) -> None:
    tree = offline_parser().parse(simple_pdf, "test.pdf").tree
    invalid = tree.model_copy(deep=True)
    invalid.nodes[invalid.pages[0].content_node_ids[0]].parent_id = "missing"
    with pytest.raises(ValueError, match="dangling parent"):
        load_gold_tree(invalid.model_dump_json().encode())

    other = tree.model_copy(deep=True)
    other.source_sha256 = "0" * 64
    with pytest.raises(ValueError, match="different source"):
        evaluate_tree(tree, other)

    monkeypatch.setattr("grounded_docparse.evaluation.MAX_GOLD_BYTES", 10)
    with pytest.raises(ValueError, match="25 MB"):
        load_gold_tree(b" " * 11)


def test_unmatched_nodes_preserve_discrepancy_order_and_empty_metric_defaults(
    simple_pdf: bytes,
) -> None:
    gold = offline_parser().parse(simple_pdf, "test.pdf").tree
    candidate = gold.model_copy(deep=True)
    field_source_ids = {
        source_id
        for field in candidate.grounded_fields
        for source_id in field.source_node_ids
    }
    original_id = next(
        node_id
        for node_id in candidate.pages[0].content_node_ids
        if node_id not in field_source_ids
    )
    node = candidate.nodes.pop(original_id)
    replacement_id = "unexpected-candidate-node"
    node.id = replacement_id
    node.bbox = None
    content_ids = candidate.pages[0].content_node_ids
    content_ids[content_ids.index(original_id)] = replacement_id
    parent = candidate.nodes[node.parent_id]
    parent.children_ids[parent.children_ids.index(original_id)] = replacement_id
    candidate.nodes[replacement_id] = node

    report = evaluate_tree(candidate, gold)

    unmatched = [item for item in report.discrepancies if item.kind != "mismatch"]
    assert [item.kind for item in unmatched] == [
        "missing_candidate",
        "unexpected_candidate",
    ]
    assert unmatched[0].gold_node_id == original_id
    assert unmatched[1].candidate_node_id == replacement_id
    assert report.metrics["schema_extraction"] == {
        "available": False,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "citation_coverage": 1.0,
        "mean_bbox_iou": 1.0,
    }
