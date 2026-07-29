from __future__ import annotations

import hashlib
import math
import re
import statistics
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Block, Document, VerificationState

CORPUS_SCHEMA_VERSION = "1.0"
ANNOTATION_SCHEMA_VERSION = "1.1"


class ReferenceBasis(StrEnum):
    SOURCE_VERIFIED = "source_verified"
    SYNTHETIC_EXACT = "synthetic_exact"
    GENERATED = "generated"

    @property
    def is_primary(self) -> bool:
        return self in {self.SOURCE_VERIFIED, self.SYNTHETIC_EXACT}


class EvaluationAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class EvaluationTableCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    text: str
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)


class EvaluationTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    ordinal: int = Field(ge=0)
    cells: list[EvaluationTableCell] = Field(default_factory=list)


class CorpusAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    document_id: str
    reference_text: str | None = None
    reference_basis: ReferenceBasis | None = None
    reference_pages: dict[int, str] = Field(default_factory=dict)
    anchors: list[EvaluationAnchor] = Field(default_factory=list)
    tables: list[EvaluationTable] = Field(default_factory=list)
    grounding_regions: dict[str, tuple[float, float, float, float]] = Field(
        default_factory=dict
    )
    schema_output: dict[str, Any] | None = None
    continuity_pairs: list[tuple[str, str]] = Field(default_factory=list)
    forbidden_literals: list[str] = Field(default_factory=list)
    rejected_block_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_anchor_ids(self) -> CorpusAnnotation:
        ids = [anchor.id for anchor in self.anchors]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate anchor id")
        if self.schema_version != ANNOTATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported annotation schema version: {self.schema_version}"
            )
        if any(page < 1 for page in self.reference_pages):
            raise ValueError("reference page numbers must be positive")
        return self


class CorpusSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["local", "external"]
    path: str
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_local_checksum(self) -> CorpusSource:
        if self.kind == "local" and self.sha256 is None:
            raise ValueError("local source requires a sha256 checksum")
        return self


class CorpusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str
    source: CorpusSource
    annotation_path: str | None = None
    features: list[str] = Field(default_factory=list)
    synthetic: bool
    annotation: CorpusAnnotation | None = Field(default=None, exclude=True)
    source_path: Path | None = Field(default=None, exclude=True)


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    annotation_schema_version: str
    corpus_id: str
    documents: list[CorpusDocument]

    @model_validator(mode="after")
    def validate_versions_and_ids(self) -> CorpusManifest:
        if self.schema_version != CORPUS_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported manifest schema version: {self.schema_version}"
            )
        ids = [document.id for document in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate document id")
        return self


class ModelRate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)


class ModelRateCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    models: dict[str, ModelRate]


def _repository_path(repository_root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"repository path traversal is not allowed: {value}")
    root = repository_root.resolve()
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"repository path traversal is not allowed: {value}")
    return resolved


def load_corpus_manifest(
    path: Path, *, repository_root: Path | None = None
) -> CorpusManifest:
    root = (repository_root or Path.cwd()).resolve()
    manifest_path = path.resolve()
    if not manifest_path.is_relative_to(root):
        raise ValueError("manifest must be inside the repository root")
    manifest = CorpusManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    for document in manifest.documents:
        if document.annotation_path is not None:
            annotation_path = _repository_path(root, document.annotation_path)
            if not annotation_path.is_file():
                raise ValueError(
                    f"annotation does not exist: {document.annotation_path}"
                )
            annotation = CorpusAnnotation.model_validate_json(
                annotation_path.read_text(encoding="utf-8")
            )
            if annotation.schema_version != manifest.annotation_schema_version:
                raise ValueError(
                    "annotation schema version does not match manifest: "
                    f"{annotation.schema_version} != {manifest.annotation_schema_version}"
                )
            if annotation.document_id != document.id:
                raise ValueError(
                    f"annotation document id {annotation.document_id} does not match "
                    f"manifest id {document.id}"
                )
            document.annotation = annotation
        if document.source.kind == "external":
            continue
        source_path = _repository_path(root, document.source.path)
        if not source_path.is_file():
            raise ValueError(f"local source does not exist: {document.source.path}")
        actual_checksum = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if actual_checksum != document.source.sha256:
            raise ValueError(
                f"checksum mismatch for {document.id}: "
                f"{actual_checksum} != {document.source.sha256}"
            )
        document.source_path = source_path
    return manifest


