from __future__ import annotations

import pymupdf
from streamlit.testing.v1 import AppTest

from grounded_docparse import pipeline
from grounded_docparse.models import (
    Block,
    Document,
    Page,
    ParseResult,
    ProgressEvent,
    RunUsage,
    VerificationState,
)
from grounded_docparse.render import render_agentic_document, render_json


def test_studio_requires_environment(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)

    assert not app.exception
    assert len(app.file_uploader) == 1
    assert app.sidebar
    parse = next(button for button in app.button if button.label == "Parse document")
    assert parse.disabled is True
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Markdown",
        "Annotated PDF",
        "Layout Tree",
    ]


def test_stale_session_result_is_discarded(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = AppTest.from_file("streamlit_app.py")
    app.session_state["result"] = object()
    app.session_state["result_source_hash"] = "old"
    app.session_state["result_version"] = "old-contract"

    app.run(timeout=20)

    assert app.session_state["result"] is None
    assert app.session_state["result_source_hash"] is None
    assert app.session_state["result_version"] == "4.0.0"


def test_studio_shows_results_and_only_requested_tools(
    monkeypatch, simple_pdf: bytes
) -> None:
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
            if progress_callback is not None:
                for stage in ("layout", "recognize", "assemble", "annotate", "complete"):
                    progress_callback(
                        ProgressEvent(
                            stage=stage,
                            current=1,
                            total=1,
                            message=stage,
                        )
                    )
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
    monkeypatch.setattr(pipeline, "DocumentParser", FakeParser)

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)
    app.file_uploader[0].upload(
        "notice.pdf", simple_pdf, "application/pdf"
    ).run(timeout=20)
    app = next(
        button for button in app.button if button.label == "Parse document"
    ).click().run(timeout=20)

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Markdown",
        "Annotated PDF",
        "Layout Tree",
    ]
    assert [(item.label, item.value) for item in app.metric] == [
        ("Pages", "1"),
        ("Regions", "1"),
        ("Tables", "0"),
        ("Figures", "0"),
        ("Time", "0.0s"),
    ]
    assert any("Public notice" in item.value for item in app.markdown)
    assert not app.text_area
    assert any(button.label.startswith("1 · Heading") for button in app.button)
    assert [button.label for button in app.download_button] == [
        "Download Markdown",
        "Download annotated PDF",
        "Download JSON",
    ]
    assert any(
        "Luna input tokens: 1,234" in item.value for item in app.get("caption")
    )


def test_page_range_parses_a_renumbered_pdf_subset(monkeypatch) -> None:
    source = pymupdf.open()
    source.new_page().insert_text((72, 72), "First page")
    source.new_page().insert_text((72, 72), "Second page")
    source_bytes = source.tobytes()
    source.close()
    captured_page_counts: list[int] = []

    class FakeParser:
        def parse(self, data, name, progress_callback=None):
            with pymupdf.open(stream=data, filetype="pdf") as selected:
                captured_page_counts.append(selected.page_count)
            document = Document(
                source_name=name,
                source_sha256="b" * 64,
                pages=[Page(number=1, width=595, height=842)],
            )
            rendered = render_agentic_document(document)
            return ParseResult(
                document=document,
                markdown=rendered.markdown,
                json=rendered.json,
                input_tokens=0,
                output_tokens=0,
                annotated_pdf=data,
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(pipeline, "DocumentParser", FakeParser)

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)
    app.file_uploader[0].upload(
        "two-pages.pdf", source_bytes, "application/pdf"
    ).run(timeout=20)
    app = next(box for box in app.checkbox if box.label == "Page range").check().run(
        timeout=20
    )
    app = next(item for item in app.number_input if item.label == "Start").set_value(
        2
    ).run(timeout=20)
    app = next(
        button for button in app.button if button.label == "Parse document"
    ).click().run(timeout=20)

    assert not app.exception
    assert captured_page_counts == [1]
    assert app.session_state.overview_page == 1
