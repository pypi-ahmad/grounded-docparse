from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TRUE_VALUES = frozenset({"1", "true", "yes"})


def managed_shutdown_available() -> bool:
    return os.getenv("DOCPARSE_MANAGE_OCR_SERVICES", "false").casefold() in _TRUE_VALUES


def schedule_managed_shutdown() -> int:
    if not managed_shutdown_available():
        raise RuntimeError("Shutdown is available only when using a managed launcher")
    script = PROJECT_ROOT / "scripts" / "wsl" / "stop-stack.sh"
    if not script.is_file():
        raise RuntimeError("Managed shutdown helper is missing")
    runtime_dir = PROJECT_ROOT / ".runtime"
    runtime_dir.mkdir(exist_ok=True)
    with (runtime_dir / "stop-stack.log").open("ab") as log:
        process = subprocess.Popen(
            ["bash", str(script), "2"],
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=True,
            close_fds=True,
        )
    return process.pid
