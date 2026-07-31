from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_launcher_reads_openai_values_from_user_environment() -> None:
    launcher = (ROOT / "Launch-GLM-OCR.cmd").read_text(encoding="utf-8")
    installer = (
        ROOT / "installer" / "Install-GroundedDocParse.ps1"
    ).read_text(encoding="utf-8")

    assert "GetEnvironmentVariable('OPENAI_API_KEY','User')" in launcher
    assert "GetEnvironmentVariable('OPENAI_BASE_URL','User')" in launcher
    assert "OPENAI_API_KEY:OPENAI_BASE_URL" in launcher
    assert "GetEnvironmentVariable('OPENAI_API_KEY', 'User')" in installer
    assert "GetEnvironmentVariable('OPENAI_BASE_URL', 'User')" in installer


def test_wsl_launcher_restarts_streamlit_on_luna_environment_drift() -> None:
    launcher = (ROOT / "scripts/wsl/launch-stack.sh").read_text(encoding="utf-8")

    assert "streamlit_environment_matches" in launcher
    assert 'OPENAI_API_KEY' in launcher
    assert 'OPENAI_BASE_URL' in launcher


def test_wsl_services_bind_to_loopback() -> None:
    run_app = (ROOT / "scripts/wsl/run-app.sh").read_text(encoding="utf-8")
    serve_glmocr = (ROOT / "scripts/wsl/serve-glmocr.sh").read_text(encoding="utf-8")
    serve_ollama = (ROOT / "scripts/wsl/serve-ollama.sh").read_text(encoding="utf-8")

    assert '"$@" --server.address=127.0.0.1' in run_app
    assert "--host 127.0.0.1" in serve_glmocr
    assert 'OLLAMA_HOST="127.0.0.1:11434"' in serve_ollama


def test_installer_reuses_dependencies_and_has_cpu_fallback() -> None:
    setup = (ROOT / "scripts/wsl/setup-glmocr.sh").read_text(encoding="utf-8")
    installer = (
        ROOT / "installer" / "Install-GroundedDocParse.ps1"
    ).read_text(encoding="utf-8")

    assert ".docparse-lock-$BACKEND" in setup
    assert "local-ocr-cpu" in setup
    assert "NVIDIA runtime validation failed; switching to Ollama CPU fallback" in installer
    assert "DOCPARSE_AMD_GPU" in installer
