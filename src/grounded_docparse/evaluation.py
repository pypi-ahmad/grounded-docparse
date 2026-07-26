from __future__ import annotations

import unicodedata
from collections import Counter
from itertools import combinations
from typing import Any

from pydantic import BaseModel, Field

from .models import BoundingBox, DocumentNode, DocumentTree, NodeType

MAX_GOLD_BYTES = 25 * 1024 * 1024


class EvaluationDiscrepancy(BaseModel):
    kind: str
    gold_node_id: str | None = None
    candidate_node_id: str | None = None
    page_number: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    schema_version: str = "1.0.0"
    document_id: str
    source_sha256: str
    candidate_schema_version: str
    gold_schema_version: str
    matched_nodes: int
    unmatched_candidate_nodes: int
    unmatched_gold_nodes: int
    metrics: dict[str, Any]
    per_type: dict[str, dict[str, float | int]]
    discrepancies: list[EvaluationDiscrepancy] = Field(default_factory=list)


def load_gold_tree(data: bytes) -> DocumentTree:
    if len(data) > MAX_GOLD_BYTES:
        raise ValueError("Gold JSON exceeds the 25 MB limit")
    try:
        tree = DocumentTree.model_validate_json(data)
    except Exception as exc:
        raise ValueError("Gold JSON is not a valid document tree") from exc
    _validate_tree(tree)
    return tree


def _validate_tree(tree: DocumentTree) -> None:
    node_ids = set(tree.nodes)
    page_numbers = {page.number for page in tree.pages}
    if tree.root_id not in node_ids:
        raise ValueError("Gold tree root does not exist")
    for page in tree.pages:
        if page.id not in node_ids or any(item not in node_ids for item in page.content_node_ids):
            raise ValueError("Gold tree page contains a dangling node reference")
    for node in tree.nodes.values():
        if node.parent_id and node.parent_id not in node_ids:
            raise ValueError("Gold tree contains a dangling parent reference")
        if any(child not in node_ids for child in node.children_ids):
            raise ValueError("Gold tree contains a dangling child reference")
        for child_id in node.children_ids:
            if tree.nodes[child_id].parent_id != node.id:
                raise ValueError("Gold tree contains a non-reciprocal child reference")
        seen: set[str] = set()
        current = node
        while current.parent_id:
            if current.id in seen:
                raise ValueError("Gold tree contains a hierarchy cycle")
            seen.add(current.id)
            current = tree.nodes[current.parent_id]
        if node.visual_analysis and any(
            source_id not in node_ids
            for source_id in node.visual_analysis.source_node_ids
        ):
            raise ValueError("Gold tree contains an unknown visual source")
    for field in tree.grounded_fields:
        if any(source_id not in node_ids for source_id in field.source_node_ids):
            raise ValueError("Gold tree contains an unknown field source")
        if any(source.node_id not in node_ids for source in field.sources):
            raise ValueError("Gold tree contains an unknown field source")
    for failure in tree.failure_cases:
        if any(node_id not in node_ids for node_id in failure.node_ids):
            raise ValueError("Gold tree contains an unknown failure source")
        if failure.page_number is not None and failure.page_number not in page_numbers:
            raise ValueError("Gold tree contains an unknown failure page")


def _content_nodes(tree: DocumentTree) -> dict[str, DocumentNode]:
    return {
        node_id: tree.nodes[node_id]
        for page in tree.pages
        for node_id in page.content_node_ids
    }


