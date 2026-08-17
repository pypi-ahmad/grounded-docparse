from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from streamlit.testing.v1 import AppTest

from grounded_docparse.native import NativeDocument, NativeExtractedValue

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = ROOT / "demo" / "fixtures" / "native_text_showcase.json"


def test_showcase_fixture_preserves_exact_native_evidence() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    document = NativeDocument.model_validate(fixture["document"])
    values = [
        NativeExtractedValue.model_validate(value)
        for value in fixture["extraction"]["values"]
    ]

    source = ROOT / "benchmarks" / "corpus-v1" / "documents" / "native-text.pdf"
    assert sha256(source.read_bytes()).hexdigest() == document.source_sha256

    for value in values:
        interval = value.evidence.char_interval
        assert (
            document.base_text[interval.start : interval.end]
            == value.evidence.source_text
        )
        assert document.source_spans_for(interval.start, interval.end)


def test_showcase_is_read_only_and_starts_without_services() -> None:
    app = AppTest.from_file(
        ROOT / "demo" / "streamlit_app.py", default_timeout=30
    ).run()

    assert not app.exception
    assert app.title[0].value == "Grounded Document Parser"
    assert any("Synthetic read-only demonstration" in item.value for item in app.info)
    assert len(app.file_uploader) == 0
    process = next(
        button for button in app.button if button.label == "Process document"
    )
    assert process.disabled is True
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Markdown",
        "Extract",
        "Source structure",
        "JSON",
    ]
