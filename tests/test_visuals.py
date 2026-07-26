from __future__ import annotations

from grounded_docparse import DocumentParser, ParserConfig, ProcessingProfile
from grounded_docparse.models import PageVerification, RunRecord


def test_chart_has_typed_grounded_visual_data(simple_pdf: bytes, monkeypatch) -> None:
    payload = {
        1: {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.1, 0.9, 0.7],
                    "block_label": "chart",
                    "block_order": 0,
                    "block_content": "Revenue 2025 100",
                    "chart_type": "bar",
                    "chart_title": "Revenue",
                    "axes": ["Year", "USD"],
                    "legends": ["Revenue"],
                    "chart_data": [
                        {
                            "series": "Revenue",
                            "label": "2025",
                            "value": "100",
                            "source_text": "2025 100",
                        }
                    ],
                }
            ]
        }
    }
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
    result = DocumentParser(config).parse(simple_pdf, "chart.pdf")
    chart = next(node for node in result.tree.nodes.values() if node.type == "Chart")
    assert chart.visual_analysis
    assert chart.visual_analysis.chart_type == "bar"
    assert chart.visual_analysis.data_points[0].value == "100"
    assert chart.visual_analysis.derived_summary is None
    assert "data-role=\"chart-data\"" in result.llm_markdown


def test_visual_summary_is_only_added_in_maximum_accuracy(
    simple_pdf: bytes, monkeypatch
) -> None:
    payload = {
        1: {
            "parsing_res_list": [
                {
                    "block_bbox": [0.1, 0.1, 0.9, 0.7],
                    "block_label": "chart",
                    "block_order": 0,
                    "block_content": "A 10",
                    "chart_data": [{"label": "A", "value": "10"}],
                }
            ]
        }
    }

    class FakeOpenAI:
        def __init__(self, _config):
            pass

        def verify_page(self, _page, _regions):
            return PageVerification(), RunRecord(
                provider="openai", model="luna", stage="page_verification"
            )

    monkeypatch.setattr(
        "grounded_docparse.pipeline.PaddleDockerRunner.run",
        lambda *_args, **_kwargs: payload,
    )
    monkeypatch.setattr("grounded_docparse.pipeline.OpenAIDocumentGateway", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = ParserConfig(
        enable_paddle=True,
        enable_glm=False,
        enable_openai=True,
        render_dpi=72,
    )
    result = DocumentParser(config).parse(
        simple_pdf,
        "chart.pdf",
        profile=ProcessingProfile.MAXIMUM_ACCURACY,
    )
    chart = next(node for node in result.tree.nodes.values() if node.type == "Chart")
    assert chart.visual_analysis
    assert chart.visual_analysis.derived_summary
    assert chart.visual_analysis.summary_literal is False
    assert 'data-derived="true"' in result.llm_markdown
