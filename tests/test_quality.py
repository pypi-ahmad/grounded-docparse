from __future__ import annotations

from pathlib import Path

import pytest

from grounded_docparse.ingest import PageEvidence, TextBlock
from grounded_docparse.models import (
    AtomicEvidence,
    Block,
    BoundingBox,
    Citation,
    FormData,
    NodeType,
    TableCell,
    TableData,
    VerificationState,
)
from grounded_docparse.quality import (
    _rectangle_union_area,
    find_missing_source_regions,
    literal_repair_candidates,
    normalize_page_blocks,
    recovery_content_conflicts,
    recovery_content_is_redundant,
    select_repair_blocks,
)


def test_literal_candidates_use_exact_disagreement_range(tmp_path: Path) -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.2)
    page = PageEvidence(
        number=1,
        width=100,
        height=100,
        dpi=72,
        image_path=tmp_path / "page.png",
        scanned=False,
        text_blocks=[TextBlock("Account 12345", bbox, 10, "Arial")],
    )
    block = Block(
        id="p1-b1",
        type=NodeType.PARAGRAPH,
        text="Account l2345",
        bbox=bbox,
        reading_order=0,
        confidence=0.9,
        atoms=[AtomicEvidence(kind="line", text="Account l2345", bbox=bbox)],
    )

    candidates = literal_repair_candidates(page, block)

    assert len(candidates) == 1
    assert candidates[0].span.text == "l2345"
    assert (
        block.atoms[0].text[candidates[0].span.start : candidates[0].span.end]
        == "l2345"
    )
    assert candidates[0].span.source == "deterministic_validation"


def test_native_text_agreement_suppresses_confidence_only_repair(
    tmp_path: Path,
) -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.2)
    page = PageEvidence(
        number=1,
        width=100,
        height=100,
        dpi=72,
        image_path=tmp_path / "page.png",
        scanned=False,
        text_blocks=[TextBlock("Account 12345", bbox, 10, "Arial")],
    )
    block = Block(
        id="p1-b1",
        type=NodeType.PARAGRAPH,
        text="Account 12345",
        bbox=bbox,
        reading_order=0,
        atoms=[
            AtomicEvidence(
                kind="line",
                text="Account 12345",
                bbox=bbox,
                confidence=0.4,
                low_confidence_spans=[
                    {
                        "start": 8,
                        "end": 13,
                        "text": "12345",
                        "confidence": 0.4,
                        "source": "provider",
                    }
                ],
            )
        ],
    )

    assert literal_repair_candidates(page, block) == []


def _box(x0: float, y0: float, x1: float, y1: float) -> BoundingBox:
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _page(
    *source_blocks: tuple[str, BoundingBox], scanned: bool = False
) -> PageEvidence:
    return PageEvidence(
        number=1,
        width=612,
        height=792,
        dpi=200,
        image_path=Path("page.png"),
        scanned=scanned,
        text_blocks=[
            TextBlock(text=text, bbox=bbox, font_size=11, font="Helvetica")
            for text, bbox in source_blocks
        ],
    )


def _block(
    block_id: str,
    text: str,
    bbox: BoundingBox,
    *,
    node_type: NodeType = NodeType.PARAGRAPH,
    order: int = 0,
    marker: str | None = None,
    table: TableData | None = None,
    form: FormData | None = None,
    confidence: float = 0.5,
    verification: VerificationState = VerificationState.NOT_CHECKED,
) -> Block:
    return Block(
        id=block_id,
        type=node_type,
        text=text,
        bbox=bbox,
        reading_order=order,
        list_marker=marker,
        table=table,
        form=form,
        confidence=confidence,
        verification=verification,
        citation=Citation(page=1, bbox=bbox),
    )


def test_recovery_content_is_redundant_when_existing_blocks_cover_it_in_order() -> None:
    full_page = _box(0.05, 0.05, 0.95, 0.95)
    existing = [
        _block("p1-b1", "First grounded line.", _box(0.1, 0.1, 0.9, 0.2), order=0),
        _block("p1-b2", "Second grounded line.", _box(0.1, 0.3, 0.9, 0.4), order=1),
    ]
    recovery = _block(
        "p1-b3",
        "First grounded line. Second grounded line.",
        full_page,
        order=2,
        verification=VerificationState.VERIFIED,
    )

    assert recovery_content_is_redundant(recovery, existing)