def _iou(left: BoundingBox | None, right: BoundingBox | None) -> float:
    if left is None or right is None or left.unit != right.unit:
        return 0.0
    x0 = max(left.x0, right.x0)
    y0 = max(left.y0, right.y0)
    x1 = min(left.x1, right.x1)
    y1 = min(left.y1, right.y1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = max(0.0, left.x1 - left.x0) * max(0.0, left.y1 - left.y0)
    right_area = max(0.0, right.x1 - right.x0) * max(0.0, right.y1 - right.y0)
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _match_nodes(
    candidate: dict[str, DocumentNode], gold: dict[str, DocumentNode]
) -> dict[str, str]:
    matches = {node_id: node_id for node_id in candidate.keys() & gold.keys()}
    candidate_left = set(candidate) - set(matches.values())
    gold_left = set(gold) - set(matches)
    pairs: list[tuple[float, str, str]] = []
    for gold_id in gold_left:
        gold_node = gold[gold_id]
        for candidate_id in candidate_left:
            candidate_node = candidate[candidate_id]
            if candidate_node.page_number != gold_node.page_number:
                continue
            score = _iou(candidate_node.bbox, gold_node.bbox)
            if score >= 0.5:
                pairs.append((score, gold_id, candidate_id))
    used_gold: set[str] = set()
    used_candidate: set[str] = set()
    for _, gold_id, candidate_id in sorted(
        pairs, key=lambda item: (-item[0], item[1], item[2])
    ):
        if gold_id in used_gold or candidate_id in used_candidate:
            continue
        matches[gold_id] = candidate_id
        used_gold.add(gold_id)
        used_candidate.add(candidate_id)
    return matches


def _normalize(text: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").split())


def _edit_distance(left: list[str], right: list[str]) -> int:
    if not left:
        return len(right)
    if not right:
        return len(left)
    if len(left) > len(right):
        left, right = right, left
    masks: dict[str, int] = {}
    for index, item in enumerate(left):
        masks[item] = masks.get(item, 0) | (1 << index)
    positive = ~0
    negative = 0
    score = len(left)
    final_bit = 1 << (len(left) - 1)
    for item in right:
        equal = masks.get(item, 0)
        combined = equal | negative
        horizontal = (((equal & positive) + positive) ^ positive) | equal
        positive_horizontal = negative | ~(horizontal | positive)
        negative_horizontal = positive & horizontal
        if positive_horizontal & final_bit:
            score += 1
        elif negative_horizontal & final_bit:
            score -= 1
        positive_horizontal = (positive_horizontal << 1) | 1
        negative_horizontal <<= 1
        positive = negative_horizontal | ~(combined | positive_horizontal)
        negative = positive_horizontal & combined
    return score


def _rate(errors: int, reference_units: int, candidate_units: int) -> float:
    if reference_units:
        return errors / reference_units
    return 0.0 if candidate_units == 0 else 1.0


def _ancestor_path(tree: DocumentTree, node: DocumentNode) -> tuple[str, ...]:
    path: list[str] = []
    parent_id = node.parent_id
    ignored = {NodeType.DOCUMENT.value, NodeType.PAGE.value}
    while parent_id:
        parent = tree.nodes[parent_id]
        if parent.type not in ignored:
            label = _normalize(parent.text or parent.semantic_role).casefold()
            path.append(f"{parent.type}:{label}")
        parent_id = parent.parent_id
    return tuple(reversed(path))


def _segmentation_metrics(candidate: DocumentTree, gold: DocumentTree) -> dict[str, Any]:
    if gold.batch_manifest is None:
        return {"available": False}
    candidate_manifest = candidate.batch_manifest
    if candidate_manifest is None:
        return {
            "available": True,
            "boundary_precision": 0.0,
            "boundary_recall": 0.0,
            "boundary_f1": 0.0,
            "page_assignment_accuracy": 0.0,
            "document_type_accuracy": 0.0,
            "identifier_exact_match_recall": 0.0,
        }
    candidate_boundaries = {
        item.before_page for item in candidate_manifest.boundaries if item.decision == "split"
    }
    gold_boundaries = {
        item.before_page for item in gold.batch_manifest.boundaries if item.decision == "split"
    }
    correct = len(candidate_boundaries & gold_boundaries)
    precision = correct / len(candidate_boundaries) if candidate_boundaries else float(not gold_boundaries)
    recall = correct / len(gold_boundaries) if gold_boundaries else float(not candidate_boundaries)

    def page_map(manifest):
        return {
            page: descriptor
            for descriptor in manifest.subdocuments
            for page in range(descriptor.start_page, descriptor.end_page + 1)
        }

    candidate_pages = page_map(candidate_manifest)
    gold_pages = page_map(gold.batch_manifest)
    page_numbers = sorted(gold_pages)
    pairs = list(combinations(page_numbers, 2))
    assignment_correct = sum(
        (candidate_pages.get(left) is candidate_pages.get(right))
        == (gold_pages[left] is gold_pages[right])
        for left, right in pairs
    )
    type_correct = sum(
        page in candidate_pages
        and candidate_pages[page].profile == gold_pages[page].profile
        for page in page_numbers
    )
    gold_keys = {
        (item.start_page, item.end_page, item.instance_key)
        for item in gold.batch_manifest.subdocuments
        if item.instance_key
    }
    candidate_keys = {
        (item.start_page, item.end_page, item.instance_key)
        for item in candidate_manifest.subdocuments
        if item.instance_key
    }
    return {
        "available": True,
        "boundary_precision": precision,
        "boundary_recall": recall,
        "boundary_f1": 2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0,
        "page_assignment_accuracy": assignment_correct / len(pairs) if pairs else 1.0,
        "document_type_accuracy": type_correct / len(page_numbers) if page_numbers else 1.0,
        "identifier_exact_match_recall": len(candidate_keys & gold_keys) / len(gold_keys)
        if gold_keys
        else 1.0,
    }


def _schema_extraction_values(
    tree: DocumentTree,
) -> dict[tuple[str, str, str], tuple[Any, Any]]:
    values: dict[tuple[str, str, str], tuple[Any, Any]] = {}
    for extraction in tree.schema_extractions:
        identity = extraction.subdocument_id or extraction.document_id

        def walk(
            value: Any,
            pointer: str,
            identity: str = identity,
            extraction: Any = extraction,
        ) -> None:
            if isinstance(value, dict):
                for name, child in value.items():
                    escaped = name.replace("~", "~0").replace("/", "~1")
                    walk(child, f"{pointer}/{escaped}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{pointer}/{index}")
            else:
                values[(identity, extraction.schema_sha256, pointer)] = (
                    value,
                    extraction.provenance.get(pointer),
                )

        walk(extraction.data, "")
    return values


def _text_metrics(
    candidate: dict[str, DocumentNode],
    gold: dict[str, DocumentNode],
    matches: dict[str, str],
    unmatched_gold: list[str],
    unmatched_candidate: list[str],
) -> dict[str, float]:
    character_errors = word_errors = 0
    gold_characters = candidate_characters = 0
    gold_words = candidate_words = 0
    for gold_id, candidate_id in matches.items():
        gold_text = _normalize(gold[gold_id].text)
        candidate_text = _normalize(candidate[candidate_id].text)
        character_errors += _edit_distance(list(gold_text), list(candidate_text))
        word_errors += _edit_distance(gold_text.split(), candidate_text.split())
        gold_characters += len(gold_text)
        candidate_characters += len(candidate_text)
        gold_words += len(gold_text.split())
        candidate_words += len(candidate_text.split())
    for gold_id in unmatched_gold:
        text = _normalize(gold[gold_id].text)
        character_errors += len(text)
        word_errors += len(text.split())
        gold_characters += len(text)
        gold_words += len(text.split())
    for candidate_id in unmatched_candidate:
        text = _normalize(candidate[candidate_id].text)
        character_errors += len(text)
        word_errors += len(text.split())
        candidate_characters += len(text)
        candidate_words += len(text.split())
    return {
        "character_error_rate": _rate(
            character_errors, gold_characters, candidate_characters
        ),
        "word_error_rate": _rate(word_errors, gold_words, candidate_words),
    }


def _node_type_metrics(
    candidate: dict[str, DocumentNode],
    gold: dict[str, DocumentNode],
    matches: dict[str, str],
) -> tuple[dict[str, float], dict[str, dict[str, float | int]]]:
    gold_types = Counter(node.type for node in gold.values())
    candidate_types = Counter(node.type for node in candidate.values())
    true_types = Counter(
        gold[gold_id].type
        for gold_id, candidate_id in matches.items()
        if gold[gold_id].type == candidate[candidate_id].type
    )
    per_type: dict[str, dict[str, float | int]] = {}
    for node_type in sorted(gold_types.keys() | candidate_types.keys()):
        true_positive = true_types[node_type]
        predicted = candidate_types[node_type]
        expected = gold_types[node_type]
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / expected if expected else 0.0
        per_type[node_type] = {
            "true_positive": true_positive,
            "predicted": predicted,
            "expected": expected,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0,
        }
    total_true = sum(true_types.values())
    type_precision = total_true / len(candidate) if candidate else 0.0
    type_recall = total_true / len(gold) if gold else 0.0
    metrics = {
        "precision": type_precision,
        "recall": type_recall,
        "f1": 2 * type_precision * type_recall / (type_precision + type_recall)
        if type_precision + type_recall
        else 0.0,
    }
    return metrics, per_type


def _layout_metrics(
    candidate: dict[str, DocumentNode],
    gold: dict[str, DocumentNode],
    matches: dict[str, str],
) -> dict[str, float]:
    box_scores = [
        _iou(candidate[candidate_id].bbox, gold[gold_id].bbox)
        for gold_id, candidate_id in matches.items()
        if gold[gold_id].bbox is not None and candidate[candidate_id].bbox is not None
    ]
    gold_box_count = sum(node.bbox is not None for node in gold.values())
    return {
        "mean_bbox_iou": sum(box_scores) / len(box_scores) if box_scores else 0.0,
        "bbox_recall_at_0_5": sum(score >= 0.5 for score in box_scores)
        / gold_box_count
        if gold_box_count
        else 0.0,
    }


def _reading_order_metrics(
    candidate: dict[str, DocumentNode],
    gold: dict[str, DocumentNode],
    matches: dict[str, str],
) -> dict[str, float | int]:
    order_correct = order_total = 0
    for page_number in sorted({node.page_number for node in gold.values()}):
        page_matches = [
            (gold[gold_id], candidate[candidate_id])
            for gold_id, candidate_id in matches.items()
            if gold[gold_id].page_number == page_number
            and candidate[candidate_id].page_number == page_number
            and gold[gold_id].reading_order is not None
            and candidate[candidate_id].reading_order is not None
        ]
        for (gold_left, candidate_left), (gold_right, candidate_right) in combinations(
            page_matches, 2
        ):
            order_total += 1
            if (gold_left.reading_order < gold_right.reading_order) == (
                candidate_left.reading_order < candidate_right.reading_order
            ):
                order_correct += 1
    return {
        "pairwise_accuracy": order_correct / order_total if order_total else 1.0,
        "compared_pairs": order_total,
    }


def _hierarchy_metrics(
    candidate_tree: DocumentTree,
    gold_tree: DocumentTree,
    candidate: dict[str, DocumentNode],
    gold: dict[str, DocumentNode],
    matches: dict[str, str],
) -> dict[str, float]:
    hierarchy_correct = sum(
        _ancestor_path(candidate_tree, candidate[candidate_id])
        == _ancestor_path(gold_tree, gold[gold_id])
        for gold_id, candidate_id in matches.items()
    )
    return {"path_accuracy": hierarchy_correct / len(matches) if matches else 0.0}


def _document_profile_metrics(
    candidate_tree: DocumentTree, gold_tree: DocumentTree
) -> dict[str, float]:
    accuracy = float(
        candidate_tree.document_classification is not None
        and gold_tree.document_classification is not None
        and candidate_tree.document_classification.profile
        == gold_tree.document_classification.profile
    )
    return {"accuracy": accuracy}


def _grounded_field_metrics(
    candidate_tree: DocumentTree, gold_tree: DocumentTree
) -> dict[str, float]:
    candidate_fields = {field.path: field for field in candidate_tree.grounded_fields}
    gold_fields = {field.path: field for field in gold_tree.grounded_fields}
    correct_fields = sum(
        path in candidate_fields
        and _normalize(candidate_fields[path].normalized_value or candidate_fields[path].raw_value)
        == _normalize(field.normalized_value or field.raw_value)
        for path, field in gold_fields.items()
    )
    field_precision = (
        correct_fields / len(candidate_fields)
        if candidate_fields
        else (1.0 if not gold_fields else 0.0)
    )
    field_recall = (
        correct_fields / len(gold_fields)
        if gold_fields
        else (1.0 if not candidate_fields else 0.0)
    )
    return {
        "precision": field_precision,
        "recall": field_recall,
        "f1": 2 * field_precision * field_recall / (field_precision + field_recall)
        if field_precision + field_recall
        else 0.0,
    }


def _schema_extraction_metrics(
    candidate_tree: DocumentTree, gold_tree: DocumentTree
) -> dict[str, bool | float]:
    candidate_extractions = _schema_extraction_values(candidate_tree)
    gold_extractions = _schema_extraction_values(gold_tree)
    correct_extractions = sum(
        key in candidate_extractions and candidate_extractions[key][0] == value[0]
        for key, value in gold_extractions.items()
    )
    extraction_precision = (
        correct_extractions / len(candidate_extractions)
        if candidate_extractions
        else (1.0 if not gold_extractions else 0.0)
    )
    extraction_recall = (
        correct_extractions / len(gold_extractions)
        if gold_extractions
        else (1.0 if not candidate_extractions else 0.0)
    )
    extraction_box_ious: list[float] = []
    for key, (_, gold_provenance) in gold_extractions.items():
        candidate_value = candidate_extractions.get(key)
        if candidate_value is None or gold_provenance is None or candidate_value[1] is None:
            continue
        if not gold_provenance.citations or not candidate_value[1].citations:
            continue
        gold_box = gold_provenance.citations[0].bbox
        candidate_box = candidate_value[1].citations[0].bbox
        if gold_box is not None and candidate_box is not None:
            extraction_box_ious.append(_iou(candidate_box, gold_box))
    return {
        "available": bool(candidate_extractions or gold_extractions),
        "precision": extraction_precision,
        "recall": extraction_recall,
        "f1": (
            2
            * extraction_precision
            * extraction_recall
            / (extraction_precision + extraction_recall)
            if extraction_precision + extraction_recall
            else 0.0
        ),
        "citation_coverage": (
            sum(
                provenance is not None and bool(provenance.citations)
                for _, provenance in candidate_extractions.values()
            )
            / len(candidate_extractions)
            if candidate_extractions
            else 1.0
        ),
        "mean_bbox_iou": (
            sum(extraction_box_ious) / len(extraction_box_ious)
            if extraction_box_ious
            else 1.0
        ),
    }


def _visual_structure_metrics(
    candidate: dict[str, DocumentNode],
    gold: dict[str, DocumentNode],
    matches: dict[str, str],
) -> dict[str, float]:
    gold_visuals = [node for node in gold.values() if node.visual_analysis is not None]
    visual_matches = sum(
        candidate[candidate_id].visual_analysis is not None
        and candidate[candidate_id].type == gold[gold_id].type
        for gold_id, candidate_id in matches.items()
        if gold[gold_id].visual_analysis is not None
    )
    return {"node_recall": visual_matches / len(gold_visuals) if gold_visuals else 1.0}


def _relationship_metrics(
    candidate_tree: DocumentTree, gold_tree: DocumentTree
) -> dict[str, float]:
    gold_relationships = {
        (node.id, relationship.type, relationship.target_id)
        for node in gold_tree.nodes.values()
        for relationship in node.relationships
    }
    candidate_relationships = {
        (node.id, relationship.type, relationship.target_id)
        for node in candidate_tree.nodes.values()
        for relationship in node.relationships
    }
    overlap = len(candidate_relationships & gold_relationships)
    return {
        "precision": overlap / len(candidate_relationships)
        if candidate_relationships
        else (1.0 if not gold_relationships else 0.0),
        "recall": overlap / len(gold_relationships) if gold_relationships else 1.0,
    }


def _citation_metrics(candidate: dict[str, DocumentNode]) -> dict[str, float]:
    candidate_grounded = sum(bool(node.citations) for node in candidate.values())
    return {"coverage": candidate_grounded / len(candidate) if candidate else 1.0}


def _table_cell_metrics(
    candidate_tree: DocumentTree, gold_tree: DocumentTree
) -> dict[str, float]:
    gold_cells = {
        node.id: node
        for node in gold_tree.nodes.values()
        if node.type == NodeType.TABLE_CELL.value
    }
    cell_ious = [
        _iou(candidate_tree.nodes[node_id].bbox, node.bbox)
        for node_id, node in gold_cells.items()
        if node_id in candidate_tree.nodes
        and node.bbox is not None
        and candidate_tree.nodes[node_id].bbox is not None
    ]
    return {"mean_bbox_iou": sum(cell_ious) / len(cell_ious) if cell_ious else 1.0}


def _form_metrics(
    candidate_tree: DocumentTree, gold_tree: DocumentTree
) -> dict[str, float]:
    gold_forms = {
        node.id: node
        for node in gold_tree.nodes.values()
        if node.type in {NodeType.FORM_FIELD.value, NodeType.CHECKBOX.value}
    }
    correct_forms = sum(
        node_id in candidate_tree.nodes
        and candidate_tree.nodes[node_id].form_field is not None
        and candidate_tree.nodes[node_id].form_field.model_dump()
        == node.form_field.model_dump()
        for node_id, node in gold_forms.items()
        if node.form_field is not None
    )
    return {
        "exact_match_recall": correct_forms / len(gold_forms) if gold_forms else 1.0
    }


def _build_discrepancies(
    candidate: dict[str, DocumentNode],
    gold: dict[str, DocumentNode],
    matches: dict[str, str],
    unmatched_gold: list[str],
    unmatched_candidate: list[str],
) -> list[EvaluationDiscrepancy]:
    discrepancies: list[EvaluationDiscrepancy] = []
    for gold_id, candidate_id in matches.items():
        details: dict[str, Any] = {}
        if _normalize(gold[gold_id].text) != _normalize(candidate[candidate_id].text):
            details["text_mismatch"] = True
        if gold[gold_id].type != candidate[candidate_id].type:
            details["gold_type"] = gold[gold_id].type
            details["candidate_type"] = candidate[candidate_id].type
        score = _iou(candidate[candidate_id].bbox, gold[gold_id].bbox)
        if gold[gold_id].bbox is not None and score < 0.5:
            details["bbox_iou"] = score
        if details:
            discrepancies.append(
                EvaluationDiscrepancy(
                    kind="mismatch",
                    gold_node_id=gold_id,
                    candidate_node_id=candidate_id,
                    page_number=gold[gold_id].page_number,
                    details=details,
                )
            )
    discrepancies.extend(
        EvaluationDiscrepancy(
            kind="missing_candidate",
            gold_node_id=node_id,
            page_number=gold[node_id].page_number,
        )
        for node_id in unmatched_gold
    )
    discrepancies.extend(
        EvaluationDiscrepancy(
            kind="unexpected_candidate",
            candidate_node_id=node_id,
            page_number=candidate[node_id].page_number,
        )
        for node_id in unmatched_candidate
    )
    return discrepancies


def evaluate_tree(candidate_tree: DocumentTree, gold_tree: DocumentTree) -> EvaluationReport:
    _validate_tree(candidate_tree)
    _validate_tree(gold_tree)
    if candidate_tree.source_sha256 != gold_tree.source_sha256:
        raise ValueError("Candidate and gold trees refer to different source documents")

    candidate = _content_nodes(candidate_tree)
    gold = _content_nodes(gold_tree)
    matches = _match_nodes(candidate, gold)
    matched_candidate_ids = set(matches.values())
    unmatched_gold = sorted(set(gold) - set(matches))
    unmatched_candidate = sorted(set(candidate) - matched_candidate_ids)
    node_type_metrics, per_type = _node_type_metrics(candidate, gold, matches)

    return EvaluationReport(
        document_id=candidate_tree.document_id,
        source_sha256=candidate_tree.source_sha256,
        candidate_schema_version=candidate_tree.schema_version,
        gold_schema_version=gold_tree.schema_version,
        matched_nodes=len(matches),
        unmatched_candidate_nodes=len(unmatched_candidate),
        unmatched_gold_nodes=len(unmatched_gold),
        metrics={
            "text": _text_metrics(
                candidate, gold, matches, unmatched_gold, unmatched_candidate
            ),
            "node_type": node_type_metrics,
            "layout": _layout_metrics(candidate, gold, matches),
            "reading_order": _reading_order_metrics(candidate, gold, matches),
            "hierarchy": _hierarchy_metrics(
                candidate_tree, gold_tree, candidate, gold, matches
            ),
            "document_profile": _document_profile_metrics(candidate_tree, gold_tree),
            "grounded_fields": _grounded_field_metrics(candidate_tree, gold_tree),
            "schema_extraction": _schema_extraction_metrics(candidate_tree, gold_tree),
            "visual_structure": _visual_structure_metrics(candidate, gold, matches),
            "relationships": _relationship_metrics(candidate_tree, gold_tree),
            "citations": _citation_metrics(candidate),
            "table_cells": _table_cell_metrics(candidate_tree, gold_tree),
            "forms": _form_metrics(candidate_tree, gold_tree),
            "segmentation": _segmentation_metrics(candidate_tree, gold_tree),
        },
        per_type=per_type,
        discrepancies=_build_discrepancies(
            candidate, gold, matches, unmatched_gold, unmatched_candidate
        ),
    )
