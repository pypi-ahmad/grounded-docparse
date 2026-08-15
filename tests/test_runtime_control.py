from __future__ import annotations

import subprocess

import pytest

from grounded_docparse import runtime_control


def test_managed_shutdown_is_unavailable_outside_launcher(monkeypatch) -> None:
    monkeypatch.delenv("DOCPARSE_MANAGE_OCR_SERVICES", raising=False)

    assert runtime_control.managed_shutdown_available() is False
    with pytest.raises(RuntimeError, match="managed Windows launcher"):
        runtime_control.schedule_managed_shutdown()


def test_managed_shutdown_is_unavailable_outside_windows(monkeypatch) -> None:
    monkeypatch.setenv("DOCPARSE_MANAGE_OCR_SERVICES", "true")
    monkeypatch.setattr(runtime_control.os, "name", "posix")

    assert runtime_control.managed_shutdown_available() is False
    with pytest.raises(RuntimeError, match="managed Windows launcher"):
        runtime_control.schedule_managed_shutdown()


def test_managed_shutdown_starts_windows_detached_helper(monkeypatch) -> None:
    calls = []

    class FakeProcess:
        pid = 123

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setenv("DOCPARSE_MANAGE_OCR_SERVICES", "true")
    monkeypatch.setattr(runtime_control.subprocess, "Popen", fake_popen)

    assert runtime_control.schedule_managed_shutdown() == 123

    command, kwargs = calls[0]
    assert command[:3] == ["powershell.exe", "-NoProfile", "-Command"]
    assert "Stop-Process" in command[3]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["shell"] is False
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["creationflags"]
