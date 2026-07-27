from __future__ import annotations

import html
import re
from collections import Counter

from .models import Block, Document, NodeType, VerificationState

WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
VISUAL_TYPES = {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}


def _flatten(blocks: list[Block]) -> list[Block]:
    flattened: list[Block] = []
    for block in blocks:
        flattened.append(block)
        flattened.extend(_flatten(block.children))
    return flattened


def _searchable_text(block: Block) -> str:
    values = [block.text, block.caption or "", block.figure_description or ""]
    if block.form is not None:
        values.extend(
            [block.form.label, block.form.value or "", block.form.hint or ""]
        )
    values.extend([block.checkbox_group or "", block.checkbox_option or ""])
    return "\n".join(value for value in values if value)


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _tokens(value: str) -> list[str]:
    normalized = value.replace("<!-- PAGE BREAK -->", " ").replace("\u00ad", "")
    normalized = re.sub(r"<[^>]*>", " ", html.unescape(normalized))
    normalized = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in normalized
    )
    return WORD_PATTERN.findall(normalized.casefold())


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


def _sequence_metrics(candidate: list[str], reference: list[str]) -> tuple[float, float]:
    if not reference:
        return (100.0 if not candidate else 0.0, 0.0 if not candidate else 100.0)
    distance = _edit_distance(candidate, reference)
    return max(0.0, 100 * (1 - distance / len(reference))), 100 * distance / len(reference)


def compare_markdown(
    candidate: str,
    reference: str,
    *,
    text_dominant_pages: list[int] | None = None,
) -> dict[str, object]:
    candidate_pages = candidate.split("<!-- PAGE BREAK -->")
    reference_pages = reference.split("<!-- PAGE BREAK -->")
    page_count = max(len(candidate_pages), len(reference_pages))
    candidate_page_tokens = [_tokens(page) for page in candidate_pages]
    reference_page_tokens = [_tokens(page) for page in reference_pages]
    page_report: dict[str, dict[str, float]] = {}
    for page_index in range(page_count):
        candidate_tokens = candidate_page_tokens[page_index] if page_index < len(candidate_page_tokens) else []
        reference_tokens = reference_page_tokens[page_index] if page_index < len(reference_page_tokens) else []
        accuracy, error_rate = _sequence_metrics(candidate_tokens, reference_tokens)
        page_report[str(page_index + 1)] = {
            "accuracy": accuracy,
            "word_error_rate": error_rate,
        }

    candidate_tokens = [token for page in candidate_page_tokens for token in page]
    reference_tokens = [token for page in reference_page_tokens for token in page]
    accuracy, error_rate = _sequence_metrics(candidate_tokens, reference_tokens)
    candidate_counts = Counter(candidate_tokens)
    reference_counts = Counter(reference_tokens)
    overlap = sum((candidate_counts & reference_counts).values())
    precision = overlap / len(candidate_tokens) if candidate_tokens else 0.0
    recall = overlap / len(reference_tokens) if reference_tokens else 0.0
    token_f1 = 200 * precision * recall / (precision + recall) if precision + recall else 0.0

    dominant = text_dominant_pages or []
    dominant_candidate = [
        token
        for page_number in dominant
        if page_number <= len(candidate_page_tokens)
        for token in candidate_page_tokens[page_number - 1]
    ]
    dominant_reference = [
        token
        for page_number in dominant
        if page_number <= len(reference_page_tokens)
        for token in reference_page_tokens[page_number - 1]
    ]
    dominant_accuracy, _ = _sequence_metrics(dominant_candidate, dominant_reference)
    return {
        "strict_word_accuracy": accuracy,
        "word_error_rate": error_rate,
        "token_f1": token_f1,
        "text_dominant_accuracy": dominant_accuracy,
        "pages": page_report,
    }


def accuracy_threshold_failures(
    metrics: dict[str, object], thresholds: dict[str, object]
) -> list[str]:
    failures: list[str] = []
    for name in (
        "strict_word_accuracy",
        "token_f1",
        "text_dominant_accuracy",
    ):
        if name not in thresholds:
            continue
        actual = float(metrics[name])
        minimum = float(thresholds[name])
        if actual <= minimum:
            failures.append(
                f"{name} was {actual:.4f}, expected greater than {minimum:.4f}"
            )
    pages = metrics.get("pages", {})
    if not isinstance(pages, dict):
        pages = {}
    page_thresholds = thresholds.get("page_accuracy", {})
    if not isinstance(page_thresholds, dict):
        page_thresholds = {}
    for page_number, raw_minimum in page_thresholds.items():
        page_metrics = pages.get(str(page_number), {})
        actual = float(page_metrics.get("accuracy", 0.0))
        minimum = float(raw_minimum)
        if actual <= minimum:
            failures.append(
                f"page {page_number} accuracy was {actual:.4f}, "
                f"expected greater than {minimum:.4f}"
            )
    return failures


