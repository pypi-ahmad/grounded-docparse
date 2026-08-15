from __future__ import annotations

import os
import subprocess

_TRUE_VALUES = frozenset({"1", "true", "yes"})


def managed_shutdown_available() -> bool:
    return os.name == "nt" and (
        os.getenv("DOCPARSE_MANAGE_OCR_SERVICES", "false").casefold()
        in _TRUE_VALUES
    )


def schedule_managed_shutdown() -> int:
    if not managed_shutdown_available():
        raise RuntimeError(
            "Shutdown is available only when using the managed Windows launcher"
        )
    command = (
        "Start-Sleep -Seconds 2; "
        f"Stop-Process -Id {os.getpid()} -ErrorAction SilentlyContinue"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    process = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", command],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=creation_flags,
    )
    return process.pid
