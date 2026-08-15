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


def test_provisioner_handles_reboot_credentials_and_gpu_or_windows_ollama() -> None:
    provisioner = (
        ROOT / "installer" / "Install-GroundedDocParse.ps1"
    ).read_text(encoding="utf-8")

    assert "RunOnce" in provisioner
    assert "RedirectStandardInput" in provisioner
    assert "chpasswd" in provisioner
    assert "Windows 11 22H2 or newer" in provisioner
    assert "At least 16 GB RAM" in provisioner
    assert "At least 20 GB free disk" in provisioner
    assert "Windows Ollama/local CPU profile" in provisioner
    assert "AMD|Radeon" in provisioner


def test_host_setup_installs_windows_ollama_and_preserves_loopback() -> None:
    provisioner = (ROOT / "installer" / "Install-GroundedDocParse.ps1").read_text(
        encoding="utf-8"
    )
    assert "irm https://ollama.com/install.ps1 | iex" in provisioner
    assert "networkingMode=mirrored" in provisioner
    assert "http://127.0.0.1:11434/api/tags" in provisioner
    assert "wsl.exe --shutdown" in provisioner


def test_wsl_private_ollama_runtime_is_removed() -> None:
    assert not (ROOT / "scripts" / "wsl" / "setup-ollama.sh").exists()
    assert not (ROOT / "scripts" / "wsl" / "serve-ollama.sh").exists()