def evaluate_result(
    document: Document, markdown: str, expectations: dict[str, object]
) -> list[str]:
    failures: list[str] = []
    expected_schema = str(expectations["schema_version"])
    if document.schema_version != expected_schema:
        failures.append(
            f"schema version was {document.schema_version}, expected {expected_schema}"
        )
    expected_pages = int(expectations["page_count"])
    if len(document.pages) != expected_pages:
        failures.append(f"page count was {len(document.pages)}, expected {expected_pages}")
    expected_breaks = int(expectations["page_break_count"])
    actual_breaks = markdown.count("<!-- PAGE BREAK -->")
    if actual_breaks != expected_breaks:
        failures.append(f"page break count was {actual_breaks}, expected {expected_breaks}")
    minimum_words = int(expectations["minimum_word_count"])
    actual_words = len(WORD_PATTERN.findall(markdown))
    if actual_words < minimum_words:
        failures.append(f"word count was {actual_words}, expected at least {minimum_words}")
    for marker in ("[UNRESOLVED", "<!-- source", "---\nsource:"):
        if marker in markdown:
            failures.append(f"Markdown contains audit clutter: {marker}")

    pages = {page.number: _flatten(page.blocks) for page in document.pages}
    required_by_page = expectations.get("required_by_page", {})
    for raw_page, required in required_by_page.items():
        page_number = int(raw_page)
        page_text = _normalize_whitespace(
            "\n".join(_searchable_text(block) for block in pages.get(page_number, []))
        )
        for value in required:
            if _normalize_whitespace(str(value)) not in page_text:
                failures.append(f"page {page_number} missing required text: {value}")

    markdown_casefold = markdown.casefold()
    for value in expectations.get("forbidden", []):
        if str(value).casefold() in markdown_casefold:
            failures.append(f"Markdown contains forbidden text: {value}")

    for raw_page, expected_markers in expectations.get("list_markers_by_page", {}).items():
        page_number = int(raw_page)
        actual_markers = [
            block.list_marker
            for block in pages.get(page_number, [])
            if block.type is NodeType.LIST_ITEM
        ]
        if actual_markers != expected_markers:
            failures.append(
                f"page {page_number} list markers were {actual_markers}, expected {expected_markers}"
            )

    for raw_page, minimum_types in expectations.get("minimum_types_by_page", {}).items():
        page_number = int(raw_page)
        counts = Counter(str(block.type) for block in pages.get(page_number, []))
        for block_type, minimum in minimum_types.items():
            if counts[block_type] < int(minimum):
                failures.append(
                    f"page {page_number} has {counts[block_type]} {block_type} blocks, "
                    f"expected at least {minimum}"
                )

    for raw_page, terms in expectations.get("figure_terms_by_page", {}).items():
        page_number = int(raw_page)
        visual_text = "\n".join(
            _searchable_text(block)
            for block in pages.get(page_number, [])
            if block.type in VISUAL_TYPES
        ).casefold()
        for term in terms:
            if str(term).casefold() not in visual_text:
                failures.append(f"page {page_number} figure descriptions missing: {term}")

    for raw_page, fact_groups in expectations.get(
        "visual_fact_groups_by_page", {}
    ).items():
        page_number = int(raw_page)
        visual_texts = [
            _normalize_whitespace(_searchable_text(block)).casefold()
            for block in pages.get(page_number, [])
            if block.type in VISUAL_TYPES
        ]
        for group_index, fact_group in enumerate(fact_groups, 1):
            matched = any(
                all(
                    any(
                        _normalize_whitespace(str(term)).casefold() in visual_text
                        for term in alternatives
                    )
                    for alternatives in fact_group
                )
                for visual_text in visual_texts
            )
            if not matched:
                failures.append(
                    f"page {page_number} has no visual block matching "
                    f"semantic fact group {group_index}"
                )

    for page_number, blocks in pages.items():
        for block in blocks:
            if block.verification is VerificationState.REJECTED:
                continue
            grounded = (
                block.bbox is not None
                and block.citation is not None
                and block.citation.page == page_number
                and block.citation.bbox is not None
                and block.citation.bbox.unit == "normalized"
            )
            if not grounded:
                failures.append(f"block {block.id} on page {page_number} is missing grounding")
    return failures
