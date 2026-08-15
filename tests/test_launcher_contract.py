from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_wsl_shell_scripts_use_unix_line_endings() -> None:
    for script in sorted((ROOT / "scripts" / "wsl").glob("*.sh")):
        content = script.read_bytes()

        assert content.startswith(b"#!/usr/bin/env bash\n"), script
        assert b"\r\n" not in content, script


def test_windows_launcher_reads_openai_values_from_user_environment() -> None:
    launcher = (ROOT / "Launch-Grounded-DocParse.cmd").read_text(encoding="utf-8")
    installer = (
        ROOT / "installer" / "Install-GroundedDocParse.ps1"
    ).read_text(encoding="utf-8")

    assert "for %%K in (OPENAI_API_KEY OPENAI_BASE_URL GOOGLE_API_KEY OLLAMA_BASE_URL)" in launcher
    assert "GetEnvironmentVariable('%%K','User')" in launcher
    assert "OPENAI_API_KEY:OPENAI_BASE_URL" in launcher
    assert "GOOGLE_API_KEY:OLLAMA_BASE_URL" in launcher
    assert "GetEnvironmentVariable('OPENAI_API_KEY', 'User')" in installer
    assert "GetEnvironmentVariable('OPENAI_BASE_URL', 'User')" in installer


def test_streamlit_uses_port_8600_everywhere_it_launches() -> None:
    launchers = [
        (ROOT / "Launch-Grounded-DocParse.cmd").read_text(encoding="utf-8"),
    ]
    stack = (ROOT / "scripts" / "wsl" / "launch-stack.sh").read_text(
        encoding="utf-8"
    )
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    installer = (
        ROOT / "installer" / "Install-GroundedDocParse.ps1"
    ).read_text(encoding="utf-8")

    assert all("http://localhost:8600" in launcher for launcher in launchers)
    assert "STREAMLIT_PORT=8600" in stack
    assert '--server.port "$STREAMLIT_PORT"' in stack
    assert "streamlit_uses_configured_port()" in stack
    assert "port = 8600" in config
    assert "http://localhost:8600" in installer


def test_wsl_launcher_restarts_streamlit_on_luna_environment_drift() -> None:
    launcher = (ROOT / "scripts/wsl/launch-stack.sh").read_text(encoding="utf-8")

    assert "streamlit_environment_matches" in launcher
    assert 'OPENAI_API_KEY' in launcher
    assert 'OPENAI_BASE_URL' in launcher


def test_wsl_launcher_restarts_streamlit_on_application_source_drift() -> None:
    launcher = (ROOT / "scripts/wsl/launch-stack.sh").read_text(encoding="utf-8")

    assert "streamlit_source_fingerprint" in launcher
    assert "DOCPARSE_SOURCE_FINGERPRINT" in launcher
    assert '"$PROJECT_ROOT/streamlit_app.py"' in launcher
    assert '"$PROJECT_ROOT/src/grounded_docparse"' in launcher
    assert '"$PROJECT_ROOT/uv.lock"' in launcher
    assert 'process_is_running "$pid"' in launcher


def test_managed_stack_has_a_safe_stop_all_command() -> None:
    manager = (ROOT / "scripts/wsl/manage-ocr-stack.sh").read_text(encoding="utf-8")
    stopper = (ROOT / "scripts/wsl/stop-stack.sh").read_text(encoding="utf-8")

    assert 'manage-ocr-stack.sh" stop all' in stopper
    assert '"streamlit run streamlit_app.py"' in stopper
    assert 'readlink -f "/proc/$pid/cwd"' in stopper
    assert '[[ "$action" == "stop"' in manager
    assert "stop_glm" in manager
    assert "stop_paddle" in manager


def test_wsl_services_bind_to_loopback() -> None:
    run_app = (ROOT / "scripts/wsl/run-app.sh").read_text(encoding="utf-8")
    serve_glmocr = (ROOT / "scripts/wsl/serve-glmocr.sh").read_text(encoding="utf-8")
    installer = (ROOT / "installer/Install-GroundedDocParse.ps1").read_text(encoding="utf-8")

    assert '"$@" --server.address=127.0.0.1' in run_app
    assert "--host 127.0.0.1" in serve_glmocr
    assert "http://127.0.0.1:11434/api/tags" in installer


def test_paddle_launcher_and_service_manager_use_official_full_pipeline() -> None:
    launcher = (ROOT / "Setup-PaddleOCR-VL-1.6.cmd").read_text(encoding="utf-8")
    manager = (ROOT / "scripts/wsl/manage-ocr-stack.sh").read_text(encoding="utf-8")
    runtime_config = (ROOT / "scripts/wsl/prepare_paddleocr_runtime.py").read_text(
        encoding="utf-8"
    )
    backend_config = (ROOT / "config/paddle-vllm.yaml").read_text(encoding="utf-8")

    assert "manage-ocr-stack.sh ensure paddleocr-vl-1.6" in launcher
    assert "PaddleOCR-VL-1.6-0.9B" in manager
    assert "paddleocr genai_server" in manager
    assert "--backend vllm" in manager
    assert 'PADDLE_VLLM_PORT="${DOCPARSE_PADDLE_VLLM_PORT:-8118}"' in manager
    assert 'PADDLE_API_PORT="${DOCPARSE_PADDLE_API_PORT:-8119}"' in manager
    assert '--port "$PADDLE_VLLM_PORT"' in manager
    assert '--backend_config "$PROJECT_ROOT/config/paddle-vllm.yaml"' in manager
    assert "gpu-memory-utilization: 0.70" in backend_config
    assert "no-enable-prefix-caching: true" in backend_config
    assert "paddlex --serve" in manager
    assert '--port "$PADDLE_API_PORT"' in manager
    assert "/layout-parsing" in manager
    assert "flock" in manager
    assert "DOCPARSE_PADDLE_VLLM_PORT" in runtime_config
    setup = (ROOT / "scripts/wsl/setup-paddleocr.sh").read_text(encoding="utf-8")
    assert "--get_pipeline_config PaddleOCR-VL-1.6" in setup


