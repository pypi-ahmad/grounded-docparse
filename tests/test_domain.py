from __future__ import annotations

import pymupdf

from grounded_docparse import DocumentParser, DocumentProfile, ParserConfig


def offline_config(**values) -> ParserConfig:
    return ParserConfig(
        enable_paddle=False,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
        **values,
    )


def document_with_lines(lines: list[str], pages: int = 1) -> bytes:
    document = pymupdf.open()
    for page_number in range(pages):
        page = document.new_page()
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + index * 28), line.format(page=page_number + 1))
    data = document.tobytes()
    document.close()
    return data


def test_invoice_profile_extracts_grounded_fields_and_validation() -> None:
    data = document_with_lines(
        [
            "INVOICE",
            "Invoice Number: INV-42",
            "Subtotal: $100.00",
            "Tax: $5.00",
            "Total: $110.00",
            "Payment Terms: Net 30",
        ]
    )
    tree = DocumentParser(offline_config()).parse(data, "invoice.pdf").tree
    assert tree.document_classification
    assert tree.document_classification.profile == "invoice"
    fields = {field.path: field for field in tree.grounded_fields}
    assert fields["invoice.number"].normalized_value == "INV-42"
    assert fields["invoice.total"].normalized_value == "110.00"
    assert fields["invoice.total"].sources[0].page_number == 1
    assert fields["invoice.total"].sources[0].bbox is not None
    assert any(
        finding.code == "invoice_total_mismatch"
        for finding in tree.validation_findings
    )


def test_document_profile_override_is_recorded() -> None:
    data = document_with_lines(["Generic content", "No profile terms here"])
    tree = DocumentParser(offline_config()).parse(
        data,
        "technical.pdf",
        document_profile=DocumentProfile.TECHNICAL_DOCUMENTATION,
    ).tree
    assert tree.document_classification
    assert tree.document_classification.profile == "technical-documentation"
    assert tree.document_classification.method == "user_override"


def test_long_document_uses_ten_page_windows() -> None:
    data = document_with_lines(["Page {page}", "Grounded content"], pages=21)
    tree = DocumentParser(offline_config(page_window_size=10)).parse(
        data, "long.pdf"
    ).tree
    assert [(item.start_page, item.end_page) for item in tree.window_runs] == [
        (1, 10),
        (11, 20),
        (21, 21),
    ]
    assert all(item.status == "complete" for item in tree.window_runs)
