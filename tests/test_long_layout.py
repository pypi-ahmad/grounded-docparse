from __future__ import annotations

import pymupdf

from grounded_docparse import DocumentParser, ParserConfig


def test_repeated_headers_are_preserved_but_deduplicated_for_llms(monkeypatch) -> None:
    document = pymupdf.open()
    payload = {}
    for index in range(5):
        document.new_page()
        payload[index + 1] = {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.02, 0.9, 0.08],
                    "block_label": "header",
                    "block_order": 0,
                    "block_content": "Confidential report",
                },
                {
                    "block_bbox": [0.1, 0.2, 0.9, 0.5],
                    "block_label": "text",
                    "block_order": 1,
                    "block_content": f"Body page {index + 1}.",
                },
            ]
        }
    data = document.tobytes()
    document.close()
    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    config = ParserConfig(
        enable_paddle=True,
        enable_glm=False,
        enable_openai=False,
        render_dpi=72,
    )
    result = DocumentParser(config).parse(data, "repeated.pdf")
    headers = [node for node in result.tree.nodes.values() if node.type == "Header"]
    assert len(headers) == 5
    assert all(node.attributes.get("repeated_decoration") for node in headers)
    assert sum(
        relation.type == "repeats"
        for node in headers
        for relation in node.relationships
    ) == 4
    assert result.markdown.count("Confidential report") == 5
    assert result.llm_markdown.count("Confidential report") == 1
