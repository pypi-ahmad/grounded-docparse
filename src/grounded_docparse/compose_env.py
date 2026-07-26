from __future__ import annotations

import argparse
import os
import re
import secrets
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

SECRET_NAMES = (
    "DOCPARSE_API_TOKEN",
    "POSTGRES_PASSWORD",
    "MINIO_ROOT_PASSWORD",
)
PLACEHOLDERS = {
    "DOCPARSE_API_TOKEN": "replace-with-a-long-random-token",
    "POSTGRES_PASSWORD": "replace-with-a-long-random-password",
    "MINIO_ROOT_PASSWORD": "replace-with-a-long-random-password",
}
URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_environment(environment: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    api_key = environment.get("OPENAI_API_KEY", "")
    base_url = environment.get("OPENAI_BASE_URL", "")
    if not api_key:
        errors.append("OPENAI_API_KEY is required")
    parsed_url = urlsplit(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        errors.append("OPENAI_BASE_URL must be an absolute HTTP(S) URL")

    for name in SECRET_NAMES:
        value = environment.get(name, "")
        if value == PLACEHOLDERS[name]:
            errors.append(f"{name} must not use the example placeholder")
        elif len(value) < 32 or URL_SAFE.fullmatch(value) is None:
            errors.append(f"{name} must contain at least 32 URL-safe characters")

    root_user = environment.get("MINIO_ROOT_USER", "")
    if len(root_user) < 3:
        errors.append("MINIO_ROOT_USER must contain at least 3 characters")
    return errors


def rotate_secrets(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    replacements = {name: secrets.token_urlsafe(32) for name in SECRET_NAMES}
    found: set[str] = set()
    updated: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            name = line.split("=", 1)[0].strip()
            if name in replacements:
                updated.append(f"{name}={replacements[name]}")
                found.add(name)
                continue
        updated.append(line)
    for name in SECRET_NAMES:
        if name not in found:
            updated.append(f"{name}={replacements[name]}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write("\n".join(updated) + "\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)
    return set(SECRET_NAMES)


def set_api_port(path: Path, port: int) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("API port must be between 1 and 65535")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    prefix = "DOCPARSE_API_PORT="
    updated = [
        f"{prefix}{port}" if line.startswith(prefix) else line for line in lines
    ]
    if not any(line.startswith(prefix) for line in lines):
        updated.append(f"{prefix}{port}")
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write("\n".join(updated) + "\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate or rotate Compose settings")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    rotate = subparsers.add_parser("rotate")
    rotate.add_argument("path", type=Path)
    port = subparsers.add_parser("port")
    port.add_argument("path", type=Path)
    port.add_argument("number", type=int)
    args = parser.parse_args()

    if args.command == "rotate":
        changed = rotate_secrets(args.path)
        print("Rotated local secrets: " + ", ".join(sorted(changed)))
        return 0
    if args.command == "port":
        set_api_port(args.path, args.number)
        print(f"Configured host API port: {args.number}")
        return 0

    errors = validate_environment(os.environ)
    if errors:
        for error in errors:
            print(f"Configuration error: {error}")
        return 1
    print("Compose environment validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