def test_recovery_content_compares_nested_grounded_children() -> None:
    full_page = _box(0.05, 0.05, 0.95, 0.95)
    heading = _block(
        "p1-b1",
        "Physical Exam",
        _box(0.1, 0.1, 0.9, 0.2),
        node_type=NodeType.HEADING,
        order=0,
    )
    heading.children = [
        _block(
            "p1-b2",
            "General: They are not in acute distress.",
            _box(0.1, 0.2, 0.9, 0.3),
            order=1,
        ),
        _block(
            "p1-b3",
            "Appearance: They are not ill-appearing.",
            _box(0.1, 0.3, 0.9, 0.4),
            order=2,
        ),
    ]
    recovery = _block(
        "p1-b4",
        "Physical Exam General: They are not in acute distress. "
        "Appearance: They are not ill-appearing.",
        full_page,
        order=3,
        verification=VerificationState.VERIFIED,
    )

    assert recovery_content_is_redundant(recovery, [heading])


def test_recovery_content_with_novel_literal_is_not_redundant() -> None:
    existing = [
        _block("p1-b1", "First grounded line.", _box(0.1, 0.1, 0.9, 0.2), order=0)
    ]
    recovery = _block(
        "p1-b2",
        "First grounded line. Novel value 204.",
        _box(0.05, 0.05, 0.95, 0.95),
        order=1,
        verification=VerificationState.VERIFIED,
    )

    assert not recovery_content_is_redundant(recovery, existing)


def test_recovery_at_a_different_location_is_not_treated_as_duplicate() -> None:
    existing = [_block("p1-b1", "Repeated label", _box(0.1, 0.1, 0.4, 0.2), order=0)]
    recovery = _block(
        "p1-b2",
        "Repeated label",
        _box(0.6, 0.7, 0.9, 0.8),
        order=1,
        verification=VerificationState.VERIFIED,
    )

    assert not recovery_content_is_redundant(recovery, existing)


def test_scan_recovery_with_conflicting_critical_literal_is_rejected() -> None:
    existing = [
        _block("p1-b1", "PUBLIC TEST DATA", _box(0.1, 0.1, 0.9, 0.2), order=0),
        _block("p1-b2", "Batch ID: SCAN-042", _box(0.1, 0.3, 0.9, 0.4), order=1),
    ]
    recovery = _block(
        "p1-b3",
        "PUBLIC TEST DATA\nBatch ID: SYN-0042",
        _box(0.05, 0.05, 0.95, 0.95),
        order=2,
        verification=VerificationState.VERIFIED,
    )

    assert recovery_content_conflicts(recovery, existing)


def test_full_page_recovery_allows_line_wrapped_hyphenated_literals() -> None:
    existing = [
        _block(
            "p1-b1",
            "Call 573-751-3334 for assistance.",
            _box(0.1, 0.1, 0.9, 0.2),
            order=0,
        ),
        _block("p1-b2", "Closing line", _box(0.1, 0.3, 0.9, 0.4), order=1),
    ]
    recovery = _block(
        "p1-b3",
        "Call 573-751-\n3334 for assistance. Closing line",
        _box(0.05, 0.05, 0.95, 0.95),
        order=2,
        verification=VerificationState.VERIFIED,
    )

    assert recovery_content_is_redundant(recovery, existing)


def test_missing_native_list_steps_become_grounded_recovery_regions() -> None:
    first_box = _box(0.1, 0.1, 0.9, 0.2)
    second_box = _box(0.1, 0.25, 0.9, 0.35)
    page = _page(
        ("1. Open the cold water tap for three minutes.", first_box),
        ("2. Flame-sterilize the tap before collection.", second_box),
    )
    blocks = [
        _block(
            "p1-b1",
            "Open the cold water tap for three minutes.",
            first_box,
            node_type=NodeType.LIST_ITEM,
            marker="1.",
        )
    ]

    missing = find_missing_source_regions(page, blocks)

    assert len(missing) == 1
    assert missing[0].type is NodeType.LIST_ITEM
    assert missing[0].list_marker == "2."
    assert missing[0].text == "Flame-sterilize the tap before collection."
    assert missing[0].bbox is not None
    assert missing[0].bbox.model_dump() == second_box.model_dump(exclude={"unit"})