def _semantic_normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _semantic_words(value: str) -> list[str]:
    return re.findall(
        r"\w+(?:[-'’]\w+)*", _semantic_normalize(value).casefold(), re.UNICODE
    )


def semantic_text_metrics(candidate: str, reference: str) -> dict[str, float]:
    candidate_characters = list(_semantic_normalize(candidate))
    reference_characters = list(_semantic_normalize(reference))
    character_accuracy, character_error_rate = _sequence_metrics(
        candidate_characters, reference_characters
    )
    word_accuracy, word_error_rate = _sequence_metrics(
        _semantic_words(candidate), _semantic_words(reference)
    )
    return {
        "character_accuracy": character_accuracy / 100,
        "character_error_rate": character_error_rate / 100,
        "word_accuracy": word_accuracy / 100,
        "word_error_rate": word_error_rate / 100,
    }


def _canonical_block_text(block: Block, *, recognized_text_only: bool = False) -> str:
    if block.table is not None:
        return " ".join(
            cell.text
            for cell in sorted(
                block.table.cells,
                key=lambda item: (item.row, item.column),
            )
            if cell.text
        )
    if block.text and not recognized_text_only:
        prefix = f"{block.list_marker} " if block.list_marker else ""
        return f"{prefix}{block.text}"
    values: list[str] = []
    if block.text:
        prefix = f"{block.list_marker} " if block.list_marker else ""
        values.append(f"{prefix}{block.text}")
    if block.form is not None:
        values.extend((block.form.label, block.form.value or "", block.form.hint or ""))
    values.extend((block.checkbox_group or "", block.checkbox_option or ""))
    values.append(block.caption or "")
    if not recognized_text_only:
        values.append(block.figure_description or "")
    values.extend(
        f"{point.series + ' ' if point.series else ''}{point.label}: {point.value}"
        for point in block.chart_data
    )
    if recognized_text_only:
        represented = _semantic_normalize(" ".join(values)).casefold()
        for atom in block.atoms:
            normalized = _semantic_normalize(atom.text)
            if normalized and normalized.casefold() not in represented:
                values.append(atom.text)
                represented = _semantic_normalize(" ".join(values)).casefold()
    return " ".join(value for value in values if value)


def canonical_document_pages(
    document: Document, *, recognized_text_only: bool = False
) -> list[str]:
    pages: list[str] = []
    for page in document.pages:
        blocks = sorted(_flatten(page.blocks), key=lambda item: item.reading_order)
        pages.append(
            "\n".join(
                text
                for block in blocks
                if block.verification is not VerificationState.REJECTED
                and (
                    text := _canonical_block_text(
                        block, recognized_text_only=recognized_text_only
                    ).strip()
                )
            )
        )
    return pages


def semantic_text_metrics_for_reference_pages(
    candidate_pages: list[str],
    reference_pages: dict[int, str],
    *,
    source_page_numbers: list[int] | None = None,
) -> dict[str, float | int | list[int]]:
    selected_pages = sorted(reference_pages)
    candidate_numbers = source_page_numbers or list(range(1, len(candidate_pages) + 1))
    if len(candidate_numbers) != len(candidate_pages):
        raise ValueError("source page mapping must match candidate page count")
    candidates_by_page = dict(zip(candidate_numbers, candidate_pages, strict=True))
    selected_pages = [page for page in selected_pages if page in candidates_by_page]
    if not selected_pages:
        return _unavailable("no annotated reference pages are present in this run")
    metrics = semantic_text_metrics_by_page(
        [candidates_by_page[page] for page in selected_pages],
        "<!-- PAGE BREAK -->".join(reference_pages[page] for page in selected_pages),
    )
    metrics["scored_pages"] = selected_pages
    return metrics


def _aggregate_sequence_metrics(
    candidate_pages: list[list[str]], reference_pages: list[list[str]]
) -> tuple[float, float]:
    reference_size = sum(len(page) for page in reference_pages)
    candidate_size = sum(len(page) for page in candidate_pages)
    if reference_size == 0:
        return (
            1.0 if candidate_size == 0 else 0.0,
            0.0 if candidate_size == 0 else 1.0,
        )
    distance = sum(
        _edit_distance(candidate, reference)
        for candidate, reference in zip(candidate_pages, reference_pages, strict=True)
    )
    return max(0.0, 1 - distance / reference_size), distance / reference_size


