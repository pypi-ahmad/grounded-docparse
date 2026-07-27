from __future__ import annotations

from streamlit.testing.v1 import AppTest

from grounded_docparse import extraction, pipeline
from grounded_docparse.models import (
    Block,
    Document,
    ExtractionResult,
    Page,
    ParseResult,
    RunUsage,
    SchemaProposal,
    VerificationState,
)
from grounded_docparse.render import render_agentic_document, render_json


def test_single_page_app_requires_environment(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)

    assert not app.exception
    assert len(app.file_uploader) == 1
    assert not app.sidebar
    parse = next(button for button in app.button if button.label == "Parse document")
    assert parse.disabled is True


def test_stale_session_result_is_discarded(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    app = AppTest.from_file("streamlit_app.py")
    app.session_state["result"] = object()
    app.session_state["result_source_hash"] = "old"
    app.session_state["result_version"] = "old-contract"

    app.run(timeout=20)

    assert app.session_state["result"] is None
    assert app.session_state["result_source_hash"] is None
    assert app.session_state["result_version"] == "2.0.0"


def test_single_page_app_shows_markdown_and_json_result(monkeypatch, simple_pdf: bytes) -> None:
    document = Document(
        source_name="notice.pdf",
        source_sha256="a" * 64,
        pages=[
            Page(
                number=1,
                width=612,
                height=792,
                blocks=[
                    Block(
                        id="p1-b1",
                        type="heading",
                        text="Public notice",
                        reading_order=0,
                        verification=VerificationState.VERIFIED,
                    )
                ],
            )
        ],
    )

    class FakeParser:
        def parse(self, _data, _name, progress_callback=None):
            rendered = render_agentic_document(document)
            return ParseResult(
                document=document,
                markdown=rendered.markdown,
                json=rendered.json,
                legacy_json=render_json(document),
                input_tokens=1_234,
                output_tokens=56,
                annotated_pdf=simple_pdf,
                usage=RunUsage(),
                trace=[],
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(pipeline, "DocumentParser", FakeParser)

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)
    app.file_uploader[0].upload("notice.pdf", simple_pdf, "application/pdf").run(timeout=20)
    app = next(button for button in app.button if button.label == "Parse document").click().run(timeout=20)

    assert not app.exception
    assert any("Public notice" in item.value for item in app.markdown)
    assert [(item.label, item.value) for item in app.metric] == [
        ("Input tokens", "1,234"),
        ("Output tokens", "56"),
    ]
    tabs = [tab.label for tab in app.tabs]
    assert "Markdown" in tabs
    assert "Agentic JSON" in tabs
    assert "Legacy JSON" in tabs
    assert "Annotated PDF" in tabs
    assert "Agent trace" in tabs
    assert "Extract" in tabs
    downloads = [button.label for button in app.download_button]
    assert "Download Markdown" in downloads
    assert "Download agentic JSON" in downloads
    assert "Download legacy JSON" in downloads
    assert "Download annotated PDF" in downloads


def test_extract_tab_generates_schema_and_grounded_data(
    monkeypatch, simple_pdf: bytes
) -> None:
    document = Document(
        source_name="notice.pdf",
        source_sha256="b" * 64,
        pages=[Page(number=1, width=612, height=792)],
    )
    rendered = render_agentic_document(document)
    parse_result = ParseResult(
        document=document,
        markdown=rendered.markdown,
        json=rendered.json,
        legacy_json=render_json(document),
        input_tokens=10,
        output_tokens=4,
        annotated_pdf=simple_pdf,
        usage=RunUsage(),
        trace=[],
    )
    schema = {
        "type": "object",
        "properties": {"name": {"type": ["string", "null"]}},
        "required": ["name"],
        "additionalProperties": False,
    }

    class FakeParser:
        def parse(self, *_args, **_kwargs):
            return parse_result

    class FakeExtractor:
        def propose_schema(self, instruction, _result):
            return SchemaProposal(
                instruction=instruction,
                json_schema=schema,
                usage=RunUsage(),
            )

        def extract(self, _result, selected_schema):
            assert selected_schema == schema
            return ExtractionResult(
                data={"name": "Ada"},
                evidence={"/name": [{"block_id": "p1-b1"}]},
                json='{"data":{"name":"Ada"}}',
                warnings=[],
                input_tokens=20,
                output_tokens=5,
                usage=RunUsage(),
                trace=[],
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(pipeline, "DocumentParser", FakeParser)
    monkeypatch.setattr(extraction, "DocumentExtractor", FakeExtractor)

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)
    app.file_uploader[0].upload("notice.pdf", simple_pdf, "application/pdf").run(timeout=20)
    app = next(button for button in app.button if button.label == "Parse document").click().run(timeout=20)
    instruction = next(area for area in app.text_area if area.label == "Fields to extract")
    app = instruction.set_value("Extract the name").run(timeout=20)
    app = next(button for button in app.button if button.label == "Generate schema").click().run(timeout=20)

    assert any(area.label == "JSON Schema" for area in app.text_area)
    app = next(button for button in app.button if button.label == "Run extraction").click().run(timeout=20)

    assert not app.exception
    assert any("Ada" in item.value for item in app.json)
    assert any(button.label == "Download extraction JSON" for button in app.download_button)
