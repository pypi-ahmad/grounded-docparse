from __future__ import annotations

import pymupdf
from streamlit.testing.v1 import AppTest

from grounded_docparse import pipeline
from grounded_docparse.agentic import DocumentAgent
from grounded_docparse.models import (
    AgenticAnalysis,
    Block,
    Document,
    Page,
    ParseMetadata,
    ParseResult,
    ProgressEvent,
    RunUsage,
    VerificationState,
)
from grounded_docparse.render import build_elements, render_agentic_document


def test_studio_allows_glm_without_openai_environment(
    monkeypatch, simple_pdf: bytes
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)

    assert not app.exception
    assert len(app.file_uploader) == 1
    assert app.sidebar
    app = app.file_uploader[0].upload(
        "notice.pdf", simple_pdf, "application/pdf"
    ).run(timeout=20)
    parse = next(button for button in app.button if button.label == "Parse document")
    assert parse.disabled is False
    assert next(item for item in app.selectbox if item.label == "ADE mode").value == "Fast"
    assert not next(
        toggle.value
        for toggle in app.toggle
        if toggle.label == "Enhance with gpt-5.6-luna"
    )
    recovery = next(
        toggle
        for toggle in app.toggle
        if toggle.label == "Enable visual recovery on hard regions"
    )
    assert recovery.disabled is True
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
    assert app.session_state["result_version"] == "4.4.0"


def test_ade_presets_default_fast_and_allow_full_or_custom(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    app = AppTest.from_file("streamlit_app.py").run(timeout=20)

    mode = next(item for item in app.selectbox if item.label == "ADE mode")
    assert mode.value == "Fast"
    app = mode.select("Full").run(timeout=20)
    toggles = {item.label: item for item in app.toggle}
    assert toggles["Enhance with gpt-5.6-luna"].value is True
    assert toggles["Classify document type"].value is True
    assert toggles["Generate table of contents"].value is True
    assert toggles["Enable document chat"].value is False
    assert toggles["Enable visual recovery on hard regions"].value is True

    app = toggles["Generate table of contents"].set_value(False).run(timeout=20)
    assert next(item for item in app.selectbox if item.label == "ADE mode").value == "Custom"


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
        def parse(
            self,
            _data,
            _name,
            progress_callback=None,
            *,
            refine_markdown=True,
            visual_recovery=True,
        ):
            assert visual_recovery is True
            del refine_markdown
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
                input_tokens=1_234,
                output_tokens=56,
                annotated_pdf=simple_pdf,
                usage=RunUsage(),
                trace=[],
                elements=build_elements(document, {"p1-b1"}),
                metadata=ParseMetadata(
                    visual_recovery_candidates=1,
                    visual_recovery_crops=1,
                    visual_recovery_region_ids=["p1-b1"],
                ),
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(pipeline, "DocumentParser", FakeParser)
    monkeypatch.setattr(DocumentAgent, "analyze", lambda self, *args, **kwargs: AgenticAnalysis())

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
        "Extract",
        "Layout Tree",
    ]
    assert next(item for item in app.metric if item.label == "Recovered").value == "1"
    assert [(item.label, item.value) for item in app.metric] == [
        ("Pages", "1"),
        ("Regions", "1"),
        ("Tables", "0"),
        ("Figures", "0"),
        ("Time", "0.0s"),
        ("Recovered", "1"),
    ]
    assert not app.text_area
    assert [button.label for button in app.download_button] == [
        "Download Markdown",
        "Download annotated PDF",
        "Download Full JSON",
    ]
    assert any(
        "Luna input tokens: 1,234" in item.value for item in app.get("caption")
    )

    app.session_state["studio_tab"] = "Markdown"
    app = app.run(timeout=20)
    assert any("Public notice" in item.value for item in app.markdown)

    app.session_state["studio_tab"] = "Extract"
    app = app.run(timeout=20)
    assert not app.exception
    assert any("Define the field keys" in item.value for item in app.get("caption"))
    assert any(button.label == "Run extraction" for button in app.button) is False

    app.session_state["studio_tab"] = "Layout Tree"
    app = app.run(timeout=20)
    assert any(button.label.startswith("1 · Heading") for button in app.button)
    assert any("Luna" in item.value for item in app.markdown)


def test_page_range_parses_a_renumbered_pdf_subset(monkeypatch) -> None:
    source = pymupdf.open()
    source.new_page().insert_text((72, 72), "First page")
    source.new_page().insert_text((72, 72), "Second page")
    source_bytes = source.tobytes()
    source.close()
    captured_page_counts: list[int] = []
    captured_recovery: list[bool] = []

    class FakeParser:
        def parse(
            self,
            data,
            name,
            progress_callback=None,
            *,
            refine_markdown=True,
            visual_recovery=True,
        ):
            del refine_markdown
            captured_recovery.append(visual_recovery)
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
    monkeypatch.setattr(DocumentAgent, "analyze", lambda self, *args, **kwargs: AgenticAnalysis())

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
        item
        for item in app.toggle
        if item.label == "Enable visual recovery on hard regions"
    ).set_value(False).run(timeout=20)
    app = next(
        button for button in app.button if button.label == "Parse document"
    ).click().run(timeout=20)

    assert not app.exception
    assert captured_page_counts == [1]
    assert captured_recovery == [False]
    assert app.session_state.overview_page == 1