def semantic_text_metrics_by_page(
    candidate_pages: list[str], reference: str
) -> dict[str, float | int]:
    reference_pages = reference.split("<!-- PAGE BREAK -->")
    if len(reference_pages) != len(candidate_pages) or len(reference_pages) == 1:
        return {
            **semantic_text_metrics("\n".join(candidate_pages), reference),
            "page_count": 1,
        }
    character_accuracy, character_error_rate = _aggregate_sequence_metrics(
        [list(_semantic_normalize(page)) for page in candidate_pages],
        [list(_semantic_normalize(page)) for page in reference_pages],
    )
    word_accuracy, word_error_rate = _aggregate_sequence_metrics(
        [_semantic_words(page) for page in candidate_pages],
        [_semantic_words(page) for page in reference_pages],
    )
    return {
        "character_accuracy": character_accuracy,
        "character_error_rate": character_error_rate,
        "word_accuracy": word_accuracy,
        "word_error_rate": word_error_rate,
        "page_count": len(reference_pages),
    }


def reading_order_metrics(
    candidate_anchor_ids: list[str], reference_anchor_ids: list[str]
) -> dict[str, float]:
    reference_positions = {
        anchor_id: index for index, anchor_id in enumerate(reference_anchor_ids)
    }
    candidate = list(
        dict.fromkeys(
            anchor_id
            for anchor_id in candidate_anchor_ids
            if anchor_id in reference_positions
        )
    )
    candidate_positions = {
        anchor_id: index for index, anchor_id in enumerate(candidate)
    }
    pairs = [
        (left, right)
        for left_index, left in enumerate(reference_anchor_ids)
        for right in reference_anchor_ids[left_index + 1 :]
        if left in candidate_positions and right in candidate_positions
    ]
    correct = sum(
        candidate_positions[left] < candidate_positions[right] for left, right in pairs
    )
    return {
        "pairwise_order_accuracy": correct / len(pairs) if pairs else 1.0,
        "anchor_coverage": len(candidate) / len(reference_anchor_ids)
        if reference_anchor_ids
        else 1.0,
    }


def table_cell_metrics(
    candidate: list[dict[str, Any]], reference: list[dict[str, Any]]
) -> dict[str, float | int]:
    candidate_tables = {
        (int(table["page"]), int(table["ordinal"])): table for table in candidate
    }
    matched_tables = 0
    matched_cells = 0
    reference_cells = 0
    for reference_table in reference:
        table_key = (int(reference_table["page"]), int(reference_table["ordinal"]))
        candidate_table = candidate_tables.get(table_key)
        if candidate_table is not None:
            matched_tables += 1
        candidate_cells = {
            (int(cell["row"]), int(cell["column"])): (
                _semantic_normalize(str(cell["text"])),
                int(cell.get("row_span", 1)),
                int(cell.get("column_span", 1)),
            )
            for cell in (candidate_table or {}).get("cells", [])
        }
        for cell in reference_table.get("cells", []):
            reference_cells += 1
            key = (int(cell["row"]), int(cell["column"]))
            expected = (
                _semantic_normalize(str(cell["text"])),
                int(cell.get("row_span", 1)),
                int(cell.get("column_span", 1)),
            )
            matched_cells += candidate_cells.get(key) == expected
    return {
        "matched_tables": matched_tables,
        "table_coverage": matched_tables / len(reference) if reference else 1.0,
        "cell_exact_accuracy": matched_cells / reference_cells
        if reference_cells
        else 1.0,
    }


def _intersection_over_union(
    candidate: list[float] | tuple[float, float, float, float],
    reference: list[float] | tuple[float, float, float, float],
) -> float:
    candidate_x0, candidate_y0, candidate_x1, candidate_y1 = candidate
    reference_x0, reference_y0, reference_x1, reference_y1 = reference
    intersection_width = max(
        0.0, min(candidate_x1, reference_x1) - max(candidate_x0, reference_x0)
    )
    intersection_height = max(
        0.0, min(candidate_y1, reference_y1) - max(candidate_y0, reference_y0)
    )
    intersection = intersection_width * intersection_height
    candidate_area = max(0.0, candidate_x1 - candidate_x0) * max(
        0.0, candidate_y1 - candidate_y0
    )
    reference_area = max(0.0, reference_x1 - reference_x0) * max(
        0.0, reference_y1 - reference_y0
    )
    union = candidate_area + reference_area - intersection
    return intersection / union if union else 0.0


