from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from grounded_docparse import runtime_control


def test_managed_shutdown_is_unavailable_outside_launcher(monkeypatch) -> None:
    monkeypatch.delenv("DOCPARSE_MANAGE_OCR_SERVICES", raising=False)

    assert runtime_control.managed_shutdown_available() is False
    with pytest.raises(RuntimeError, match="managed launcher"):
        runtime_control.schedule_managed_shutdown()


def test_managed_shutdown_starts_fixed_detached_helper(monkeypatch, tmp_path) -> None:
    script = tmp_path / "scripts" / "wsl" / "stop-stack.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    calls = []

    class FakeProcess:
        pid = 123

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setenv("DOCPARSE_MANAGE_OCR_SERVICES", "true")
    monkeypatch.setattr(runtime_control, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_control.subprocess, "Popen", fake_popen)

    assert runtime_control.schedule_managed_shutdown() == 123

    command, kwargs = calls[0]
    assert command == ["bash", str(script), "2"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.STDOUT
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    assert Path(kwargs["stdout"].name) == tmp_path / ".runtime" / "stop-stack.log"
