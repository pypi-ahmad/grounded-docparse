from __future__ import annotations

from huggingface_hub.errors import LocalEntryNotFoundError

from grounded_docparse import docling_native, grounded_ocr, windows_setup
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
    monkeypatch.setattr(
        windows_setup,
        "ensure_docling_models",
        lambda: calls.append("docling"),
    )

    windows_setup.prepare_models()

    assert calls == ["layout", *OllamaOcrModel, "docling"]


def test_docling_models_use_valid_persistent_manifest_before_downloading(
    monkeypatch, tmp_path
) -> None:
    calls = []
    monkeypatch.setattr(docling_native, "docling_artifacts_path", lambda: tmp_path)

    def download_models(**kwargs) -> None:
        calls.append(kwargs)
        model = tmp_path / "rapidocr" / "model.onnx"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"weights")

    monkeypatch.setattr(
        "docling.utils.model_downloader.download_models", download_models
    )

    assert docling_native.ensure_docling_models() == tmp_path
    assert docling_native.ensure_docling_models() == tmp_path

    assert len(calls) == 1
    assert calls[0]["force"] is False
    assert calls[0]["with_layout"] is True
    assert calls[0]["with_tableformer"] is True
    assert calls[0]["with_rapidocr"] is True