def grounding_metrics(
    candidate_regions: dict[str, list[float]],
    reference_regions: dict[str, list[float]],
) -> dict[str, float]:
    overlaps = [
        _intersection_over_union(candidate_regions.get(region_id, [0, 0, 0, 0]), box)
        for region_id, box in reference_regions.items()
    ]
    return {
        "mean_iou": statistics.fmean(overlaps) if overlaps else 1.0,
        "recall_at_0_5": sum(overlap >= 0.5 for overlap in overlaps) / len(overlaps)
        if overlaps
        else 1.0,
    }


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError(f"unsupported JSON leaf type: {type(value).__name__}")


def _json_leaves(value: Any, pointer: str = "") -> dict[str, tuple[str, Any]]:
    if isinstance(value, dict):
        leaves: dict[str, tuple[str, Any]] = {}
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            leaves.update(_json_leaves(child, f"{pointer}/{escaped}"))
        return leaves
    if isinstance(value, list):
        leaves = {}
        for index, child in enumerate(value):
            leaves.update(_json_leaves(child, f"{pointer}/{index}"))
        return leaves
    return {pointer or "/": (_json_type(value), value)}


def schema_leaf_metrics(
    candidate: dict[str, Any], reference: dict[str, Any]
) -> dict[str, bool | float | int]:
    candidate_leaves = _json_leaves(candidate)
    reference_leaves = _json_leaves(reference)
    exact_matches = sum(
        candidate_leaves.get(pointer) == leaf
        for pointer, leaf in reference_leaves.items()
    )
    precision = exact_matches / len(candidate_leaves) if candidate_leaves else 0.0
    recall = exact_matches / len(reference_leaves) if reference_leaves else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "exact_matches": exact_matches,
        "exact_match": candidate_leaves == reference_leaves,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def continuity_metrics(
    candidate_pairs: list[tuple[str, str]], reference_pairs: list[tuple[str, str]]
) -> dict[str, float]:
    candidate = set(candidate_pairs)
    reference = set(reference_pairs)
    matches = len(candidate & reference)
    precision = matches / len(candidate) if candidate else 0.0
    recall = matches / len(reference) if reference else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0,
    }


def _word_insertions(candidate: list[str], reference: list[str]) -> int:
    previous = [(index, 0) for index in range(len(reference) + 1)]
    for candidate_index, candidate_word in enumerate(candidate, 1):
        current = [(candidate_index, candidate_index)]
        for reference_index, reference_word in enumerate(reference, 1):
            choices = [
                (current[-1][0] + 1, current[-1][1]),
                (previous[reference_index][0] + 1, previous[reference_index][1] + 1),
                (
                    previous[reference_index - 1][0]
                    + (candidate_word != reference_word),
                    previous[reference_index - 1][1],
                ),
            ]
            current.append(min(choices))
        previous = current
    return previous[-1][1]


def hallucination_metrics(
    *,
    candidate_text: str,
    reference_text: str,
    forbidden_literals: list[str],
    rejected_block_ids: list[str],
    accepted_block_ids: list[str],
) -> dict[str, float | int]:
    candidate_words = _semantic_words(candidate_text)
    insertions = _word_insertions(candidate_words, _semantic_words(reference_text))
    normalized_candidate = _semantic_normalize(candidate_text).casefold()
    rejected = set(rejected_block_ids)
    false_accept_count = len(rejected & set(accepted_block_ids))
    return {
        "word_insertions": insertions,
        "candidate_words": len(candidate_words),
        "hallucination_rate": insertions / len(candidate_words)
        if candidate_words
        else 0.0,
        "forbidden_literal_count": sum(
            _semantic_normalize(literal).casefold() in normalized_candidate
            for literal in forbidden_literals
        ),
        "rejected_block_count": len(rejected),
        "false_accept_count": false_accept_count,
        "false_accept_rate": false_accept_count / len(rejected) if rejected else 0.0,
    }


