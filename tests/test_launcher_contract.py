from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_launcher_reads_openai_values_from_user_environment() -> None:
    for name in ("Setup-GLM-OCR.cmd", "Launch-GLM-OCR.cmd"):
        launcher = (ROOT / name).read_text(encoding="utf-8")

        assert "GetEnvironmentVariable('OPENAI_API_KEY','User')" in launcher
        assert "GetEnvironmentVariable('OPENAI_BASE_URL','User')" in launcher
        assert "OPENAI_API_KEY:OPENAI_BASE_URL" in launcher


def test_wsl_launcher_restarts_streamlit_on_luna_environment_drift() -> None:
    launcher = (ROOT / "scripts/wsl/launch-stack.sh").read_text(encoding="utf-8")

    assert "streamlit_environment_matches" in launcher
    assert 'OPENAI_API_KEY' in launcher
    assert 'OPENAI_BASE_URL' in launcher


def test_wsl_services_bind_to_loopback() -> None:
    run_app = (ROOT / "scripts/wsl/run-app.sh").read_text(encoding="utf-8")
    serve_glmocr = (ROOT / "scripts/wsl/serve-glmocr.sh").read_text(encoding="utf-8")

    assert '"$@" --server.address=127.0.0.1' in run_app
    assert "--host 127.0.0.1" in serve_glmocr
