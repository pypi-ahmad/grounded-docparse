from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = PROJECT_ROOT / "scripts" / "wsl" / "prepare_paddleocr_runtime.py"

_SPEC = importlib.util.spec_from_file_location("prepare_paddleocr_runtime", PREPARE_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_PREPARE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PREPARE)


def _config(layout_model: str = "PP-DocLayoutV3") -> dict:
    return {
        "pipeline_name": "PaddleOCR-VL-1.6",
        "SubModules": {
            "LayoutDetection": {"model_name": layout_model},
            "VLRecognition": {
                "model_name": "PaddleOCR-VL-1.6-0.9B",
                "genai_config": {},
            },
        },
    }


def test_configure_pipeline_preserves_full_v1_6_layout_and_uses_vllm(
    tmp_path: Path,
) -> None:
    configured = _PREPARE.configure_pipeline(_config(), "8128", tmp_path)

    layout = configured["SubModules"]["LayoutDetection"]
    assert layout["model_name"] == "PP-DocLayoutV3"
    assert layout["model_dir"] == str(
        tmp_path / "official_models" / "PP-DocLayoutV3"
    )
    recognition = configured["SubModules"]["VLRecognition"]
    assert recognition["model_name"] == "PaddleOCR-VL-1.6-0.9B"
    assert recognition["model_dir"] == str(
        tmp_path / "official_models" / "PaddleOCR-VL-1.6"
    )
    assert recognition["genai_config"] == {
        "backend": "vllm-server",
        "server_url": "http://127.0.0.1:8128/v1",
    }


def test_configure_pipeline_rejects_non_v1_6_layout() -> None:
    with pytest.raises(RuntimeError, match="PP-DocLayoutV3"):
        _PREPARE.configure_pipeline(_config("PP-DocLayoutV2"), "8118")


def test_validate_cached_assets_requires_all_runtime_downloads(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="PaddleOCR cache is incomplete"):
        _PREPARE.validate_cached_assets(tmp_path)

    for relative_path in _PREPARE.REQUIRED_ASSET_FILES:
        asset = tmp_path / relative_path
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"cached")

    assets = _PREPARE.validate_cached_assets(tmp_path)

    assert assets["vlm_dir"] == tmp_path / "official_models" / "PaddleOCR-VL-1.6"
    assert assets["layout_dir"] == tmp_path / "official_models" / "PP-DocLayoutV3"
    assert assets["font_file"] == tmp_path / "fonts" / "PingFang-SC-Regular.ttf"


def test_main_defaults_an_empty_forwarded_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.yaml"
    target = tmp_path / "target.yaml"
    source.write_text(_PREPARE.yaml.safe_dump(_config()), encoding="utf-8")
    monkeypatch.setenv("DOCPARSE_PADDLE_VLLM_PORT", "")
    monkeypatch.setattr(_PREPARE.sys, "argv", ["prepare", str(source), str(target)])

    _PREPARE.main()

    configured = _PREPARE.yaml.safe_load(target.read_text(encoding="utf-8"))
    recognition = configured["SubModules"]["VLRecognition"]
    assert recognition["genai_config"]["server_url"] == "http://127.0.0.1:8118/v1"