def summarize_telemetry(
    records: list[dict[str, Any]], *, rate_card: dict[str, Any] | None = None
) -> dict[str, Any]:
    latencies = sorted(float(record["latency_seconds"]) for record in records)
    model_usage: dict[str, dict[str, int]] = {}
    model_calls = 0
    for record in records:
        usage = record.get("model_usage")
        if usage is None:
            usage = {
                str(record["model"]): {
                    "calls": int(record.get("model_calls", 1)),
                    "input_tokens": int(record["input_tokens"]),
                    "output_tokens": int(record["output_tokens"]),
                }
            }
        for model, values in usage.items():
            totals = model_usage.setdefault(
                str(model), {"calls": 0, "input_tokens": 0, "output_tokens": 0}
            )
            for name in totals:
                totals[name] += int(values[name])
            model_calls += int(values["calls"])
    crop_area_ratios = sorted(
        float(ratio)
        for record in records
        for ratio in record.get("crop_area_ratios", [])
    )
    output: dict[str, Any] = {
        "latency_seconds": {
            "p50": statistics.median(latencies) if latencies else None,
            "p95": latencies[math.ceil(0.95 * len(latencies)) - 1]
            if latencies
            else None,
        },
        "input_tokens": sum(int(record["input_tokens"]) for record in records),
        "output_tokens": sum(int(record["output_tokens"]) for record in records),
        "model_calls": model_calls,
        "model_usage": model_usage,
        "full_page_fallbacks": sum(
            int(record.get("full_page_fallbacks", 0)) for record in records
        ),
        "full_page_calls": sum(
            int(record.get("full_page_calls", 0)) for record in records
        ),
        "crop_calls": sum(int(record.get("crop_calls", 0)) for record in records),
        "image_pixels": sum(int(record.get("image_pixels", 0)) for record in records),
        "crop_pixels": sum(int(record.get("crop_pixels", 0)) for record in records),
        "crop_area_ratio": {
            "p50": statistics.median(crop_area_ratios) if crop_area_ratios else None,
            "p95": crop_area_ratios[math.ceil(0.95 * len(crop_area_ratios)) - 1]
            if crop_area_ratios
            else None,
        },
        "full_page_equivalents": sum(
            float(record.get("full_page_equivalents", 0.0)) for record in records
        ),
        "repair_calls": sum(int(record.get("repair_calls", 0)) for record in records),
        "repaired_target_rate": (
            sum(int(record.get("repaired_targets", 0)) for record in records)
            / sum(int(record.get("blocks", 0)) for record in records)
            if sum(int(record.get("blocks", 0)) for record in records)
            else 0.0
        ),
    }
    if rate_card is None:
        output["cost_per_page"] = None
        output["cost_unavailable_reason"] = "no rate card supplied"
        return output
    rates = ModelRateCard.model_validate(rate_card)
    missing_models = sorted(model_usage.keys() - rates.models.keys())
    if missing_models:
        output["cost_per_page"] = None
        output["cost_unavailable_reason"] = "rate card has no rates for: " + ", ".join(
            missing_models
        )
        return output
    total_pages = sum(int(record["pages"]) for record in records)
    cost = sum(
        (
            usage["input_tokens"] * rates.models[model].input_per_million
            + usage["output_tokens"] * rates.models[model].output_per_million
        )
        / 1_000_000
        for model, usage in model_usage.items()
    )
    output["cost_per_page"] = cost / total_pages if total_pages else None
    output["cost_unavailable_reason"] = None if total_pages else "page count is zero"
    return output


def _macro_metrics(values: list[dict[str, Any]]) -> dict[str, Any]:
    available = [
        value for value in values if not ("value" in value and value["value"] is None)
    ]
    if not available:
        reasons = sorted(
            {
                str(value.get("reason"))
                for value in values
                if value.get("reason") is not None
            }
        )
        return _unavailable("; ".join(reasons) or "metric is not annotated")
    output: dict[str, Any] = {}
    keys = set().union(*(value.keys() for value in available))
    for key in sorted(keys):
        items = [value[key] for value in available if key in value]
        numeric = [float(item) for item in items if isinstance(item, (int, float))]
        if numeric:
            output[key] = statistics.fmean(numeric)
    return output