def test_paddle_runtime_downloads_once_then_uses_local_cache_offline() -> None:
    manager = (ROOT / "scripts/wsl/manage-ocr-stack.sh").read_text(encoding="utf-8")
    setup = (ROOT / "scripts/wsl/setup-paddleocr.sh").read_text(encoding="utf-8")
    paddle_runtime = manager.split("ensure_paddle()", maxsplit=1)[1]

    assert "--ensure-assets" in setup
    assert "--offline" in setup
    assert "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True" in paddle_runtime
    assert "HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1" in paddle_runtime
    assert '--model_dir "$PADDLE_MODEL_DIR"' in paddle_runtime
    assert "PADDLE_PDX_LOCAL_FONT_FILE_PATH" in paddle_runtime


def test_paddle_runtime_project_is_complete_and_packaged() -> None:
    project = ROOT / "paddle-runtime"
    setup = (ROOT / "scripts" / "wsl" / "setup-paddleocr.sh").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "installer" / "GroundedDocParse.iss").read_text(
        encoding="utf-8"
    )

    assert (project / "pyproject.toml").is_file()
    assert (project / "uv.lock").is_file()
    assert 'PADDLE_PROJECT="$PROJECT_ROOT/paddle-runtime"' in setup
    assert 'sha256sum "$PADDLE_PROJECT/uv.lock"' in setup
    assert '--project "$PADDLE_PROJECT" --locked' in setup
    assert "Setup-PaddleOCR-VL-1.6.cmd" in installer
    assert "paddle-runtime\\pyproject.toml" in installer
    assert "paddle-runtime\\uv.lock" in installer


def test_paddle_cuda_check_accepts_current_wsl_nvidia_smi_format() -> None:
    manager = (ROOT / "scripts/wsl/manage-ocr-stack.sh").read_text(encoding="utf-8")

    assert "CUDA (UMD )?Version:" in manager


def test_detached_services_do_not_inherit_launcher_locks() -> None:
    manager = (ROOT / "scripts/wsl/manage-ocr-stack.sh").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts/wsl/launch-stack.sh").read_text(encoding="utf-8")

    assert manager.count("9>&-") == 3
    assert (
        'run-app.sh --server.headless true --server.port "$STREAMLIT_PORT" 8>&-'
        in launcher
    )


def test_paddle_readiness_probe_generates_its_png() -> None:
    probe = (ROOT / "scripts/wsl/check-paddleocr-api.py").read_text(encoding="utf-8")

    assert "Image.new" in probe
    assert "base64.b64decode" not in probe


def test_primary_launcher_checks_setup_then_starts_streamlit() -> None:
    launcher = (ROOT / "Launch-Grounded-DocParse.cmd").read_text(encoding="utf-8")
    stack = (ROOT / "scripts/wsl/launch-stack.sh").read_text(encoding="utf-8")

    assert "check-installation.sh" in launcher
    assert "-WarmEngine paddleocr-vl-1.6" in launcher
    assert "launch-stack.sh" in launcher
    run_app = (ROOT / "scripts/wsl/run-app.sh").read_text(encoding="utf-8")
    assert run_app.index("export DOCPARSE_GLMOCR_CONFIG_PATH") < run_app.index(
        'if [[ "$DOCPARSE_OCR_ENGINE" == "glm-ocr" ]]'
    )


def test_launcher_set_is_consolidated_and_setup_commands_warm_requested_gpu() -> None:
    assert not (ROOT / "Launch-GLM-OCR.cmd").exists()
    assert not (ROOT / "Launch-PaddleOCR-VL-1.6.cmd").exists()
    assert not (ROOT / "Launch-Ollama.cmd").exists()
    assert (ROOT / "Launch-Grounded-DocParse.cmd").is_file()
    glm = (ROOT / "Setup-GLM-OCR.cmd").read_text(encoding="utf-8")
    paddle = (ROOT / "Setup-PaddleOCR-VL-1.6.cmd").read_text(encoding="utf-8")
    assert "manage-ocr-stack.sh ensure glm-ocr" in glm
    assert "manage-ocr-stack.sh ensure paddleocr-vl-1.6" in paddle


def test_launchers_repair_shared_environment_and_use_current_worktree() -> None:
    manager = (ROOT / "scripts" / "wsl" / "manage-ocr-stack.sh").read_text(
        encoding="utf-8"
    )
    run_app = (ROOT / "scripts" / "wsl" / "run-app.sh").read_text(
        encoding="utf-8"
    )

    assert "glm_environment_current()" in manager
    assert 'sha256sum "$PROJECT_ROOT/uv.lock"' in manager
    assert 'glm_environment_current "$backend"' in manager
    assert "glm_environment_current vllm" in manager
    assert 'export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"' in run_app


def test_installer_reuses_dependencies_and_has_windows_ollama_profile() -> None:
    setup = (ROOT / "scripts/wsl/setup-glmocr.sh").read_text(encoding="utf-8")
    installer = (
        ROOT / "installer" / "Install-GroundedDocParse.ps1"
    ).read_text(encoding="utf-8")

    assert ".docparse-lock-$BACKEND" in setup
    assert "local-ocr-cpu" in setup
    assert "--extra native" in setup
    assert "import docling" in setup
    assert "langextract" in setup
    assert "pdf_inspector" in setup
    assert "Windows Ollama/local CPU profile" in installer
    assert "DOCPARSE_AMD_GPU" in installer
