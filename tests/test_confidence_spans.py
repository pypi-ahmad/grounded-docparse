import json

from grounded_docparse.models import (
    AtomicDraft,
    Document,
    InspectionAction,
    InspectionDecision,
    NodeType,
    Page,
    RegionDraft,
    TableCellDraft,
    VerificationState,
)
from grounded_docparse.pipeline import _apply_decision, _block
from grounded_docparse.render import render_agentic_document, render_json


def test_agentic_confidence_evidence_uses_codepoint_spans_and_omits_them_from_legacy() -> None:
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
    legacy = json.loads(render_json(document))
    legacy_cell = legacy["pages"][0]["blocks"][0]["table"]["cells"][0]
    legacy_atom = legacy["pages"][0]["blocks"][0]["atoms"][0]

    assert payload["schema_version"] == "2.1.0"
    assert block.confidence == 0.72
    assert cell["confidence"] == 0.72
    assert cell["low_confidence_spans"] == [{"start": 1, "end": 2}]
    assert atom["confidence"] == 0.81
    assert atom["low_confidence_spans"] == [{"start": 1, "end": 2}]
    assert "confidence" not in legacy_cell
    assert "low_confidence_spans" not in legacy_cell
    assert "confidence" not in legacy_atom
    assert "low_confidence_spans" not in legacy_atom


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
    assert span == {"start": 1, "end": 3}
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
    assert span == {"start": 15, "end": 21}
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