def test_source_region_with_at_least_seventy_percent_coverage_is_not_recovered() -> (
    None
):
    bbox = _box(0.1, 0.1, 0.9, 0.2)
    page = _page(("Location address or name of sampling point", bbox))
    blocks = [_block("p1-b1", "Location address name of sampling point", bbox)]

    assert find_missing_source_regions(page, blocks) == []


def test_scanned_blank_page_creates_an_internal_quality_probe() -> None:
    page = _page(scanned=True)

    probes = find_missing_source_regions(page, [])

    assert len(probes) == 1
    assert probes[0].type is NodeType.PARAGRAPH
    assert probes[0].text == ""
    assert probes[0].bbox is not None
    assert probes[0].bbox.model_dump() == {
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.9,
        "y1": 0.9,
    }


def test_scanned_page_probes_untranscribed_large_visual_only() -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.9)
    page = _page(scanned=True)
    blank_visual = _block("p1-b1", "", bbox, node_type=NodeType.IMAGE)
    covered_text = _block("p1-b2", "Visible chart title", bbox)
    transcribed_visual = _block(
        "p1-b3", "Visible chart title", bbox, node_type=NodeType.IMAGE
    )

    blank_probes = find_missing_source_regions(page, [blank_visual, covered_text])
    transcribed_probes = find_missing_source_regions(page, [transcribed_visual])

    assert [probe.bbox.model_dump() for probe in blank_probes if probe.bbox] == [
        bbox.model_dump(exclude={"unit"})
    ]
    assert transcribed_probes == []


def test_scanned_page_does_not_duplicate_repairable_structured_content() -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.9)
    page = _page(scanned=True)
    incomplete_table = _block(
        "p1-b1",
        "",
        bbox,
        node_type=NodeType.TABLE,
        table=TableData(
            cells=[
                TableCell(row=0, column=0, text="Medication"),
                TableCell(row=0, column=1, text=""),
            ]
        ),
    )

    assert find_missing_source_regions(page, [incomplete_table]) == []


def test_scanned_page_probes_large_uncovered_internal_region() -> None:
    page = _page(scanned=True)
    small_text_block = _block("p1-b1", "Scanned notice", _box(0.1, 0.1, 0.2, 0.2))

    probes = find_missing_source_regions(page, [small_text_block])

    assert [probe.bbox.model_dump() for probe in probes if probe.bbox] == [
        {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9}
    ]


@pytest.mark.parametrize(
    ("boxes", "expected"),
    [
        ([], 0.0),
        ([_box(0.1, 0.1, 0.4, 0.4)], 0.09),
        ([_box(0.1, 0.1, 0.5, 0.5), _box(0.3, 0.3, 0.7, 0.7)], 0.28),
        ([_box(0.1, 0.1, 0.5, 0.5), _box(0.1, 0.1, 0.5, 0.5)], 0.16),
        ([_box(0.1, 0.1, 0.1, 0.9), _box(0.2, 0.2, 0.8, 0.2)], 0.0),
    ],
)
def test_rectangle_union_area_handles_overlap_duplicates_and_zero_area(
    boxes: list[BoundingBox], expected: float
) -> None:
    assert _rectangle_union_area(boxes) == pytest.approx(expected)


def test_rectangle_union_area_scales_to_many_disjoint_strips() -> None:
    boxes = [
        _box(index / 2_000, 0.1, (index + 1) / 2_000, 0.9) for index in range(1_000)
    ]

    assert _rectangle_union_area(boxes) == pytest.approx(0.4)


