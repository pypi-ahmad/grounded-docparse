"""Windows-only self-termination for the "Stop app" UI action.

Responsibility: let the running Streamlit process schedule its own delayed
kill so the managed native launcher can restart cleanly. Must not run (or
claim to be available) outside the managed Windows launcher, since nothing
else is watching this process's PID to relaunch it. Next file: see
scripts/windows/launch-native.ps1 for the launcher side of this contract.
"""

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
    # Self-kill is delegated to a detached PowerShell process rather than
    # exiting inline: the 2-second delay gives this process time to finish
    # sending its HTTP response to the UI before `Stop-Process` ends it.
    # `os.getpid()` is this process's own PID (not attacker-controlled input),
    # and shell=False with an argv list avoids any shell-parsing of it.
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
