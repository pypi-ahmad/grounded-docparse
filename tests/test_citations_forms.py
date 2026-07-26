from __future__ import annotations

import json

import pymupdf

from grounded_docparse import DocumentParser, ParserConfig


def parser_config(*, paddle: bool = False) -> ParserConfig:
    return ParserConfig(
        enable_paddle=paddle,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
    )


def test_table_cells_use_exact_or_inherited_grounding(
    simple_pdf: bytes, monkeypatch
) -> None:
    payload = {
        1: {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.1, 0.9, 0.5],
                    "block_label": "table",
                    "block_order": 0,
                    "block_content": "A B",
                    "table_rows": [
                        [
                            {"text": "A", "bbox": [0.1, 0.1, 0.4, 0.2], "score": 0.9},
                            {"text": "B"},
                        ]
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    result = DocumentParser(parser_config(paddle=True)).parse(simple_pdf, "table.pdf")
    table = next(node for node in result.tree.nodes.values() if node.type == "Table")
    row = result.tree.nodes[table.children_ids[0]]
    exact, inherited = (result.tree.nodes[node_id] for node_id in row.children_ids)
    assert exact.citations[0].grounding_scope == "exact"
    assert exact.citations[0].bbox == exact.bbox
    assert inherited.citations[0].grounding_scope == "table"
    assert inherited.citations[0].bbox == table.bbox
    assert inherited.citations[0].parent_citation_id == table.citations[0].id
    assert 'data-grounding-scope="exact"' in result.llm_markdown
    assert 'data-grounding-scope="table"' in result.llm_markdown


def test_paddle_table_result_provides_exact_pixel_cell_grounding(
    simple_pdf: bytes, monkeypatch
) -> None:
    payload = {
        1: {
            "parsing_res_list": [
                {
                    "block_bbox": [0, 0, 612, 300],
                    "block_label": "table",
                    "block_order": 0,
                    "block_content": "A B",
                }
            ],
            "table_res_list": [
                {
                    "pred_html": "<table><tr><td>A</td><td>B</td></tr></table>",
                    "cell_box_list": [[0, 0, 306, 100], [306, 0, 612, 100]],
                }
            ],
        }
    }
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    result = DocumentParser(parser_config(paddle=True)).parse(simple_pdf, "table.pdf")
    cells = [node for node in result.tree.nodes.values() if node.type == "TableCell"]
    assert len(cells) == 2
    assert all(cell.citations[0].grounding_scope == "exact" for cell in cells)
    assert cells[0].bbox and cells[0].bbox.x1 == 0.5


def test_form_fields_are_derived_without_replacing_source_text() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Member ID: ABC-123")
    data = document.tobytes()
    document.close()
    result = DocumentParser(parser_config()).parse(data, "form.pdf")
    source = next(
        node for node in result.tree.nodes.values() if node.type == "Paragraph"
    )
    form = next(node for node in result.tree.nodes.values() if node.type == "FormField")
    assert form.form_field
    assert form.form_field.label == "Member ID"
    assert form.form_field.value == "ABC-123"
    assert form.citations[0].grounding_scope == "exact"
    assert any(
        relation.type == "derived_from" and relation.target_id == source.id
        for relation in form.relationships
    )
    assert "## Grounded form fields" in result.llm_markdown


def test_checkbox_state_is_preserved(simple_pdf: bytes, monkeypatch) -> None:
    payload = {
        1: {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.1, 0.3, 0.2],
                    "block_label": "checkbox",
                    "block_order": 0,
                    "block_content": "Accept terms",
                    "state": "checked",
                }
            ]
        }
    }
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    result = DocumentParser(parser_config(paddle=True)).parse(simple_pdf, "form.pdf")
    checkbox = next(node for node in result.tree.nodes.values() if node.type == "Checkbox")
    assert checkbox.form_field and checkbox.form_field.state == "checked"
    assert "[x] Accept terms" in result.llm_markdown


def test_audit_reports_complete_content_citation_coverage(simple_pdf: bytes) -> None:
    result = DocumentParser(parser_config()).parse(simple_pdf, "test.pdf")
    audit = json.loads(result.audit_json)
    assert audit["citation_coverage"]["coverage"] == 1
    assert audit["document_schema_version"] == "1.9.0"
    assert audit["schema_version"] == "1.2.0"
    for page in result.tree.pages:
        assert all(result.tree.nodes[node_id].citations for node_id in page.content_node_ids)