def test_critical_literal_mismatch_is_selected_for_repair() -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.2)
    page = _page(("NPI 1386746512", bbox))
    corrupted = _block("p1-b1", "NPI 1388746512", bbox)
    matching = _block("p1-b2", "NPI 1386746512", bbox, order=1)

    selected = select_repair_blocks(page, [corrupted, matching], [])

    assert [block.id for block in selected] == ["p1-b1"]


def test_degraded_scanned_table_with_codes_is_selected_for_repair() -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.5)
    page = _page(scanned=True)
    table = TableData(
        cells=[TableCell(row=0, column=0, text="Diabetes E11.9", bbox=bbox)]
    )
    block = _block(
        "p1-b1",
        "",
        bbox,
        node_type=NodeType.TABLE,
        table=table,
    )

    selected = select_repair_blocks(
        page,
        [block],
        ["Page 1: handwritten table is heavily degraded and ambiguous"],
    )

    assert selected == [block]


def test_structured_risks_are_selected_without_warning_keywords() -> None:
    table_box = _box(0.1, 0.1, 0.9, 0.3)
    form_box = _box(0.1, 0.4, 0.9, 0.6)
    page = _page(("Plan Gold", table_box))
    disagreeing_table = _block(
        "p1-b1",
        "",
        table_box,
        node_type=NodeType.TABLE,
        table=TableData(cells=[TableCell(row=0, column=0, text="Plan Silver")]),
        confidence=0.99,
    )
    weak_form = _block(
        "p1-b2",
        "",
        form_box,
        node_type=NodeType.FORM_FIELD,
        form=FormData(label="Account holder information"),
        confidence=0.4,
        order=1,
    )
    critical_table = _block(
        "p1-b3",
        "",
        _box(0.1, 0.65, 0.9, 0.75),
        node_type=NodeType.TABLE,
        table=TableData(cells=[TableCell(row=0, column=0, text="NPI 1386746512")]),
        confidence=0.99,
        order=2,
    )
    incomplete_checkbox = _block(
        "p1-b4",
        "",
        _box(0.1, 0.8, 0.9, 0.9),
        node_type=NodeType.CHECKBOX,
        confidence=0.99,
        order=3,
    )

    selected = select_repair_blocks(
        page,
        [disagreeing_table, weak_form, critical_table, incomplete_checkbox],
        [],
    )

    assert {block.id for block in selected} == {"p1-b1", "p1-b2", "p1-b3", "p1-b4"}


def test_rejected_structured_block_remains_a_repair_candidate() -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.3)
    rejected_checkbox = _block(
        "p1-b1",
        "Consent: Yes",
        bbox,
        node_type=NodeType.CHECKBOX,
        confidence=0.99,
        verification=VerificationState.REJECTED,
    )
    rejected_prose = _block(
        "p1-b2",
        "Unsupported prose",
        bbox,
        confidence=0.99,
        verification=VerificationState.REJECTED,
        order=1,
    )

    selected = select_repair_blocks(_page(), [rejected_checkbox, rejected_prose], [])

    assert selected == [rejected_checkbox]


def test_all_structural_candidates_are_returned_for_downstream_batching() -> None:
    blocks = [
        _block(
            f"p1-b{index + 1}",
            "",
            _box(0.1, 0.1, 0.9, 0.2),
            node_type=NodeType.FORM_FIELD,
            form=FormData(label=f"Field {index + 1}"),
            confidence=0.4,
            order=index,
        )
        for index in range(10)
    ]

    selected = select_repair_blocks(_page(), blocks, [])

    assert [block.id for block in selected] == [
        f"p1-b{index}" for index in range(1, 11)
    ]


def test_clipped_structured_geometry_is_selected_for_quality_repair() -> None:
    clipped = _block(
        "p1-b1",
        "",
        _box(0.999, 0.1, 1.0, 0.2),
        node_type=NodeType.FORM_FIELD,
        form=FormData(label="Account holder information"),
        confidence=0.99,
        verification=VerificationState.VERIFIED,
    )

    assert select_repair_blocks(_page(), [clipped], []) == [clipped]


