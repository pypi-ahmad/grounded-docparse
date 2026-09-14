"""Page-level OCR block quality cleanup: exact/near-duplicate removal,
redundant or conflicting "aggregate" recovery-block detection, missing-
region scan probes, and low-confidence literal/region repair-candidate
selection.

Must not: drop unique content as a duplicate, or treat a recovered/repaired
region as conflict-free when it disagrees with an already-grounded
high-stakes literal value (URL, email, phone, date, ID) — see
`CRITICAL_PATTERNS` and `recovery_content_conflicts`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import pairwise

from .ingest import PageEvidence
from .models import (
    Block,
    BoundingBox,
    ConfidenceSpan,
    NodeType,
    RegionDraft,
    VerificationState,
)

MAX_REPAIR_BLOCKS = 8
REPAIR_CONFIDENCE_THRESHOLD = 0.85
# Scan-probe tuning: SCAN_INTERIOR trims a 10% margin from each edge of the
# normalized [0, 1] page box (the margin is assumed to legitimately be
# whitespace); a probe is added there when less than
# (1 - SCAN_UNCOVERED_INTERIOR_THRESHOLD) of that interior is covered by
# text. SCAN_LARGE_VISUAL_AREA is the minimum fractional area for a
# text-free figure/image/chart block to also get its own probe.
SCAN_UNCOVERED_INTERIOR_THRESHOLD = 0.30
SCAN_LARGE_VISUAL_AREA = 0.15
SCAN_INTERIOR = (0.1, 0.1, 0.9, 0.9)

# Matches one token that may itself contain embedded separators (e.g.
# "user@example.com" or "12/25/2024" as a single token), not just bare
# alphanumerics.
WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[./:@_-][A-Za-z0-9]+)*")
ROMAN_NUMERAL_PATTERN = (
    r"(?:(?=[MDCLXVI])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})"
    r"(?:IX|IV|V?I{0,3})|(?=[mdclxvi])m{0,3}(?:cm|cd|d?c{0,3})"
    r"(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3}))"
)
LIST_PREFIX_PATTERN = re.compile(
    rf"^\s*(?P<marker>(?:\d+|{ROMAN_NUMERAL_PATTERN}|[A-Za-z])[.)]|"
    rf"\((?:\d+|{ROMAN_NUMERAL_PATTERN}|[A-Za-z])\)|[-*•])\s+(?P<body>.+)$"
)
# Matches a label+separator duplicated back-to-back at the start of text
# (e.g. "Total – Total – $50"), an observed OCR/render artifact; used by
# _normalize_marker to collapse it to a single occurrence.
REPEATED_LABEL_PATTERN = re.compile(
    r"^(?P<label>[^\n–—]{1,80}?)(?P<separator>\s+[–—-]\s+)"
    r"(?P=label)(?P=separator)",
    re.IGNORECASE,
)
# High-stakes literal values (URL, email, phone, date, alphanumeric ID,
# long number/decimal) where a recovery/repair silently getting the value
# wrong matters far more than losing a word of prose; see
# recovery_content_conflicts.
CRITICAL_PATTERNS = (
    re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\w)\+?\d[\d(). -]{6,}\d(?!\w)"),
    re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b"),
    re.compile(r"\b(?=[A-Za-z0-9_.-]*[A-Za-z])(?=[A-Za-z0-9_.-]*\d)[A-Za-z0-9_.-]{3,}\b"),
    re.compile(r"\b\d{5,}\b|\b\d+\.\d+\b"),
)
DEGRADED_MARKERS = ("ambiguous", "degraded", "handwritten", "illegible", "obscured")
COMPLEX_TYPES = {NodeType.TABLE, NodeType.FORM_FIELD, NodeType.CHECKBOX}
VISUAL_TYPES = {NodeType.FIGURE, NodeType.IMAGE, NodeType.CHART}


@dataclass(frozen=True, slots=True)
class LiteralRepairCandidate:
    owner_kind: str
    owner_index: int
    span_index: int
    span: ConfidenceSpan
    reason: str


def _tokens(value: str) -> list[str]:
    return WORD_PATTERN.findall(value.casefold())


def _area(box: BoundingBox | None) -> float:
    if box is None:
        return 0.0
    return max(0.0, box.x1 - box.x0) * max(0.0, box.y1 - box.y0)


def _intersection(left: BoundingBox | None, right: BoundingBox | None) -> float:
    if left is None or right is None:
        return 0.0
    width = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    height = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    return width * height


def semantic_text(block: Block) -> str:
    # The single string used for token/duplicate/critical-value comparisons
    # throughout this file; must stay comprehensive across every text-
    # bearing field or those comparisons will miss structured content
    # (e.g. a table cell's own text, not just the block's top-level text).
    values = [block.text]
    if block.table is not None:
        values.extend(cell.text for cell in block.table.cells)
    if block.form is not None:
        values.extend((block.form.label, block.form.value or "", block.form.hint or ""))
    values.extend((block.checkbox_group or "", block.checkbox_option or ""))
    values.extend((block.caption or "", block.figure_description or ""))
    return " ".join(" ".join(value.split()) for value in values if value)


def _spatial_recovery_blocks(candidate: Block, existing: list[Block]) -> list[Block]:
    related: list[Block] = []

    def visit(block: Block) -> None:
        if (
            block.verification is not VerificationState.REJECTED
            and _intersection(candidate.bbox, block.bbox) > 0
        ):
            related.append(block)
        for child in sorted(block.children, key=lambda item: item.reading_order):
            visit(child)

    for block in sorted(existing, key=lambda item: item.reading_order):
        visit(block)
    return related


def recovery_content_is_redundant(candidate: Block, existing: list[Block]) -> bool:
    """Return whether a recovery repeats spatially related active content in order.

    Checks that every candidate token appears, in order (not necessarily
    contiguously), within the combined existing tokens — an ordered
    subsequence, not an exact substring or an unordered bag match. Note the
    direction: candidate tokens must be a subsequence *of* existing tokens
    (opposite of `recovery_content_conflicts` below, which checks the
    reverse direction).
    """

    candidate_tokens = _recovery_tokens(semantic_text(candidate))
    if not candidate_tokens or candidate.bbox is None:
        return False
    existing_tokens = [
        token
        for block in _spatial_recovery_blocks(candidate, existing)
        for token in _recovery_tokens(semantic_text(block))
    ]
    return _ordered_subsequence(candidate_tokens, existing_tokens)


def recovery_content_conflicts(candidate: Block, existing: list[Block]) -> bool:
    """Detect a scan probe that repeats known content with conflicting literals."""

    if candidate.bbox is None:
        return False
    related = _spatial_recovery_blocks(candidate, existing)
    candidate_text = semantic_text(candidate)
    existing_text = " ".join(semantic_text(block) for block in related)
    # Only proceed if the candidate has at least one critical literal
    # (URL/email/phone/date/ID/number) that none of the related existing
    # content has — a plain wording difference is not a "conflict" here.
    if not (_critical_values(candidate_text) - _critical_values(existing_text)):
        return False
    candidate_tokens = _recovery_tokens(candidate_text)
    # Direction reversed from recovery_content_is_redundant: here each
    # related block's tokens must be a subsequence *of the candidate's*
    # tokens — i.e. the candidate repeats that block's wording but
    # (per the check above) attaches a different critical value to it.
    return any(
        _ordered_subsequence(_recovery_tokens(semantic_text(block)), candidate_tokens)
        for block in related
        if semantic_text(block).strip()
    )


def _recovery_tokens(value: str) -> list[str]:
    # Collapse "word- \n next" (a hyphenated word broken across a line
    # wrap) to "word-next" before tokenizing, so it reads as one token
    # instead of two.
    joined = re.sub(r"(?<=\w)-\s+(?=\w)", "-", value)
    return _tokens(joined)


def _ordered_subsequence(candidate: list[str], reference: list[str]) -> bool:
    if not candidate:
        return False
    iterator = iter(reference)
    return all(token in iterator for token in candidate)


def _scan_candidate(bbox: BoundingBox, reading_order: int) -> RegionDraft:
    return RegionDraft(
        type=NodeType.PARAGRAPH,
        bbox=bbox.model_dump(exclude={"unit"}),
        reading_order=reading_order,
        text="",
        confidence=0.5,
    )


def incomplete_table(block: Block) -> bool:
    return block.type is NodeType.TABLE and (
        block.table is None
        or not block.table.cells
        or any(not cell.text.strip() for cell in block.table.cells)
    )


def _incomplete_structured_content(block: Block) -> bool:
    if block.type is NodeType.TABLE:
        return incomplete_table(block)
    if block.type is NodeType.FORM_FIELD:
        return block.form is None or not block.form.label.strip()
    if block.type is NodeType.CHECKBOX:
        return not (block.checkbox_group or block.checkbox_option)
    return False


def _rectangle_union_area(boxes: list[BoundingBox]) -> float:
    """Union area of possibly-overlapping rectangles via a vertical sweep:
    walk x in order of each box's left/right edges (+1/-1 events), and at
    each x-gap add width * (merged height of all currently-active y-ranges)
    so overlapping boxes aren't double-counted.
    """
    events: list[tuple[float, int, float, float]] = []
    for box in boxes:
        if box.x1 <= box.x0 or box.y1 <= box.y0:
            continue
        events.append((box.x0, 1, box.y0, box.y1))
        events.append((box.x1, -1, box.y0, box.y1))
    events.sort()
    active: Counter[tuple[float, float]] = Counter()
    area = 0.0
    previous_x: float | None = None
    index = 0
    while index < len(events):
        x = events[index][0]
        if previous_x is not None and x > previous_x:
            intervals = sorted(interval for interval, count in active.items() if count)
            covered_y = 0.0
            if intervals:
                start, end = intervals[0]
                for next_start, next_end in intervals[1:]:
                    if next_start <= end:
                        end = max(end, next_end)
                    else:
                        covered_y += end - start
                        start, end = next_start, next_end
                covered_y += end - start
            area += (x - previous_x) * covered_y
        while index < len(events) and events[index][0] == x:
            _event_x, delta, y0, y1 = events[index]
            active[(y0, y1)] += delta
            if not active[(y0, y1)]:
                del active[(y0, y1)]
            index += 1
        previous_x = x
    return area


def _covered_fraction(blocks: list[Block], region: BoundingBox) -> float:
    boxes = [
        BoundingBox(
            x0=max(block.bbox.x0, region.x0),
            y0=max(block.bbox.y0, region.y0),
            x1=min(block.bbox.x1, region.x1),
            y1=min(block.bbox.y1, region.y1),
        )
        for block in blocks
        if block.verification is not VerificationState.REJECTED
        and block.bbox is not None
        and _intersection(block.bbox, region) > 0
    ]
    covered = _rectangle_union_area(boxes)
    return covered / _area(region) if _area(region) else 0.0


def _scan_probes(page: PageEvidence, blocks: list[Block]) -> list[RegionDraft]:
    """Propose placeholder regions worth a fresh OCR/repair attempt: (1) a
    large visual block (figure/image/chart) with no recognized text, which
    may actually contain readable text; (2) the page's margin-trimmed
    interior, when it has no text at all or is mostly uncovered by any
    text-bearing block (see SCAN_INTERIOR/SCAN_UNCOVERED_INTERIOR_THRESHOLD
    above).
    """
    probes: list[RegionDraft] = []

    def add_probe(bbox: BoundingBox) -> None:
        candidate = _scan_candidate(bbox, len(blocks) + len(probes))
        if not any(probe.bbox == candidate.bbox for probe in probes):
            probes.append(candidate)

    active_blocks = [
        block for block in blocks if block.verification is not VerificationState.REJECTED
    ]
    for block in active_blocks:
        if block.bbox is None:
            continue
        if (
            block.type in VISUAL_TYPES
            and not semantic_text(block).strip()
            and _area(block.bbox) >= SCAN_LARGE_VISUAL_AREA
        ):
            add_probe(block.bbox)

    interior = BoundingBox(
        x0=SCAN_INTERIOR[0],
        y0=SCAN_INTERIOR[1],
        x1=SCAN_INTERIOR[2],
        y1=SCAN_INTERIOR[3],
    )
    if not any(semantic_text(block).strip() for block in active_blocks) or (
        1 - _covered_fraction(active_blocks, interior)
        >= SCAN_UNCOVERED_INTERIOR_THRESHOLD
    ):
        add_probe(interior)
    return probes


def find_missing_source_regions(
    page: PageEvidence,
    blocks: list[Block],
) -> list[RegionDraft]:
    return _scan_probes(page, blocks)


def _critical_values(value: str) -> set[str]:
    return {
        match.group(0).casefold().rstrip(".,;:")
        for pattern in CRITICAL_PATTERNS
        for match in pattern.finditer(value)
    }


def literal_repair_candidates(
    page: PageEvidence,
    block: Block,
    *,
    threshold: float = REPAIR_CONFIDENCE_THRESHOLD,
) -> list[LiteralRepairCandidate]:
    """Return exact, independently repairable literals without inventing ranges."""

    owners: list[tuple[str, int, str, float | None, BoundingBox | None, list[ConfidenceSpan]]] = [
        (
            "atom",
            index,
            atom.text,
            atom.confidence,
            atom.bbox or block.bbox,
            atom.low_confidence_spans,
        )
        for index, atom in enumerate(block.atoms)
    ]
    if block.table is not None:
        owners.extend(
            (
                "table_cell",
                index,
                cell.text,
                cell.confidence,
                cell.bbox or block.bbox,
                cell.low_confidence_spans,
            )
            for index, cell in enumerate(block.table.cells)
        )

    candidates: list[LiteralRepairCandidate] = []
    for owner_kind, owner_index, text, owner_confidence, bbox, spans in owners:
        # `occupied` is populated below but never read — unclear from this
        # file whether it was meant to suppress overlapping candidate spans
        # and that check was never wired in, or it's leftover from removed
        # logic.
        occupied: list[tuple[int, int]] = []
        for span_index, span in enumerate(spans):
            confidence = span.confidence if span.confidence is not None else owner_confidence
            confidence = block.confidence if confidence is None else confidence
            if confidence is None:
                continue
            if confidence >= threshold:
                continue
            candidates.append(
                LiteralRepairCandidate(
                    owner_kind=owner_kind,
                    owner_index=owner_index,
                    span_index=span_index,
                    span=span,
                    reason="low confidence",
                )
            )
            occupied.append((span.start, span.end))

    return candidates


def requires_region_repair(page: PageEvidence, block: Block, warnings: list[str]) -> bool:
    # "confidence" is a valid risk _structured_repair_risks can return, but
    # is deliberately not one of the triggers checked here — low
    # confidence alone doesn't force a full region repair (contrast with
    # select_repair_blocks below, where any non-empty risk set qualifies).
    risks = _structured_repair_risks(page, block, warnings)
    return bool(risks.intersection({"rejected", "structure", "geometry", "degraded"}))


def _structured_repair_risks(
    page: PageEvidence,
    block: Block,
    warnings: list[str],
) -> set[str]:
    if block.type not in COMPLEX_TYPES:
        return set()
    risks: set[str] = set()
    if block.verification is VerificationState.REJECTED:
        risks.add("rejected")
    if _incomplete_structured_content(block):
        risks.add("structure")
    if block.confidence is not None and block.confidence < REPAIR_CONFIDENCE_THRESHOLD:
        risks.add("confidence")
    if _clipped(block.bbox):
        risks.add("geometry")
    if any(
        marker in warning.casefold()
        for marker in DEGRADED_MARKERS
        for warning in warnings
    ):
        risks.add("degraded")
    return risks


def select_repair_blocks(
    page: PageEvidence,
    blocks: list[Block],
    warnings: list[str],
    *,
    limit: int | None = None,
) -> list[Block]:
    candidates: list[tuple[int, float, int, Block]] = []
    for block in blocks:
        structured = block.type in COMPLEX_TYPES
        if block.verification is VerificationState.REJECTED and not structured:
            continue
        values = _critical_values(semantic_text(block))
        structured_risks = _structured_repair_risks(page, block, warnings)
        unresolved_literal = (
            block.verification is VerificationState.NEEDS_REVIEW and bool(values)
        )
        if not (structured_risks or unresolved_literal):
            continue
        priority = (
            1
            if structured_risks
            else 2
        )
        candidates.append((priority, block.confidence, block.reading_order, block))
    # Ascending sort: structured risks first (priority 1 before 2), then
    # lowest confidence first within a tier (worse blocks repaired first),
    # then document order as the final tiebreak.
    candidates.sort(key=lambda item: item[:3])
    selected = [item[3] for item in candidates]
    return selected if limit is None else selected[:limit]


def _normalize_marker(block: Block) -> None:
    block.text = REPEATED_LABEL_PATTERN.sub(
        lambda match: f"{match.group('label')}{match.group('separator')}",
        block.text,
    )
    if block.type is not NodeType.LIST_ITEM or not block.list_marker:
        return
    marker = block.list_marker.strip()
    if not marker:
        return
    marker_prefix = re.compile(rf"^{re.escape(marker)}(?=\s|$)", re.IGNORECASE)
    # A loop, not a single strip: the marker text has been observed
    # repeated more than once (e.g. "1. 1. Item").
    while marker_prefix.match(block.text):
        block.text = marker_prefix.sub("", block.text, count=1).lstrip()


def _fingerprint(block: Block) -> str:
    return " ".join(_tokens(f"{block.type.value} {semantic_text(block)}"))


def _box_overlap(left: BoundingBox | None, right: BoundingBox | None) -> float:
    """Intersection-over-union (IoU) of two normalized [0, 1] bboxes."""
    intersection = _intersection(left, right)
    union = _area(left) + _area(right) - intersection
    return intersection / union if union else 0.0


def _clipped(box: BoundingBox | None) -> bool:
    # A box with no area, or one that starts almost exactly at the page's
    # bottom or right edge (y0/x0 >= 0.999) — a sliver most likely produced
    # by content cut off at the page boundary rather than a real block.
    return box is None or _area(box) == 0 or box.y0 >= 0.999 or box.x0 >= 0.999


def _duplicate(left: Block, right: Block) -> bool:
    """Two strategies: an exact fingerprint match co-located in reading
    order or heavily overlapping boxes, or (for blocks clipped at the page's
    bottom edge — see _clipped) a near-duplicate by text similarity, since
    a footer/caption clipped and re-OCR'd can come back with a slightly
    different crop rather than byte-identical text.
    """
    if left.type is not right.type:
        return False
    left_text = _fingerprint(left)
    right_text = _fingerprint(right)
    if not left_text or not right_text:
        return False
    exact = left_text == right_text
    if exact and (
        left.reading_order == right.reading_order
        or _box_overlap(left.bbox, right.bbox) >= 0.8
    ):
        return True
    bottom_edge = bool(
        left.bbox
        and right.bbox
        and left.bbox.y1 >= 0.95
        and right.bbox.y1 >= 0.95
    )
    similarity = SequenceMatcher(None, left_text, right_text, autojunk=False).ratio()
    return bottom_edge and (_clipped(left.bbox) or _clipped(right.bbox)) and similarity >= 0.75


def _quality(block: Block) -> tuple[int, int, int, float, float]:
    # Tuple compared lexicographically: not-rejected, then not-clipped,
    # then verified, outrank confidence and area — a rejected or clipped
    # duplicate loses even if it has higher confidence or a larger box.
    return (
        int(block.verification is not VerificationState.REJECTED),
        int(not _clipped(block.bbox)),
        int(block.verification is VerificationState.VERIFIED),
        block.confidence,
        _area(block.bbox),
    )


def normalize_page_blocks(blocks: list[Block]) -> tuple[list[Block], list[str]]:
    ordered = sorted(enumerate(blocks), key=lambda item: (item[1].reading_order, item[0]))
    kept: list[Block] = []
    warnings: list[str] = []
    for _index, block in ordered:
        _normalize_marker(block)
        duplicate_index = next(
            (index for index, existing in enumerate(kept) if _duplicate(existing, block)),
            None,
        )
        if duplicate_index is None:
            kept.append(block)
            continue
        existing = kept[duplicate_index]
        if _quality(block) > _quality(existing):
            kept[duplicate_index] = block
            warnings.append(f"removed duplicate block {existing.id}")
        else:
            warnings.append(f"removed duplicate block {block.id}")
    # Second pass: a PARAGRAPH block whose box is larger than, and
    # overlaps, at least 2 already-kept blocks is treated as a suspect
    # "aggregate" (e.g. a whole region OCR'd again as one blob on top of
    # already-recognized finer-grained blocks) and checked for redundancy/
    # conflict against them.
    for candidate in list(kept):
        if candidate.type is not NodeType.PARAGRAPH or candidate.bbox is None:
            continue
        related = [
            block
            for block in kept
            if block is not candidate
            and semantic_text(block).strip()
            and _area(candidate.bbox) > _area(block.bbox)
            and _intersection(candidate.bbox, block.bbox) > 0
        ]
        if len(related) < 2:
            continue
        if recovery_content_is_redundant(candidate, related):
            kept.remove(candidate)
            warnings.append(f"removed redundant aggregate block {candidate.id}")
        elif recovery_content_conflicts(candidate, related):
            candidate.verification = VerificationState.REJECTED
            candidate.verification_reason = (
                "Aggregate content conflicts with grounded page evidence"
            )
            warnings.append(f"rejected conflicting aggregate block {candidate.id}")
    kept.sort(key=lambda block: block.reading_order)
    # Third pass: if a block immediately follows a HEADING and its first
    # line just repeats that heading's own text, drop the repeated line —
    # another observed OCR/render duplication artifact, distinct from the
    # marker/aggregate cases handled above.
    for previous, current in pairwise(kept):
        if previous.type is not NodeType.HEADING or not current.text:
            continue
        lines = current.text.splitlines()
        heading = previous.text.strip().removesuffix(":").casefold()
        first_line = lines[0].strip().removesuffix(":").casefold()
        if heading and heading == first_line:
            current.text = "\n".join(lines[1:]).lstrip()
    for reading_order, block in enumerate(kept):
        block.reading_order = reading_order
    return kept, warnings
