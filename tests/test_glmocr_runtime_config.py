from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "glmocr.yaml"
PREPARE_SCRIPT = PROJECT_ROOT / "scripts" / "wsl" / "prepare_glmocr_runtime.py"

_SPEC = importlib.util.spec_from_file_location("prepare_glmocr_runtime", PREPARE_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_PREPARE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PREPARE)

EXPECTED_LABELS = {
    0: "abstract",
    1: "algorithm",
    2: "aside_text",
    3: "chart",
    4: "content",
    5: "display_formula",
    6: "doc_title",
    7: "figure_title",
    8: "footer",
    9: "footer_image",
    10: "footnote",
    11: "formula_number",
    12: "header",
    13: "header_image",
    14: "image",
    15: "inline_formula",
    16: "number",
    17: "paragraph_title",
    18: "reference",
    19: "reference_content",
    20: "seal",
    21: "table",
    22: "text",
    23: "vertical_text",
    24: "vision_footnote",
}

PRESERVED_BOILERPLATE = {
    "aside_text",
    "footer",
    "footer_image",
    "footnote",
    "header",
    "header_image",
    "number",
    "reference",
}


def pipeline_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))["pipeline"]


def test_glmocr_config_has_complete_official_task_contract() -> None:
    pipeline = pipeline_config()
    loader = pipeline["page_loader"]
    layout = pipeline["layout"]

    assert loader["task_prompt_mapping"] == {
        "text": "Text Recognition:",
        "table": "Table Recognition:",
        "formula": "Formula Recognition:",
    }
    assert layout["id2label"] == EXPECTED_LABELS
    assert layout["label_task_mapping"]["table"] == ["table"]
    assert layout["label_task_mapping"]["formula"] == [
        "display_formula",
        "inline_formula",
    ]
    assert layout["label_task_mapping"]["skip"] == ["chart", "image"]
    assert layout["label_task_mapping"]["abandon"] == []
    assert set(layout["layout_merge_bboxes_mode"]) == set(EXPECTED_LABELS)


def test_glmocr_config_preserves_document_boilerplate_as_text() -> None:
    pipeline = pipeline_config()
    layout_text = set(pipeline["layout"]["label_task_mapping"]["text"])
    formatter_text = set(
        pipeline["result_formatter"]["label_visualization_mapping"]["text"]
    )

    assert PRESERVED_BOILERPLATE <= layout_text
    assert PRESERVED_BOILERPLATE <= formatter_text


def test_glmocr_config_uses_supported_retry_and_image_limits() -> None:
    pipeline = pipeline_config()
    ocr_api = pipeline["ocr_api"]
    loader = pipeline["page_loader"]

    assert "retry_times" not in ocr_api
    assert ocr_api["retry_max_attempts"] == 2
    assert loader["max_tokens"] == 8192
    assert loader["max_pixels"] == 1_003_520
    assert pipeline["region_maxsize"] == 800


def test_runtime_config_uses_pinned_layout_path_and_worker_override() -> None:
    layout_path = Path("/cache/pp-doclayout-v3")
    config = _PREPARE._runtime_config(layout_path, max_workers=24)

    assert config["pipeline"]["layout"]["model_dir"] == str(layout_path)
    assert config["pipeline"]["max_workers"] == 24
    assert _PREPARE.GLMOCR_REVISION == "ca5d8b3e287e52589e37c28385d9655ee4372f9d"
    assert _PREPARE.LAYOUT_REVISION == "97d101e6db2642e162a1d05392d1b0231c91033e"
