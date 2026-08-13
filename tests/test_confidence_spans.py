import json

from grounded_docparse.models import (
    AtomicDraft,
    ConfidenceSpan,
    Document,
    InspectionAction,
    InspectionDecision,
    NodeType,
    Page,
    RegionDraft,
    SpanRepairAction,
    SpanRepairDecision,
    SpanRepairTarget,
    TableCellDraft,
    VerificationState,
)
from grounded_docparse.pipeline import _apply_decision, _apply_span_repairs, _block
from grounded_docparse.render import render_agentic_document


def test_agentic_confidence_evidence_uses_codepoint_spans() -> None:
    region = RegionDraft(
        type=NodeType.TABLE,
        reading_order=0,
        confidence=0.96,
        table_cells=[
            TableCellDraft(
                row_index=0,
                column_index=0,
                text="x😀y",
                confidence=0.72,
                low_confidence_spans=[{"start": 1, "end": 2}],
            )
        ],
        atoms=[
            AtomicDraft(
                kind="transcription",
                text="x😀y",
                confidence=0.81,
                low_confidence_spans=[{"start": 1, "end": 2}],
            )
        ],
    )
    block = _block(region, page_number=1, index=0)
    document = Document(
        source_name="span.pdf",
        source_sha256="a" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    payload = json.loads(render_agentic_document(document).json)
    node = payload["document"]["pages"][0]["blocks"][0]
    cell = node["semantic"]["table"]["cells"][0]
    atom = node["atoms"][0]
    assert payload["schema_version"] == "4.5.0"
    assert block.confidence == 0.72
    assert cell["confidence"] == 0.72
    assert cell["low_confidence_spans"] == [
        {
            "start": 1,
            "end": 2,
            "text": "😀",
            "confidence": 0.72,
            "source": "provider",
            "bbox": None,
        }
    ]
    assert atom["confidence"] == 0.81
    assert atom["low_confidence_spans"] == [
        {
            "start": 1,
            "end": 2,
            "text": "😀",
            "confidence": 0.81,
            "source": "provider",
        }
    ]


def test_invalid_confidence_evidence_is_discarded_and_cannot_be_verified() -> None:
    region = RegionDraft(
        type=NodeType.PARAGRAPH,
        text="x😀y",
        reading_order=0,
        confidence=0.99,
        atoms=[
            AtomicDraft(
                kind="transcription",
                text="x😀y",
                low_confidence_spans=[{"start": 1, "end": 4}],
            )
        ],
    )
    block = _block(region, page_number=1, index=0)

    _apply_decision(
        block,
        InspectionDecision(region_id="p1-b1", action=InspectionAction.ACCEPT),
        page_number=1,
    )

    assert block.atoms[0].low_confidence_spans == []
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "Invalid confidence evidence"


def test_emitted_table_atom_rebases_span_for_markdown_escaping() -> None:
    block = _block(
        RegionDraft(
            type=NodeType.TABLE,
            reading_order=0,
            table_cells=[
                TableCellDraft(
                    row_index=0,
                    column_index=0,
                    text="a|b",
                    low_confidence_spans=[{"start": 1, "end": 2}],
                )
            ],
        ),
        page_number=1,
        index=0,
    )
    document = Document(
        source_name="table.pdf",
        source_sha256="b" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    atoms = json.loads(render_agentic_document(document).json)["document"]["pages"][0][
        "blocks"
    ][0]["atoms"]
    atom = next(item for item in atoms if item["kind"] == "table_cell")
    span = atom["low_confidence_spans"][0]

    assert atom["text"] == r"a\|b"
    assert span == {
        "start": 1,
        "end": 3,
        "text": r"\|",
        "confidence": 0.5,
        "source": "provider",
    }
    assert atom["text"][span["start"] : span["end"]] == r"\|"


def test_emitted_visual_atom_rebases_span_for_its_label() -> None:
    block = _block(
        RegionDraft(
            type=NodeType.FIGURE,
            reading_order=0,
            atoms=[
                AtomicDraft(
                    kind="transcription",
                    text="Needle",
                    low_confidence_spans=[{"start": 0, "end": 6}],
                )
            ],
        ),
        page_number=1,
        index=0,
    )
    document = Document(
        source_name="visual.pdf",
        source_sha256="c" * 64,
        pages=[Page(number=1, width=100, height=100, blocks=[block])],
    )

    atom = json.loads(render_agentic_document(document).json)["document"]["pages"][0][
        "blocks"
    ][0]["atoms"][0]
    span = atom["low_confidence_spans"][0]

    assert atom["text"] == "Transcription: Needle"
    assert span == {
        "start": 15,
        "end": 21,
        "text": "Needle",
        "confidence": 0.5,
        "source": "provider",
    }
    assert atom["text"][span["start"] : span["end"]] == "Needle"


def test_cleaning_discards_span_that_targets_removed_soft_hyphen() -> None:
    block = _block(
        RegionDraft(
            type=NodeType.PARAGRAPH,
            reading_order=0,
            atoms=[
                AtomicDraft(
                    kind="transcription",
                    text="a\u00adbcd",
                    low_confidence_spans=[{"start": 1, "end": 2}],
                )
            ],
        ),
        page_number=1,
        index=0,
    )

    assert block.atoms[0].text == "abcd"
    assert block.atoms[0].low_confidence_spans == []
    assert block.verification is VerificationState.NEEDS_REVIEW
    assert block.verification_reason == "Invalid confidence evidence"


def test_targeted_repair_replaces_only_exact_literal_and_records_provenance() -> None:
    block = _block(
        RegionDraft(
            type=NodeType.PARAGRAPH,
            text="Account l23 beside l24",
            reading_order=0,
            confidence=0.9,
            atoms=[
                AtomicDraft(
                    kind="line",
                    text="Account l23 beside l24",
                    confidence=0.4,
                    low_confidence_spans=[
                        ConfidenceSpan(start=8, end=9, text="l", source="luna")
                    ],
                )
            ],
        ),
        page_number=1,
        index=0,
    )
    target = SpanRepairTarget(
        target_id="p1-b1:atom:0:0",
        region_id=block.id,
        owner_kind="atom",
        owner_index=0,
        start=8,
        end=9,
        text="l",
        confidence=0.4,
        source="luna",
        evidence_ref="page:1:p1-b1:atom:0:0",
    )
    decision = SpanRepairDecision(
        target_id=target.target_id,
        action=SpanRepairAction.REPLACE,
        replacement_text="1",
        confidence=0.99,
        evidence_ref=target.evidence_ref,
    )

    _apply_span_repairs(block, [target], [decision], repair_source="gpt-5.6-luna")

    assert block.text == "Account 123 beside l24"
    assert block.atoms[0].text == "Account 123 beside l24"
    assert block.atoms[0].low_confidence_spans == []
    assert len(block.correction_lineage) == 1
    assert block.correction_lineage[0].provider_id == target.target_id
    assert "luna" in block.correction_lineage[0].reason
    assert "source=luna" in block.correction_lineage[0].reason


def test_stale_target_does_not_replace_adjacent_text() -> None:
    block = _block(
        RegionDraft(
            type=NodeType.PARAGRAPH,
            text="AA11",
            reading_order=0,
            atoms=[AtomicDraft(kind="line", text="AA11")],
        ),
        page_number=1,
        index=0,
    )
    target = SpanRepairTarget(
        target_id="p1-b1:atom:0:0",
        region_id=block.id,
        owner_kind="atom",
        owner_index=0,
        start=1,
        end=2,
        text="Z",
        confidence=0.2,
        source="provider",
        evidence_ref="page:1:p1-b1:atom:0:0",
    )
    decision = SpanRepairDecision(
        target_id=target.target_id,
        action=SpanRepairAction.REPLACE,
        replacement_text="B",
        evidence_ref=target.evidence_ref,
    )

    _apply_span_repairs(block, [target], [decision], repair_source="gpt-5.6-luna")

    assert block.text == "AA11"
    assert block.atoms[0].text == "AA11"
    assert block.verification is VerificationState.NEEDS_REVIEW


def test_targeted_table_cell_repair_preserves_neighboring_cell() -> None:
    block = _block(
        RegionDraft(
            type=NodeType.TABLE,
            reading_order=0,
            table_cells=[
                TableCellDraft(
                    row_index=0,
                    column_index=0,
                    text="l23",
                    confidence=0.3,
                    low_confidence_spans=[{"start": 0, "end": 1}],
                ),
                TableCellDraft(row_index=0, column_index=1, text="l24"),
            ],
            atoms=[AtomicDraft(kind="table_cell", text="l23")],
        ),
        page_number=1,
        index=0,
    )
    target = SpanRepairTarget(
        target_id="p1-b1:table_cell:0:0",
        region_id=block.id,
        owner_kind="table_cell",
        owner_index=0,
        start=0,
        end=1,
        text="l",
        confidence=0.3,
        source="provider",
        evidence_ref="page:1:p1-b1:table_cell:0:0",
    )
    decision = SpanRepairDecision(
        target_id=target.target_id,
        action=SpanRepairAction.REPLACE,
        replacement_text="1",
        confidence=0.98,
        evidence_ref=target.evidence_ref,
    )

    _apply_span_repairs(block, [target], [decision], repair_source="gpt-5.6-luna")

    assert [cell.text for cell in block.table.cells] == ["123", "l24"]
    assert block.atoms[0].text == "123"
