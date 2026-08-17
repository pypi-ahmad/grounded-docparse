from __future__ import annotations

import json
import threading
from io import BytesIO

import pytest

from grounded_docparse import ocr_services, ollama_runtime
from grounded_docparse.config import (
    AlternateOcrEngine,
    ExtractionEngine,
    OcrEngine,
    ParserConfig,
    default_alternate_ocr_engine,
)
from grounded_docparse.models import Element
from grounded_docparse.ollama_runtime import (
    OllamaOcrModel,
    OllamaRegionRecognizer,
    recognize_region,
    region_prompt,
    warm_model,
)


def test_engine_catalog_has_one_vllm_mapping_per_gpu_engine() -> None:
    assert ExtractionEngine.PADDLE_VLLM.vllm_ocr_engine.value == "paddleocr-vl-1.6"
    assert ExtractionEngine.GLM_VLLM.vllm_ocr_engine.value == "glm-ocr"
    assert ExtractionEngine.OLLAMA.vllm_ocr_engine is None
    assert ExtractionEngine.OLLAMA.parser_ocr_engine.value == "ollama"
    assert ExtractionEngine.DOCLING_RAPIDOCR.vllm_ocr_engine is None
    assert ExtractionEngine.DOCLING_RAPIDOCR.parser_ocr_engine is OcrEngine.RAPIDOCR


def test_rapidocr_is_valid_element_provenance() -> None:
    element = Element(
        id="p1-r1",
        type="text",
        page=1,
        text="OCR text",
        reading_order=1,
        source="rapidocr",
    )

    assert element.source == "rapidocr"


def test_rapidocr_primary_uses_ollama_as_its_default_cross_check() -> None:
    assert AlternateOcrEngine.RAPIDOCR.matches_primary(
        OcrEngine.RAPIDOCR, "glm-ocr:latest"
    )
    assert (
        default_alternate_ocr_engine(
            OcrEngine.RAPIDOCR, "glm-ocr:latest"
        )
        is AlternateOcrEngine.OLLAMA_PADDLEOCR_VL_1_6
    )


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


@pytest.mark.parametrize(
    ("model", "source"),
    [
        (OllamaOcrModel.GLM_OCR, "glm-ocr"),
        (OllamaOcrModel.PADDLEOCR_VL, "paddleocr-vl-1.6"),
        (OllamaOcrModel.DEEPSEEK_OCR, "deepseek-ocr"),
    ],
)
def test_ollama_models_expose_element_provenance(model, source) -> None:
    assert model.element_source == source


def test_ollama_ocr_request_bounds_context_and_output(monkeypatch) -> None:
    captured = {}

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return BytesIO(b'{"message":{"content":"recognized"},"eval_count":4}')

    monkeypatch.setattr(ollama_runtime, "urlopen", opener)

    assert recognize_region(OllamaOcrModel.GLM_OCR, b"crop", "table") == "recognized"
    assert captured["timeout"] == 120
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["payload"] == {
        "model": "glm-ocr:latest",
        "messages": [
            {
                "role": "user",
                "content": "Table Recognition:",
                "images": ["Y3JvcA=="],
            }
        ],
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 512},
    }


