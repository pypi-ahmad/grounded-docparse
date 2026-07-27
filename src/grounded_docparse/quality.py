from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from itertools import pairwise

from .ingest import PageEvidence, TextBlock
from .models import Block, BoundingBox, NodeType, RegionDraft, VerificationState

SOURCE_COVERAGE_THRESHOLD = 0.70
MAX_REPAIR_BLOCKS = 8
REPAIR_CONFIDENCE_THRESHOLD = 0.85
SCAN_UNCOVERED_INTERIOR_THRESHOLD = 0.30
SCAN_LARGE_VISUAL_AREA = 0.15
SCAN_INTERIOR = (0.1, 0.1, 0.9, 0.9)

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
REPEATED_LABEL_PATTERN = re.compile(
    r"^(?P<label>[^\n–—]{1,80}?)(?P<separator>\s+[–—-]\s+)"
    r"(?P=label)(?P=separator)",
    re.IGNORECASE,
)
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


def _tokens(value: str) -> list[str]:
    return WORD_PATTERN.findall(value.casefold())


def _coverage(candidate: str, reference: str) -> float:
    reference_tokens = _tokens(reference)
    if not reference_tokens:
        return 1.0
    overlap = sum((Counter(_tokens(candidate)) & Counter(reference_tokens)).values())
    return overlap / len(reference_tokens)


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


def _spatially_related(left: BoundingBox | None, right: BoundingBox | None) -> bool:
    intersection = _intersection(left, right)
    smaller = min(_area(left), _area(right))
    return bool(smaller and intersection / smaller >= 0.2)


def semantic_text(block: Block) -> str:
    values = [block.text]
    if block.table is not None:
        values.extend(cell.text for cell in block.table.cells)
    if block.form is not None:
        values.extend((block.form.label, block.form.value or "", block.form.hint or ""))
    values.extend((block.checkbox_group or "", block.checkbox_option or ""))
    values.extend((block.caption or "", block.figure_description or ""))
    return " ".join(" ".join(value.split()) for value in values if value)


def _source_candidate(source: TextBlock, reading_order: int) -> RegionDraft:
    text = " ".join(source.text.split())
    marker_match = LIST_PREFIX_PATTERN.match(text)
    node_type = NodeType.LIST_ITEM if marker_match else NodeType.PARAGRAPH
    marker = marker_match.group("marker") if marker_match else None
    body = marker_match.group("body") if marker_match else text
    return RegionDraft(
        type=node_type,
        bbox=source.bbox.model_dump(exclude={"unit"}),
        reading_order=reading_order,
        text=body,
        confidence=0.99,
        list_marker=marker,
    )


def _scan_candidate(bbox: BoundingBox, reading_order: int) -> RegionDraft:
    return RegionDraft(
        type=NodeType.PARAGRAPH,
        bbox=bbox.model_dump(exclude={"unit"}),
        reading_order=reading_order,
        text="",
        confidence=0.5,
    )


def _incomplete_structured_content(block: Block) -> bool:
    if block.type is NodeType.TABLE:
        return block.table is None or not block.table.cells or any(
            not cell.text.strip() for cell in block.table.cells
        )
    if block.type is NodeType.FORM_FIELD:
        return block.form is None or not block.form.label.strip()
    if block.type is NodeType.CHECKBOX:
        return not (block.checkbox_group or block.checkbox_option)
    return False


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
    x_coordinates = sorted({region.x0, region.x1, *(box.x0 for box in boxes), *(box.x1 for box in boxes)})
    y_coordinates = sorted({region.y0, region.y1, *(box.y0 for box in boxes), *(box.y1 for box in boxes)})
    covered = 0.0
    for x0, x1 in pairwise(x_coordinates):
        for y0, y1 in pairwise(y_coordinates):
            if any(
                box.x0 <= x0 and x1 <= box.x1 and box.y0 <= y0 and y1 <= box.y1
                for box in boxes
            ):
                covered += (x1 - x0) * (y1 - y0)
    return covered / _area(region) if _area(region) else 0.0


