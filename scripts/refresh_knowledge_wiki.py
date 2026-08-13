from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import NamedTuple

CATEGORY_ORDER = (
    "application-code",
    "documentation",
    "tests-and-benchmarks",
    "runtime-and-operations",
    "contracts-and-configuration",
)
INFRASTRUCTURE_FILES = {"index.md", "log.md", "agents.md"}
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
EXCLUDED_PARTS = {
    ".git",
    ".worktrees",
    ".venv",
    ".venv-wsl",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".docparse",
    ".ua",
    ".codegraph",
    ".code-review-graph",
    ".playwright-cli",
    ".remember",
    ".superpowers",
    ".claude",
    ".codex",
    "data",
    "dist",
    "docs-site",
    "graphify-out",
    "output",
    "tmp",
    "wiki",
}


class Snapshot(NamedTuple):
    base_commit: str
    branch: str
    dirty: bool
    snapshot_id: str
    files: dict[str, dict[str, object]]
    categories: dict[str, list[dict[str, object]]]


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def excluded(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    return normalized == ".env" or any(part in EXCLUDED_PARTS for part in parts)


def classify_path(path: str) -> str:
    posix = PurePosixPath(path)
    parts = posix.parts
    name = posix.name.casefold()
    suffix = posix.suffix.casefold()
    if parts[0] in {"src", "app_pages", "components"} or name == "streamlit_app.py":
        return "application-code"
    if (
        parts[0] == "docs"
        or parts[0] == "presentations"
        or suffix
        in {
            ".md",
            ".rst",
            ".txt",
        }
    ):
        return "documentation"
    if parts[0] in {"tests", "benchmarks"}:
        return "tests-and-benchmarks"
    if parts[0] in {"scripts", "installer", "paddle-runtime"} or name.startswith(
        ("launch-", "setup-")
    ):
        return "runtime-and-operations"
    return "contracts-and-configuration"


def _dirty_paths(repo_root: Path) -> set[str]:
    paths: set[str] = set()
    for line in _git(
        repo_root, "status", "--porcelain=v1", "--untracked-files=all"
    ).splitlines():
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", maxsplit=1)[1]
        normalized = raw.strip('"').replace("\\", "/")
        if normalized and not excluded(normalized):
            paths.add(normalized)
    return paths


def build_snapshot(repo_root: Path) -> Snapshot:
    repo_root = repo_root.resolve()
    categories: dict[str, list[dict[str, object]]] = {
        category: [] for category in CATEGORY_ORDER
    }
    files: dict[str, dict[str, object]] = {}
    listed = _git(repo_root, "ls-files", "--cached", "--others", "--exclude-standard")
    for relative in sorted(set(listed.splitlines())):
        relative = relative.replace("\\", "/")
        path = repo_root / relative
        if not relative or excluded(relative) or not path.is_file():
            continue
        data = path.read_bytes()
        record: dict[str, object] = {
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        files[relative] = record
        categories[classify_path(relative)].append(record)

    digest = hashlib.sha256()
    for relative, record in files.items():
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    base_commit = _git(repo_root, "rev-parse", "HEAD")
    branch = _git(repo_root, "branch", "--show-current") or "detached"
    dirty = bool(_dirty_paths(repo_root))
    snapshot_id = f"content-{digest.hexdigest()[:12]}"
    return Snapshot(base_commit, branch, dirty, snapshot_id, files, categories)


def _snapshot_metadata(snapshot: Snapshot) -> dict[str, object]:
    return {
        "id": snapshot.snapshot_id,
        "base_commit": snapshot.base_commit,
        "branch": snapshot.branch,
        "dirty": snapshot.dirty,
    }


def write_manifests(wiki_root: Path, snapshot: Snapshot) -> None:
    raw = wiki_root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    metadata = _snapshot_metadata(snapshot)
    summary = {
        "schema_version": 1,
        "snapshot": metadata,
        "generated_at": generated_at,
        "categories": {
            category: len(snapshot.categories[category]) for category in CATEGORY_ORDER
        },
        "total_files": len(snapshot.files),
    }
    (raw / "snapshot.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    for category in CATEGORY_ORDER:
        manifest = {
            "schema_version": 1,
            "snapshot": metadata,
            "generated_at": generated_at,
            "category": category,
            "files": snapshot.categories[category],
        }
        (raw / f"{category}.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )


def manifests_match(wiki_root: Path, snapshot: Snapshot) -> bool:
    raw = wiki_root / "raw"
    try:
        summary = json.loads((raw / "snapshot.json").read_text(encoding="utf-8"))
        if summary.get("snapshot", {}).get("id") != snapshot.snapshot_id:
            return False
        if summary.get("total_files") != len(snapshot.files):
            return False
        for category in CATEGORY_ORDER:
            manifest = json.loads(
                (raw / f"{category}.json").read_text(encoding="utf-8")
            )
            if manifest.get("snapshot", {}).get("id") != snapshot.snapshot_id:
                return False
            if manifest.get("category") != category:
                return False
            if manifest.get("files") != snapshot.categories[category]:
                return False
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return True


def article_paths(wiki_root: Path) -> list[Path]:
    article_root = wiki_root / "articles"
    return sorted(article_root.rglob("*.md")) if article_root.is_dir() else []


def write_article_snapshots(wiki_root: Path, snapshot: Snapshot) -> None:
    pattern = re.compile(r"^snapshot:\s*.*$", re.MULTILINE)
    for article in article_paths(wiki_root):
        text = article.read_text(encoding="utf-8")
        updated, count = pattern.subn(
            f"snapshot: {snapshot.snapshot_id}", text, count=1
        )
        if count and updated != text:
            article.write_text(updated, encoding="utf-8")


def index_categories(index_path: Path) -> list[str]:
    if not index_path.is_file():
        return []
    return [
        match.group(1).strip()
        for match in re.finditer(
            r"^##\s+(.+?)\s*$", index_path.read_text(encoding="utf-8"), re.MULTILINE
        )
    ]


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        values[key.strip()] = value.strip()
    return values


def _resolve_target(target: str, names: dict[str, Path]) -> Path | None:
    normalized = target.strip().replace("\\", "/").removesuffix(".md").casefold()
    return names.get(normalized) or names.get(PurePosixPath(normalized).name)


def validate_wiki(repo_root: Path, wiki_root: Path, snapshot: Snapshot) -> list[str]:
    del repo_root  # Kept in the interface for callers and future repository checks.
    errors: list[str] = []
    for name in ("index.md", "log.md", "AGENTS.md"):
        if not (wiki_root / name).is_file():
            errors.append(f"missing wiki infrastructure file: {name}")

    articles = article_paths(wiki_root)
    names: dict[str, Path] = {}
    for article in articles:
        relative_stem = (
            article.relative_to(wiki_root / "articles").with_suffix("").as_posix()
        )
        keys = {article.stem.casefold(), relative_stem.casefold()}
        for key in keys:
            if key in names and names[key] != article:
                errors.append(f"duplicate article name: {key}")
            names[key] = article

    index = wiki_root / "index.md"
    index_text = index.read_text(encoding="utf-8") if index.is_file() else ""
    indexed: dict[Path, int] = {article: 0 for article in articles}
    for target in WIKILINK_RE.findall(index_text):
        resolved = _resolve_target(target, names)
        if resolved is None:
            errors.append(f"unresolved index wikilink: [[{target}]]")
        else:
            indexed[resolved] += 1
    for article, count in indexed.items():
        if count != 1:
            errors.append(
                f"article must appear in index exactly once: {article.relative_to(wiki_root)} ({count})"
            )

    for article in articles:
        text = article.read_text(encoding="utf-8")
        relative = article.relative_to(wiki_root).as_posix()
        metadata = _frontmatter(text)
        if not metadata.get("tags"):
            errors.append(f"missing tags frontmatter: {relative}")
        if not metadata.get("sources"):
            errors.append(f"missing sources frontmatter: {relative}")
        if metadata.get("snapshot") != snapshot.snapshot_id:
            errors.append(
                f"stale snapshot in {relative}: {metadata.get('snapshot', '<missing>')}"
            )
        for source in filter(
            None, (item.strip() for item in metadata.get("sources", "").split(","))
        ):
            if source not in snapshot.files:
                errors.append(f"unknown source '{source}' in {relative}")
        if not re.search(r"^#\s+\S", text, re.MULTILINE):
            errors.append(f"missing article title: {relative}")
        for target in WIKILINK_RE.findall(text):
            if _resolve_target(target, names) is None:
                errors.append(f"unresolved wikilink [[{target}]] in {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh and validate the Karpathy wiki"
    )
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--wiki-root", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    wiki_root = (args.wiki_root or repo_root / "wiki").resolve()
    snapshot = build_snapshot(repo_root)
    if args.write:
        write_manifests(wiki_root, snapshot)
        write_article_snapshots(wiki_root, snapshot)
    errors = validate_wiki(repo_root, wiki_root, snapshot)
    if not manifests_match(wiki_root, snapshot):
        errors.append("raw manifests do not match the current repository snapshot")
    payload = {
        "snapshot": snapshot.snapshot_id,
        "files": len(snapshot.files),
        "articles": len(article_paths(wiki_root)),
        "categories": index_categories(wiki_root / "index.md"),
        "status": "ok" if not errors else "invalid",
        "errors": errors,
    }
    print(json.dumps(payload, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
