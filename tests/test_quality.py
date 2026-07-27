from __future__ import annotations

from pathlib import Path

from grounded_docparse.ingest import PageEvidence, TextBlock
from grounded_docparse.models import (
    Block,
    BoundingBox,
    Citation,
    NodeType,
    TableCell,
    TableData,
    VerificationState,
)
from grounded_docparse.quality import (
    find_missing_source_regions,
    normalize_page_blocks,
    select_repair_blocks,
)


def _box(x0: float, y0: float, x1: float, y1: float) -> BoundingBox:
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _page(*source_blocks: tuple[str, BoundingBox], scanned: bool = False) -> PageEvidence:
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
        verification=verification,
        citation=Citation(page=1, bbox=bbox),
    )


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


def test_source_region_with_at_least_seventy_percent_coverage_is_not_recovered() -> None:
    bbox = _box(0.1, 0.1, 0.9, 0.2)
    page = _page(("Location address or name of sampling point", bbox))
    blocks = [_block("p1-b1", "Location address name of sampling point", bbox)]

    assert find_missing_source_regions(page, blocks) == []


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


def test_normalization_preserves_legitimate_repeated_prose_at_distinct_locations() -> None:
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
