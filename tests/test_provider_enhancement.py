from __future__ import annotations

import pytest

from grounded_docparse.config import CloudModel, ParserConfig
from grounded_docparse.models import Document
from grounded_docparse.pipeline import DocumentParser
from grounded_docparse.runtime import ProviderRuntime


@pytest.mark.parametrize(
    ("model", "api_key_name"),
    [
        (CloudModel.GPT_5_6_LUNA, "OPENAI_API_KEY"),
        (CloudModel.GEMINI_3_5_FLASH_LITE, "GOOGLE_API_KEY"),
        (CloudModel.GEMINI_3_7_FLASH, "GOOGLE_API_KEY"),
        (CloudModel.AGNES_2_5_FLASH, "AGNES_API_KEY"),
    ],
)
def test_enhancement_uses_selected_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    model: CloudModel,
    api_key_name: str,
) -> None:
    for name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "AGNES_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = ParserConfig(cloud_model=model)
    parser = DocumentParser(config)

    assert parser._provider_available() is False

    monkeypatch.setenv(api_key_name, "test-key")

    assert parser._provider_available() is True


def test_refinement_metadata_reports_selected_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    config = ParserConfig(cloud_model=CloudModel.GEMINI_3_7_FLASH)
    parser = DocumentParser(config)
    document = Document(source_name="empty.pdf", source_sha256="a" * 64, pages=[])

    _markdown, enhancement, _usage, _trace, _duration = parser._refine_document(
        document,
        ProviderRuntime(config),
        enabled=True,
    )

    assert enhancement.status == "failed"
    assert enhancement.model == CloudModel.GEMINI_3_7_FLASH.value
    assert enhancement.warnings == [
        "Markdown refinement had no parsed content to process"
    ]