def test_normalization_strips_structural_marker_duplication() -> None:
    numeric = _block(
        "p1-b1",
        "3. Fold and ship the form.",
        _box(0.1, 0.1, 0.9, 0.2),
        node_type=NodeType.LIST_ITEM,
        marker="3.",
        order=4,
    )
    labelled = _block(
        "p1-b2",
        "Routine – Regular monthly monitoring samples.",
        _box(0.1, 0.25, 0.9, 0.35),
        node_type=NodeType.LIST_ITEM,
        marker="Routine –",
        order=8,
    )

    normalized, warnings = normalize_page_blocks([numeric, labelled])

    assert warnings == []
    assert [(block.list_marker, block.text) for block in normalized] == [
        ("3.", "Fold and ship the form."),
        ("Routine –", "Regular monthly monitoring samples."),
    ]
    assert [block.reading_order for block in normalized] == [0, 1]


def test_normalization_removes_repeated_ordered_markers_idempotently() -> None:
    blocks = [
        _block(
            "numeric-dot",
            "1. 1. Collect the sample.",
            _box(0.1, 0.1, 0.9, 0.2),
            node_type=NodeType.LIST_ITEM,
            marker="1.",
        ),
        _block(
            "numeric-paren",
            "1) 1) Label the bottle.",
            _box(0.1, 0.2, 0.9, 0.3),
            node_type=NodeType.LIST_ITEM,
            marker="1)",
        ),
        _block(
            "alpha-dot",
            "A. A. Preserve the chain of custody.",
            _box(0.1, 0.3, 0.9, 0.4),
            node_type=NodeType.LIST_ITEM,
            marker="A.",
        ),
        _block(
            "alpha-paren",
            "A) A) Complete the field log.",
            _box(0.1, 0.4, 0.9, 0.5),
            node_type=NodeType.LIST_ITEM,
            marker="A)",
        ),
        _block(
            "roman",
            "IV. IV. Verify the result.",
            _box(0.1, 0.5, 0.9, 0.6),
            node_type=NodeType.LIST_ITEM,
            marker="IV.",
        ),
        _block(
            "parenthesized",
            "(iv) (iv) Archive the record.",
            _box(0.1, 0.6, 0.9, 0.7),
            node_type=NodeType.LIST_ITEM,
            marker="(iv)",
        ),
    ]

    normalized, _warnings = normalize_page_blocks(blocks)
    first_pass = [(block.list_marker, block.text) for block in normalized]
    renormalized, _warnings = normalize_page_blocks(normalized)

    assert first_pass == [
        ("1.", "Collect the sample."),
        ("1)", "Label the bottle."),
        ("A.", "Preserve the chain of custody."),
        ("A)", "Complete the field log."),
        ("IV.", "Verify the result."),
        ("(iv)", "Archive the record."),
    ]
    assert [(block.list_marker, block.text) for block in renormalized] == first_pass


def test_normalization_ignores_whitespace_only_list_marker() -> None:
    block = _block(
        "empty-marker",
        "",
        _box(0.1, 0.1, 0.9, 0.2),
        node_type=NodeType.LIST_ITEM,
        marker=" ",
    )

    normalized, warnings = normalize_page_blocks([block])

    assert warnings == []
    assert [(item.list_marker, item.text) for item in normalized] == [(" ", "")]


def test_source_recovery_recognizes_roman_and_parenthesized_ordered_markers_only() -> (
    None
):
    roman_box = _box(0.1, 0.1, 0.9, 0.2)
    parenthesized_box = _box(0.1, 0.25, 0.9, 0.35)
    prose_box = _box(0.1, 0.4, 0.9, 0.5)
    roman_prose_box = _box(0.1, 0.55, 0.9, 0.65)
    page = _page(
        ("IV. Verify the sample collection record.", roman_box),
        ("(2) Label the bottle before transport.", parenthesized_box),
        ("(Note) This sentence remains ordinary prose.", prose_box),
        ("Civil. Service requirements follow.", roman_prose_box),
    )

    missing = find_missing_source_regions(page, [])

    assert [(region.type, region.list_marker, region.text) for region in missing] == [
        (NodeType.LIST_ITEM, "IV.", "Verify the sample collection record."),
        (NodeType.LIST_ITEM, "(2)", "Label the bottle before transport."),
        (NodeType.PARAGRAPH, None, "(Note) This sentence remains ordinary prose."),
        (NodeType.PARAGRAPH, None, "Civil. Service requirements follow."),
    ]