def _scan_probes(page: PageEvidence, blocks: list[Block]) -> list[RegionDraft]:
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
        if _incomplete_structured_content(block):
            add_probe(block.bbox)
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
    *,
    threshold: float = SOURCE_COVERAGE_THRESHOLD,
) -> list[RegionDraft]:
    missing = _scan_probes(page, blocks) if page.scanned else []
    for source in page.text_blocks:
        if len(_tokens(source.text)) < 3:
            continue
        related_text = " ".join(
            semantic_text(block)
            for block in blocks
            if block.verification is not VerificationState.REJECTED
            and _spatially_related(source.bbox, block.bbox)
        )
        if _coverage(related_text, source.text) < threshold:
            missing.append(_source_candidate(source, len(blocks) + len(missing)))
    return missing


def _critical_values(value: str) -> set[str]:
    return {
        match.group(0).casefold().rstrip(".,;:")
        for pattern in CRITICAL_PATTERNS
        for match in pattern.finditer(value)
    }


def _related_source_text(page: PageEvidence, block: Block) -> str:
    return " ".join(
        source.text
        for source in page.text_blocks
        if _spatially_related(source.bbox, block.bbox)
    )


def _structured_repair_risks(
    page: PageEvidence,
    block: Block,
    warnings: list[str],
) -> set[str]:
    if block.type not in COMPLEX_TYPES:
        return set()
    candidate_text = semantic_text(block)
    source_text = _related_source_text(page, block)
    risks: set[str] = set()
    if block.verification is VerificationState.REJECTED:
        risks.add("rejected")
    if _incomplete_structured_content(block):
        risks.add("structure")
    if block.confidence < REPAIR_CONFIDENCE_THRESHOLD:
        risks.add("confidence")
    if _clipped(block.bbox):
        risks.add("geometry")
    if _critical_values(candidate_text):
        risks.add("critical_literal")
    if source_text.strip() and (
        _coverage(candidate_text, source_text) < SOURCE_COVERAGE_THRESHOLD
        or _coverage(source_text, candidate_text) < SOURCE_COVERAGE_THRESHOLD
    ):
        risks.add("source_disagreement")
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
        source_text = _related_source_text(page, block)
        source_values = _critical_values(source_text)
        literal_mismatch = bool(source_values and not values.issubset(source_values))
        structured_risks = _structured_repair_risks(page, block, warnings)
        unresolved_literal = (
            block.verification is VerificationState.NEEDS_REVIEW and bool(values)
        )
        if not (literal_mismatch or structured_risks or unresolved_literal):
            continue
        priority = (
            0
            if literal_mismatch or "source_disagreement" in structured_risks
            else 1
            if structured_risks
            else 2
        )
        candidates.append((priority, block.confidence, block.reading_order, block))
    candidates.sort(key=lambda item: item[:3])
    selected = [item[3] for item in candidates]
    return selected if limit is None else selected[:limit]


def is_geometry_only_repair_candidate(
    page: PageEvidence,
    block: Block,
    warnings: list[str],
) -> bool:
    return _structured_repair_risks(page, block, warnings) == {"geometry"}


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
    while marker_prefix.match(block.text):
        block.text = marker_prefix.sub("", block.text, count=1).lstrip()


def _fingerprint(block: Block) -> str:
    return " ".join(_tokens(f"{block.type.value} {semantic_text(block)}"))


def _box_overlap(left: BoundingBox | None, right: BoundingBox | None) -> float:
    intersection = _intersection(left, right)
    union = _area(left) + _area(right) - intersection
    return intersection / union if union else 0.0


def _clipped(box: BoundingBox | None) -> bool:
    return box is None or _area(box) == 0 or box.y0 >= 0.999 or box.x0 >= 0.999


def _duplicate(left: Block, right: Block) -> bool:
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


def _quality(block: Block) -> tuple[int, int, float, float]:
    return (
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
    kept.sort(key=lambda block: block.reading_order)
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