def test_ollama_warmup_generates_only_one_token(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(ollama_runtime, "ensure_model", lambda _model: None)

    def opener(request, *, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return BytesIO(b'{"message":{"content":""}}')

    monkeypatch.setattr(ollama_runtime, "urlopen", opener)

    warm_model(OllamaOcrModel.PADDLEOCR_VL)

    assert captured["timeout"] == 120
    assert captured["payload"]["model"] == "AuditAid/PaddleOCR-VL-1.6-0.9B:latest"
    assert captured["payload"]["messages"][0]["images"]
    assert captured["payload"]["options"] == {
        "temperature": 0,
        "num_ctx": 4096,
        "num_predict": 1,
    }


def test_ollama_recognizer_uses_configured_timeout(monkeypatch) -> None:
    captured = {}

    def opener(request, *, timeout):
        captured["timeout"] = timeout
        return BytesIO(b'{"message":{"content":"recognized"}}')

    monkeypatch.setattr(ollama_runtime, "urlopen", opener)

    recognizer = OllamaRegionRecognizer(
        OllamaOcrModel.GLM_OCR,
        timeout_seconds=17,
    )

    assert recognizer.recognize(b"crop", "text") == "recognized"
    assert captured["timeout"] == 17


@pytest.mark.parametrize(
    ("region_area", "expected"),
    [(0.01, 128), (0.04, 256)],
)
def test_ollama_text_token_budget_scales_with_region_area(
    monkeypatch, region_area, expected
) -> None:
    captured = {}

    def opener(request, *, timeout):
        captured["payload"] = json.loads(request.data)
        return BytesIO(b'{"message":{"content":"recognized"}}')

    monkeypatch.setattr(ollama_runtime, "urlopen", opener)

    recognize_region(
        OllamaOcrModel.GLM_OCR,
        b"crop",
        "text",
        region_area=region_area,
    )

    assert captured["payload"]["options"]["num_predict"] == expected


def test_ollama_output_cleanup_removes_model_loops() -> None:
    repeated = "A long recognized sentence that should only appear once in output."
    value = f"<|md_start|>{repeated}\n{repeated}<|md_end|><|im_end|>"

    assert ollama_runtime.clean_ocr_output(value) == repeated


def test_ocr_operation_blocks_engine_switch_until_parse_finishes(monkeypatch) -> None:
    parse_started = threading.Event()
    finish_parse = threading.Event()
    switch_finished = threading.Event()
    calls = []

    monkeypatch.setattr(
        ocr_services,
        "stop_managed_vllm",
        lambda: calls.append("stop-vllm"),
    )

    def parse_document() -> None:
        with ocr_services.ocr_operation():
            parse_started.set()
            assert finish_parse.wait(timeout=2)

    def switch_engine() -> None:
        ocr_services.switch_extraction_engine(ExtractionEngine.DOCLING_RAPIDOCR)
        switch_finished.set()

    parse_thread = threading.Thread(target=parse_document)
    switch_thread = threading.Thread(target=switch_engine)
    parse_thread.start()
    assert parse_started.wait(timeout=2)
    switch_thread.start()

    assert not switch_finished.wait(timeout=0.05)
    assert calls == []

    finish_parse.set()
    parse_thread.join(timeout=2)
    switch_thread.join(timeout=2)

    assert switch_finished.is_set()
    assert calls == ["stop-vllm"]


def test_windows_manager_uses_wsl_without_forwarding_provider_keys(monkeypatch) -> None:
    monkeypatch.setattr(ocr_services.os, "name", "nt")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("WSLENV", "EXISTING/u")

    command, environment = ocr_services._manager_command("ensure", "glm-ocr")

    assert command[:3] == ["wsl.exe", "-d", "Ubuntu-24.04"]
    assert command[-1].endswith("manage-ocr-stack.sh ensure glm-ocr")
    assert "DOCPARSE_WINDOWS_ROOT/p" in environment["WSLENV"]
    assert "OPENAI_API_KEY" not in environment["WSLENV"]


def test_cross_check_swaps_vllm_and_restores_primary() -> None:
    calls = []

    with ocr_services.temporary_alternate_ocr_engine(
        ParserConfig(ocr_engine=OcrEngine.GLM_OCR),
        AlternateOcrEngine.VLLM_PADDLEOCR_VL_1_6,
        vllm_switcher=lambda engine: calls.append(engine.value),
    ):
        calls.append("parse")

    assert calls == ["paddleocr-vl-1.6", "parse", "glm-ocr"]


def test_cross_check_swaps_ollama_models_and_restores_primary(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        ocr_services,
        "unload_model",
        lambda model: calls.append(("unload", model.value)),
    )
    monkeypatch.setattr(
        ocr_services,
        "warm_model",
        lambda model: calls.append(("warm", model.value)),
    )

    with ocr_services.temporary_alternate_ocr_engine(
        ParserConfig(ocr_engine=OcrEngine.OLLAMA, ollama_model="glm-ocr:latest"),
        AlternateOcrEngine.OLLAMA_PADDLEOCR_VL_1_6,
    ):
        calls.append(("parse", "crop"))

    assert calls == [
        ("unload", "glm-ocr:latest"),
        ("warm", "AuditAid/PaddleOCR-VL-1.6-0.9B:latest"),
        ("parse", "crop"),
        ("unload", "AuditAid/PaddleOCR-VL-1.6-0.9B:latest"),
        ("warm", "glm-ocr:latest"),
    ]


def test_cross_check_restores_primary_after_alternate_failure(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        ocr_services,
        "stop_managed_vllm",
        lambda: calls.append("stop-vllm"),
    )
    monkeypatch.setattr(
        ocr_services,
        "warm_model",
        lambda model: calls.append(f"warm:{model.value}"),
    )
    monkeypatch.setattr(
        ocr_services,
        "unload_model",
        lambda model: calls.append(f"unload:{model.value}"),
    )

    with (
        pytest.raises(RuntimeError, match="alternate failed"),
        ocr_services.temporary_alternate_ocr_engine(
            ParserConfig(
                ocr_engine=OcrEngine.OLLAMA,
                ollama_model="deepseek-ocr:latest",
            ),
            AlternateOcrEngine.VLLM_GLM_OCR,
            vllm_switcher=lambda engine: calls.append(f"vllm:{engine.value}"),
        ),
    ):
        raise RuntimeError("alternate failed")

    assert calls == [
        "unload:deepseek-ocr:latest",
        "vllm:glm-ocr",
        "stop-vllm",
        "warm:deepseek-ocr:latest",
    ]


def test_rapidocr_primary_never_starts_wsl_and_stops_temporary_vllm(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        ocr_services,
        "stop_managed_vllm",
        lambda: calls.append("stop-vllm"),
    )

    ocr_services.ensure_managed_ocr_engine(OcrEngine.RAPIDOCR)
    with ocr_services.temporary_alternate_ocr_engine(
        ParserConfig(ocr_engine=OcrEngine.RAPIDOCR),
        AlternateOcrEngine.VLLM_GLM_OCR,
        vllm_switcher=lambda engine: calls.append(f"vllm:{engine.value}"),
    ):
        calls.append("parse")

    assert calls == ["vllm:glm-ocr", "parse", "stop-vllm"]
