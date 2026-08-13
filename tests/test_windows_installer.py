from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cpu_and_gpu_extras_use_conflicting_pytorch_indexes() -> None:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional = manifest["project"]["optional-dependencies"]
    sources = manifest["tool"]["uv"]["sources"]

    assert any(requirement.startswith("vllm==") for requirement in optional["local-ocr"])
    assert not any(
        requirement.startswith("vllm==")
        for requirement in optional["local-ocr-cpu"]
    )
    assert {source["extra"] for source in sources["torch"]} == {
        "local-ocr",
        "local-ocr-cpu",
    }
    assert manifest["tool"]["uv"]["conflicts"] == [
        [{"extra": "local-ocr"}, {"extra": "local-ocr-cpu"}]
    ]


def test_installer_payload_is_allowlisted_and_excludes_secrets() -> None:
    installer = (ROOT / "installer" / "GroundedDocParse.iss").read_text(
        encoding="utf-8"
    )

    assert 'Source: "..\\streamlit_app.py"' in installer
    assert 'Source: "..\\src\\*"' in installer
    assert "node_modules" not in installer
    assert "components\\*" not in installer
    assert "__pycache__\\*" in installer
    assert ".env" not in installer
    assert ".git" not in installer
    assert "secrets.toml" not in installer


def test_provisioner_handles_reboot_credentials_and_hardware_fallback() -> None:
    provisioner = (
        ROOT / "installer" / "Install-GroundedDocParse.ps1"
    ).read_text(encoding="utf-8")

    assert "RunOnce" in provisioner
    assert "RedirectStandardInput" in provisioner
    assert "chpasswd" in provisioner
    assert "Windows 10 22H2 or Windows 11" in provisioner
    assert "At least 16 GB RAM" in provisioner
    assert "At least 20 GB free disk" in provisioner
    assert "NVIDIA runtime validation failed; switching to Ollama CPU fallback" in provisioner
    assert "AMD|Radeon" in provisioner


def test_ollama_downloads_are_versioned_and_verified() -> None:
    setup = (ROOT / "scripts" / "wsl" / "setup-ollama.sh").read_text(
        encoding="utf-8"
    )

    assert 'OLLAMA_VERSION="0.32.0"' in setup
    assert 'OLLAMA_MODEL="glm-ocr:bf16"' in setup
    assert "56362d7609dfa9e35aaebb7c9cab25605d8f0528ec3d5d585dc83d6642002bab" in setup
    assert "f0fad39e184daab11d172a855580abd7338b2f049afa462435fee15d76b4e437" in setup
    assert "sha256sum -c -" in setup
