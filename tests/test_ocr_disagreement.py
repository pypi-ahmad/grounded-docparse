from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from grounded_docparse import pipeline
from grounded_docparse.config import AlternateOcrEngine, OcrEngine, ParserConfig
from grounded_docparse.models import Document, OcrComparisonResult, Page
from grounded_docparse.ocr_disagreement import token_edit_similarity
from grounded_docparse.render import render_agentic_document


def test_disagreement_check_defaults_off_with_bounded_budget() -> None:
    config = ParserConfig()

    assert config.ocr_disagreement_enabled is False
    assert config.ocr_disagreement_similarity_threshold == 0.90
    assert config.max_ocr_disagreement_crops == 16
    assert config.max_ocr_disagreement_crops_per_page == 2


def test_disagreement_engine_loads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOCPARSE_OCR_DISAGREEMENT_ENGINE", "rapidocr")

    config = ParserConfig.from_env()

    assert config.ocr_disagreement_engine is AlternateOcrEngine.RAPIDOCR


def test_disagreement_engine_cannot_match_primary() -> None:
    with pytest.raises(ValueError, match="must differ"):
        ParserConfig(
            ocr_engine=OcrEngine.GLM_OCR,
            ocr_disagreement_enabled=True,
            ocr_disagreement_engine=AlternateOcrEngine.VLLM_GLM_OCR,
        )


def test_disagreement_config_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        ParserConfig(max_ocr_disagreement_crops=1, max_ocr_disagreement_crops_per_page=2)


def test_token_similarity_ignores_case_punctuation_and_spacing() -> None:
    assert token_edit_similarity("Invoice # 42", " invoice—42 ") == 1.0
    assert token_edit_similarity("total 100 usd", "total 900 usd") == pytest.approx(2 / 3)


def test_parse_json_persists_ocr_comparison_evidence() -> None:
    comparison = OcrComparisonResult(
        page=1,
        bbox=(0.1, 0.2, 0.8, 0.3),
        primary_engine="glm-ocr",
        secondary_engine="paddleocr-vl-1.6",
        primary_text="Total 100",
        secondary_text="Total 900",
        similarity=0.5,
        status="disagreed",
        reason="Local OCR engines disagreed",
    )

    rendered = render_agentic_document(
        Document(
            source_name="invoice.pdf",
            source_sha256="a" * 64,
            pages=[Page(number=1, width=1, height=1)],
        ),
        ocr_comparisons=[comparison],
    )
    payload = json.loads(rendered.json)

    assert payload["schema_version"] == "4.5.0"
    assert payload["ocr_comparisons"][0]["status"] == "disagreed"


def test_cross_check_sends_only_budgeted_crops_and_restores_primary(
    monkeypatch, tmp_path
) -> None:
    candidates = [
        pipeline._RecoveryCandidate(
            page=1,
            bbox=(0.1, 0.1 + index * 0.2, 0.8, 0.2 + index * 0.2),
            severity=index,
            confidence=0.2,
            reading_order=index,
            target_id=str(index),
            primary_text=f"value {index}",
        )
        for index in range(3)
    ]
    monkeypatch.setattr(pipeline, "_page_recovery_candidates", lambda *_args: candidates)
    rendered = []

    def fake_crop(*_args, **kwargs):
        rendered.append(kwargs.get("output", _args[3]))
        return _args[3]

    monkeypatch.setattr(pipeline, "render_region_crop", fake_crop)
    runtime = SimpleNamespace(
        parse_recovery_image=lambda path: SimpleNamespace(
            regions=[SimpleNamespace(content=f"alternate {path.stem}")]
        )
    )
    monkeypatch.setattr(pipeline, "get_paddleocr_runtime", lambda *_args: runtime)
    switches = []
    parser = pipeline.DocumentParser(
        ParserConfig(
            ocr_disagreement_enabled=True,
            max_ocr_disagreement_crops=2,
            max_ocr_disagreement_crops_per_page=2,
        ),
        ocr_service_switcher=switches.append,
    )

    results, candidate_count, _duration = parser._cross_check_uncertain_regions(
        SimpleNamespace(),
        [SimpleNamespace(number=1)],
        {1: SimpleNamespace()},
        tmp_path,
    )

    assert candidate_count == 3
    assert len(rendered) == len(results) == 2
    assert switches == [pipeline.OcrEngine.PADDLEOCR_VL_1_6, pipeline.OcrEngine.GLM_OCR]