def _group_metrics(documents: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = sorted(
        set().union(*(document.get("metrics", {}).keys() for document in documents))
    )
    return {
        name: _macro_metrics(
            [
                document.get("metrics", {}).get(
                    name, _unavailable("metric is not annotated")
                )
                for document in documents
            ]
        )
        for name in metric_names
    }


def build_live_report(
    *,
    corpus_id: str,
    documents: list[dict[str, Any]],
    rate_card: dict[str, Any] | None,
) -> dict[str, Any]:
    classes: dict[str, Any] = {}
    features = sorted(
        {feature for document in documents for feature in document.get("features", [])}
    )
    for feature in features:
        members = [
            document
            for document in documents
            if feature in document.get("features", [])
        ]
        classes[feature] = {
            "document_ids": [document["id"] for document in members],
            "metrics": _group_metrics(members),
        }
    telemetry_records = [document["telemetry"] for document in documents]
    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_id": corpus_id,
        "evaluation_mode": "live_pipeline",
        "broad_production_claim": False,
        "aggregation": "macro mean by document",
        "documents": documents,
        "classes": classes,
        "aggregate": {"metrics": _group_metrics(documents)},
        "telemetry": summarize_telemetry(telemetry_records, rate_card=rate_card),
        "runtime": {
            "retries": sum(
                int(record.get("retries", 0)) for record in telemetry_records
            ),
            "rate_limit_events": sum(
                int(record.get("rate_limit_events", 0)) for record in telemetry_records
            ),
        },
        "limitations": [
            "Live model results are observations, not broad production accuracy claims.",
            "Unavailable metrics are retained with an explicit reason.",
            "DocVQA answer rate is not character, field, table-cell, or grounding accuracy.",
        ],
    }


def _candidate_tables(document: Document) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for page in document.pages:
        ordinal = 0
        for block in sorted(_flatten(page.blocks), key=lambda item: item.reading_order):
            if block.verification is VerificationState.REJECTED or block.table is None:
                continue
            tables.append(
                {
                    "page": page.number,
                    "ordinal": ordinal,
                    "cells": [
                        cell.model_dump(mode="json") for cell in block.table.cells
                    ],
                }
            )
            ordinal += 1
    return tables


def _candidate_anchor_ids(
    document: Document, annotation: CorpusAnnotation
) -> list[str]:
    remaining = list(annotation.anchors)
    found: list[str] = []
    for page in document.pages:
        for block in sorted(_flatten(page.blocks), key=lambda item: item.reading_order):
            if block.verification is VerificationState.REJECTED:
                continue
            text = _semantic_normalize(_canonical_block_text(block)).casefold()
            for anchor in list(remaining):
                if _semantic_normalize(anchor.text).casefold() in text:
                    found.append(anchor.id)
                    remaining.remove(anchor)
    return found


def _reference_basis(
    corpus_document: CorpusDocument,
    *,
    explicit_reference: bool,
    requested: ReferenceBasis | str | None,
) -> ReferenceBasis:
    if requested is not None:
        return ReferenceBasis(requested)
    annotation = corpus_document.annotation
    if not explicit_reference and annotation is not None and annotation.reference_basis:
        return annotation.reference_basis
    if explicit_reference:
        return ReferenceBasis.GENERATED
    if corpus_document.synthetic:
        return ReferenceBasis.SYNTHETIC_EXACT
    return ReferenceBasis.GENERATED


