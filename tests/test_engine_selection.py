from __future__ import annotations

import pytest

from grounded_docparse.config import ExtractionEngine
from grounded_docparse import ocr_services
from grounded_docparse.ollama_runtime import OllamaOcrModel, region_prompt


def test_engine_catalog_has_one_vllm_mapping_per_gpu_engine() -> None:
    assert ExtractionEngine.PADDLE_VLLM.vllm_ocr_engine.value == "paddleocr-vl-1.6"
    assert ExtractionEngine.GLM_VLLM.vllm_ocr_engine.value == "glm-ocr"
    assert ExtractionEngine.OLLAMA.vllm_ocr_engine is None


def test_engine_switch_rolls_back_previous_vllm(monkeypatch) -> None:
    calls = []

    def ensure(engine):
        calls.append(engine.value)
        if engine.value == "glm-ocr":
            raise RuntimeError("warmup failed")

    monkeypatch.setattr(ocr_services, "ensure_managed_ocr_engine", ensure)
    with pytest.raises(RuntimeError, match="warmup failed"):
        ocr_services.switch_extraction_engine(
            ExtractionEngine.GLM_VLLM, ExtractionEngine.PADDLE_VLLM
        )
    assert calls == ["glm-ocr", "paddleocr-vl-1.6"]


def test_ollama_prompts_are_model_and_region_specific() -> None:
    assert region_prompt(OllamaOcrModel.PADDLEOCR_VL, "table") == "OCR:"
    assert region_prompt(OllamaOcrModel.GLM_OCR, "formula") == "Formula Recognition:"
    assert region_prompt(OllamaOcrModel.DEEPSEEK_OCR, "figure") == "Parse the figure."
