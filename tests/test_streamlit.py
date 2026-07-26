import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_pdf_previews_have_unique_explicit_keys() -> None:
    tree = ast.parse(Path("streamlit_app.py").read_text(encoding="utf-8"))
    pdf_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "pdf"
    ]
    keys = [
        keyword.value.value
        for call in pdf_calls
        for keyword in call.keywords
        if keyword.arg == "key" and isinstance(keyword.value, ast.Constant)
    ]

    assert len(keys) == len(pdf_calls)
    assert len(keys) == len(set(keys))


def test_app_defaults_to_balanced_async_processing(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    app = AppTest.from_file("streamlit_app.py").run(timeout=20)
    assert not app.exception
    assert app.sidebar.segmented_control[0].value == "API"
    assert app.segmented_control[0].value == "Parse"
    assert app.selectbox[0].value == "balanced"
    assert app.button[0].disabled is True


def test_app_requires_api_token_before_submission(monkeypatch) -> None:
    monkeypatch.delenv("DOCPARSE_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    app = AppTest.from_file("streamlit_app.py").run(timeout=20)
    assert not app.exception
    assert app.text_input[1].value == ""
    assert app.button[0].disabled is True


def test_app_defaults_to_local_processing_with_openai_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")

    app = AppTest.from_file("streamlit_app.py").run(timeout=20)

    assert not app.exception
    assert app.sidebar.segmented_control[0].value == "Local"
    assert all(item.label not in {"API URL", "API token"} for item in app.text_input)
