from __future__ import annotations

from huggingface_hub.errors import LocalEntryNotFoundError

from grounded_docparse import grounded_ocr, windows_setup
from grounded_docparse.ollama_runtime import OllamaOcrModel


def test_layout_model_uses_local_cache_before_network(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        grounded_ocr,
        "_snapshot_layout_model",
        lambda *, local_files_only: calls.append(local_files_only),
    )

    grounded_ocr.ensure_layout_model()

    assert calls == [True]


def test_layout_model_downloads_only_when_local_cache_is_missing(monkeypatch) -> None:
    calls = []

    def snapshot(*, local_files_only):
        calls.append(local_files_only)
        if local_files_only:
            raise LocalEntryNotFoundError("missing")

    monkeypatch.setattr(grounded_ocr, "_snapshot_layout_model", snapshot)

    grounded_ocr.ensure_layout_model()

    assert calls == [True, False]


def test_prepare_models_ensures_layout_and_every_supported_ollama_model(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(windows_setup, "ensure_layout_model", lambda: calls.append("layout"))
    monkeypatch.setattr(
        windows_setup, "ensure_model", lambda model: calls.append(model)
    )

    windows_setup.prepare_models()

    assert calls == ["layout", *OllamaOcrModel]
