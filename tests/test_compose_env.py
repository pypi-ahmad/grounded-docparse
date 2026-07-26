from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from grounded_docparse.compose_env import (
    rotate_secrets,
    set_api_port,
    validate_environment,
)

VALID_ENV = {
    "OPENAI_API_KEY": "provider-key",
    "OPENAI_BASE_URL": "https://api.example.test/v1",
    "DOCPARSE_API_TOKEN": "a" * 32,
    "POSTGRES_PASSWORD": "b" * 32,
    "MINIO_ROOT_USER": "docparse",
    "MINIO_ROOT_PASSWORD": "c" * 32,
}


def test_validation_rejects_short_minio_password_without_exposing_it() -> None:
    environment = {**os.environ, **VALID_ENV, "MINIO_ROOT_PASSWORD": "tiny"}

    errors = validate_environment(environment)

    assert errors == [
        "MINIO_ROOT_PASSWORD must contain at least 32 URL-safe characters"
    ]
    assert "tiny" not in "\n".join(errors)


def test_validation_rejects_placeholders_and_invalid_openai_url() -> None:
    environment = {
        **VALID_ENV,
        "DOCPARSE_API_TOKEN": "replace-with-a-long-random-token",
        "OPENAI_BASE_URL": "example.test/v1",
    }

    assert validate_environment(environment) == [
        "OPENAI_BASE_URL must be an absolute HTTP(S) URL",
        "DOCPARSE_API_TOKEN must not use the example placeholder",
    ]


def test_rotation_replaces_local_secrets_and_preserves_other_settings(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=leave-unchanged\n"
        "DOCPARSE_API_TOKEN=replace-with-a-long-random-token\n"
        "POSTGRES_PASSWORD=tiny\n"
        "MINIO_ROOT_USER=docparse\n"
        "MINIO_ROOT_PASSWORD=tiny\n",
        encoding="utf-8",
    )

    changed = rotate_secrets(env_file)
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
    )

    assert changed == {
        "DOCPARSE_API_TOKEN",
        "POSTGRES_PASSWORD",
        "MINIO_ROOT_PASSWORD",
    }
    assert values["OPENAI_API_KEY"] == "leave-unchanged"
    assert values["MINIO_ROOT_USER"] == "docparse"
    for name in changed:
        assert len(values[name]) >= 32
        assert values[name].replace("-", "").replace("_", "").isalnum()


def test_check_command_fails_without_printing_secret_value() -> None:
    environment = {**os.environ, **VALID_ENV, "MINIO_ROOT_PASSWORD": "tiny"}

    result = subprocess.run(
        [sys.executable, "-m", "grounded_docparse.compose_env", "check"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "MINIO_ROOT_PASSWORD must contain at least 32" in result.stdout
    assert "tiny" not in result.stdout


def test_set_api_port_preserves_secret_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DOCPARSE_API_TOKEN=keep-this-secret\nDOCPARSE_API_PORT=8000\n",
        encoding="utf-8",
    )

    set_api_port(env_file, 8001)

    assert env_file.read_text(encoding="utf-8") == (
        "DOCPARSE_API_TOKEN=keep-this-secret\nDOCPARSE_API_PORT=8001\n"
    )


def test_port_command_updates_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MINIO_ROOT_USER=docparse\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "grounded_docparse.compose_env",
            "port",
            str(env_file),
            "8001",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert env_file.read_text(encoding="utf-8").endswith("DOCPARSE_API_PORT=8001\n")
