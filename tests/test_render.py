from grounded_docparse.models import DocumentNode, NodeType
from grounded_docparse.render import render_node


def test_table_renderer_preserves_spans_and_escapes_text() -> None:
    node = DocumentNode(
        id="table-1",
        type=NodeType.TABLE,
        text="fallback",
        attributes={
            "table_rows": [
                [{"text": "A < B", "header": True, "colspan": 2}],
                [{"text": "1"}, {"text": "2"}],
            ]
        },
    )
    rendered = render_node(node)
    assert 'colspan="2"' in rendered
    assert "A &lt; B" in rendered
    assert "<script" not in rendered


def test_heading_cannot_inject_html() -> None:
    node = DocumentNode(
        id="heading",
        type=NodeType.HEADING,
        text="<script>alert(1)</script>",
    )
    rendered = render_node(node)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