def test_normalization_removes_duplicate_table_with_same_order() -> None:
    valid_box = _box(0.1, 0.7, 0.9, 0.9)
    clipped_box = _box(0.1, 1.0, 0.9, 1.0)
    table = TableData(cells=[TableCell(row=0, column=0, text="Medication")])
    valid = _block(
        "p1-b2",
        "",
        valid_box,
        node_type=NodeType.TABLE,
        table=table,
        order=20,
        verification=VerificationState.VERIFIED,
    )
    clipped = _block(
        "p1-b1",
        "",
        clipped_box,
        node_type=NodeType.TABLE,
        table=table,
        order=20,
    )

    normalized, warnings = normalize_page_blocks([clipped, valid])

    assert [block.id for block in normalized] == ["p1-b2"]
    assert warnings == ["removed duplicate block p1-b1"]
    assert normalized[0].reading_order == 0


def test_normalization_prefers_active_correction_over_rejected_duplicate() -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.2)
    rejected = _block(
        "p1-b1",
        "Grounded replacement",
        bbox,
        confidence=0.99,
        verification=VerificationState.REJECTED,
    )
    corrected = _block(
        "p1-b2",
        "Grounded replacement",
        bbox,
        confidence=0.1,
        verification=VerificationState.NEEDS_REVIEW,
    )

    normalized, warnings = normalize_page_blocks([rejected, corrected])

    assert [block.id for block in normalized] == ["p1-b2"]
    assert warnings == ["removed duplicate block p1-b1"]


def test_normalization_preserves_legitimate_repeated_prose_at_distinct_locations() -> (
    None
):
    first = _block(
        "p1-b1",
        "Plan: continue the current treatment.",
        _box(0.1, 0.1, 0.9, 0.2),
        order=1,
    )
    second = _block(
        "p1-b2",
        "Plan: continue the current treatment.",
        _box(0.1, 0.7, 0.9, 0.8),
        order=9,
    )

    normalized, warnings = normalize_page_blocks([first, second])

    assert [block.id for block in normalized] == ["p1-b1", "p1-b2"]
    assert warnings == []
    assert [block.reading_order for block in normalized] == [0, 1]


def test_normalization_rejects_conflicting_aggregate_paragraph() -> None:
    blocks = [
        _block(
            "p1-b1",
            "SYNTHETIC MEDICAL FAX - NO PHI",
            _box(0.1, 0.1, 0.7, 0.2),
            order=0,
        ),
        _block(
            "p1-b2",
            "FAX DATE: 2026-07-24",
            _box(0.1, 0.25, 0.7, 0.35),
            order=1,
        ),
        _block(
            "p1-b3",
            "SYNTHETIC MEDICAL FAX - NO PHI\nFAX DATE: 2025-07-14",
            _box(0.05, 0.05, 0.95, 0.95),
            order=2,
            verification=VerificationState.VERIFIED,
        ),
    ]

    normalized, warnings = normalize_page_blocks(blocks)

    aggregate = next(block for block in normalized if block.id == "p1-b3")
    assert aggregate.verification is VerificationState.REJECTED
    assert aggregate.verification_reason == (
        "Aggregate content conflicts with grounded page evidence"
    )
    assert warnings == ["rejected conflicting aggregate block p1-b3"]


def test_normalization_removes_redundant_aggregate_paragraph() -> None:
    blocks = [
        _block("p1-b1", "First line", _box(0.1, 0.1, 0.7, 0.2), order=0),
        _block("p1-b2", "Second line", _box(0.1, 0.25, 0.7, 0.35), order=1),
        _block(
            "p1-b3",
            "First line\nSecond line",
            _box(0.05, 0.05, 0.95, 0.95),
            order=2,
        ),
    ]

    normalized, warnings = normalize_page_blocks(blocks)

    assert [block.id for block in normalized] == ["p1-b1", "p1-b2"]
    assert warnings == ["removed redundant aggregate block p1-b3"]