def evaluate_live_document(
    corpus_document: CorpusDocument,
    document: Document,
    *,
    telemetry: dict[str, Any],
    extraction_data: dict[str, Any] | None = None,
    reference_text: str | None = None,
    reference_is_markdown: bool = False,
    reference_basis: ReferenceBasis | str | None = None,
    source_page_numbers: list[int] | None = None,
    candidate_continuity_pairs: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    annotation = corpus_document.annotation
    reference = reference_text or (annotation.reference_text if annotation else None)
    reference_pages = (
        annotation.reference_pages
        if reference_text is None and annotation is not None
        else {}
    )
    basis = _reference_basis(
        corpus_document,
        explicit_reference=reference_text is not None,
        requested=reference_basis,
    )
    pages = canonical_document_pages(document)
    recognized_pages = canonical_document_pages(document, recognized_text_only=True)
    if reference_pages:
        semantic: dict[str, Any] = semantic_text_metrics_for_reference_pages(
            recognized_pages if basis.is_primary else pages,
            reference_pages,
            source_page_numbers=source_page_numbers,
        )
    elif reference is None:
        semantic = _unavailable("annotation has no reference text")
    else:
        semantic = semantic_text_metrics_by_page(
            recognized_pages if basis.is_primary else pages,
            reference,
        )
        if reference_is_markdown:
            semantic["character_accuracy"] = None
            semantic["character_error_rate"] = None
            semantic["character_unavailable_reason"] = (
                "reference contains Markdown presentation syntax"
            )
    semantic["reference_basis"] = basis.value
    source_verified = (
        semantic
        if basis.is_primary
        else _unavailable(f"reference basis {basis.value} is not source-verified")
    )
    legacy_agreement = (
        semantic
        if not basis.is_primary
        else _unavailable("no generated or legacy comparison reference supplied")
    )

    active_blocks = [
        block
        for page in document.pages
        for block in _flatten(page.blocks)
        if block.verification is not VerificationState.REJECTED
    ]
    all_blocks = [block for page in document.pages for block in _flatten(page.blocks)]
    candidate_text = "\n".join(pages)
    metrics: dict[str, Any] = {
        "semantic_text": semantic,
        "source_verified_text": source_verified,
        "legacy_reference_agreement": legacy_agreement,
    }
    if annotation is None or not annotation.anchors:
        metrics["reading_order"] = _unavailable(
            "annotation has no reading-order anchors"
        )
    else:
        metrics["reading_order"] = reading_order_metrics(
            _candidate_anchor_ids(document, annotation),
            [anchor.id for anchor in annotation.anchors],
        )
    if annotation is None or not annotation.tables:
        metrics["tables"] = _unavailable("annotation has no reference tables")
    else:
        metrics["tables"] = table_cell_metrics(
            _candidate_tables(document),
            [table.model_dump(mode="json") for table in annotation.tables],
        )
    if annotation is None or not annotation.grounding_regions:
        metrics["grounding"] = _unavailable("annotation has no grounding regions")
    else:
        candidate_regions = {
            block.id: block.bbox.model_dump(exclude={"unit"})
            for block in active_blocks
            if block.id in annotation.grounding_regions and block.bbox is not None
        }
        metrics["grounding"] = (
            grounding_metrics(
                candidate_regions=candidate_regions,
                reference_regions=annotation.grounding_regions,
            )
            if candidate_regions
            else _unavailable(
                "no stable candidate-region identifiers match the annotation"
            )
        )
    metrics["layout"] = metrics["grounding"]
    if annotation is None or annotation.schema_output is None:
        metrics["schema_fields"] = _unavailable("annotation has no schema output")
    elif extraction_data is None:
        metrics["schema_fields"] = _unavailable("live extraction result is unavailable")
    else:
        metrics["schema_fields"] = schema_leaf_metrics(
            extraction_data, annotation.schema_output
        )
    if annotation is None or not annotation.continuity_pairs:
        metrics["cross_page_continuity"] = _unavailable(
            "annotation has no cross-page continuity pairs"
        )
    else:
        metrics["cross_page_continuity"] = continuity_metrics(
            candidate_continuity_pairs or [], annotation.continuity_pairs
        )
    hallucination_reference = reference
    hallucination_candidate = candidate_text
    if reference_pages:
        selected_pages = sorted(reference_pages)
        candidate_numbers = source_page_numbers or list(range(1, len(pages) + 1))
        candidates_by_page = dict(zip(candidate_numbers, pages, strict=True))
        selected_pages = [page for page in selected_pages if page in candidates_by_page]
        hallucination_reference = "\n".join(
            reference_pages[page] for page in selected_pages
        )
        hallucination_candidate = "\n".join(
            candidates_by_page[page] for page in selected_pages
        )
    if hallucination_reference is None:
        metrics["hallucination"] = _unavailable("annotation has no reference text")
    else:
        metrics["hallucination"] = hallucination_metrics(
            candidate_text=hallucination_candidate,
            reference_text=hallucination_reference,
            forbidden_literals=annotation.forbidden_literals if annotation else [],
            rejected_block_ids=annotation.rejected_block_ids if annotation else [],
            accepted_block_ids=[block.id for block in active_blocks],
        )
    total_blocks = len(all_blocks)
    metrics["review_outcomes"] = {
        "block_count": total_blocks,
        "rejection_rate": sum(
            block.verification is VerificationState.REJECTED for block in all_blocks
        )
        / total_blocks
        if total_blocks
        else 0.0,
        "review_rate": sum(
            block.verification is VerificationState.NEEDS_REVIEW for block in all_blocks
        )
        / total_blocks
        if total_blocks
        else 0.0,
    }
    return {
        "id": corpus_document.id,
        "features": corpus_document.features,
        "pages": len(document.pages),
        "metrics": metrics,
        "telemetry": telemetry,
        "reference_basis": basis.value,
    }


def live_telemetry_record(
    parse_result: Any,
    *,
    latency_seconds: float,
    extraction_result: Any | None = None,
) -> dict[str, Any]:
    calls = list(parse_result.usage.calls if parse_result.usage is not None else [])
    if extraction_result is not None and extraction_result.usage is not None:
        calls.extend(extraction_result.usage.calls)
    model_usage: dict[str, dict[str, int]] = {}
    for call in calls:
        usage = model_usage.setdefault(
            call.model, {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        )
        usage["calls"] += 1
        usage["input_tokens"] += call.input_tokens
        usage["output_tokens"] += call.output_tokens
    diagnostics = parse_result.runtime_diagnostics
    traces = list(parse_result.trace or [])
    image_traces = [trace for trace in traces if trace.image_count]
    crop_traces = [
        trace
        for trace in image_traces
        if trace.image_scope == "crop_batch" and trace.source_page_pixels
    ]
    repair_traces = [
        trace
        for trace in traces
        if trace.action not in {"page_draft", "page_plan"} and trace.target_ids
    ]
    repaired_targets = {
        target_id for trace in repair_traces for target_id in trace.target_ids
    }
    blocks = [
        block for page in parse_result.document.pages for block in _flatten(page.blocks)
    ]
    return {
        "latency_seconds": latency_seconds,
        "pages": len(parse_result.document.pages),
        "input_tokens": sum(call.input_tokens for call in calls),
        "output_tokens": sum(call.output_tokens for call in calls),
        "full_page_fallbacks": diagnostics.full_page_fallbacks
        if diagnostics is not None
        else 0,
        "blocks": len(blocks),
        "full_page_calls": sum(
            trace.image_scope == "full_page" for trace in image_traces
        ),
        "crop_calls": sum(trace.image_scope == "crop_batch" for trace in image_traces),
        "image_pixels": sum(trace.image_pixels for trace in image_traces),
        "crop_pixels": sum(
            trace.image_pixels
            for trace in image_traces
            if trace.image_scope == "crop_batch"
        ),
        "crop_area_ratios": [
            trace.image_pixels / trace.source_page_pixels for trace in crop_traces
        ],
        "full_page_equivalents": sum(
            trace.image_pixels / trace.source_page_pixels
            for trace in image_traces
            if trace.source_page_pixels
        ),
        "repair_calls": len(repair_traces),
        "repaired_targets": len(repaired_targets),
        "model_usage": model_usage,
        "retries": diagnostics.retries if diagnostics is not None else 0,
        "rate_limit_events": diagnostics.rate_limit_events
        if diagnostics is not None
        else 0,
    }


def _unavailable(reason: str) -> dict[str, str | None]:
    return {"value": None, "reason": reason}


def _flatten(blocks: list[Block]) -> list[Block]:
    flattened: list[Block] = []
    for block in blocks:
        flattened.append(block)
        flattened.extend(_flatten(block.children))
    return flattened


def _edit_distance(candidate: list[str], reference: list[str]) -> int:
    previous = list(range(len(reference) + 1))
    for candidate_index, candidate_token in enumerate(candidate, 1):
        current = [candidate_index]
        for reference_index, reference_token in enumerate(reference, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[reference_index] + 1,
                    previous[reference_index - 1]
                    + (candidate_token != reference_token),
                )
            )
        previous = current
    return previous[-1]


def _sequence_metrics(
    candidate: list[str], reference: list[str]
) -> tuple[float, float]:
    if not reference:
        return (100.0 if not candidate else 0.0, 0.0 if not candidate else 100.0)
    distance = _edit_distance(candidate, reference)
    return max(0.0, 100 * (1 - distance / len(reference))), 100 * distance / len(
        reference
    )
