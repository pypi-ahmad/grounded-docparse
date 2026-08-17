from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_knowledge_wiki.py"


def load_refresh_module():
    spec = importlib.util.spec_from_file_location("refresh_knowledge_wiki", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def init_repository(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "wiki-test@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Wiki Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)


def test_snapshot_is_deterministic_and_excludes_generated_or_secret_files(
    tmp_path: Path,
) -> None:
    module = load_refresh_module()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=never-index\n", encoding="utf-8")
    init_repository(tmp_path)
    (tmp_path / ".ua").mkdir()
    (tmp_path / ".ua" / "graph.json").write_text("{}\n", encoding="utf-8")

    first = module.build_snapshot(tmp_path)
    wiki = tmp_path / "wiki"
    module.write_manifests(wiki, first)
    subprocess.run(["git", "add", "wiki"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "wiki"], cwd=tmp_path, check=True)
    second = module.build_snapshot(tmp_path)

    assert first.snapshot_id == second.snapshot_id
    assert first.base_commit != second.base_commit
    assert module.manifests_match(wiki, second)
    assert set(first.files) == {".gitignore", "docs/guide.md", "src/app.py"}
    assert first.categories["application-code"][0]["path"] == "src/app.py"
    assert first.categories["documentation"][0]["path"] == "docs/guide.md"


def test_validation_reports_stale_snapshot_and_unresolved_wikilink(
    tmp_path: Path,
) -> None:
    module = load_refresh_module()
    wiki = tmp_path / "wiki"
    article_dir = wiki / "articles" / "product"
    article_dir.mkdir(parents=True)
    (wiki / "index.md").write_text(
        "# Index\n\n## Product\n\n- [[overview]]\n", encoding="utf-8"
    )
    (wiki / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
    (article_dir / "overview.md").write_text(
        "---\n"
        "tags: product\n"
        "sources: src/app.py\n"
        "snapshot: stale\n"
        "---\n\n"
        "# Overview\n\n"
        "A useful summary with [[missing-article]].\n",
        encoding="utf-8",
    )
    snapshot = module.Snapshot(
        base_commit="abc123",
        branch="feature",
        dirty=False,
        snapshot_id="abc123-clean-deadbeef",
        files={"src/app.py": {"path": "src/app.py", "sha256": "1", "size": 1}},
        categories={name: [] for name in module.CATEGORY_ORDER},
    )

    errors = module.validate_wiki(tmp_path, wiki, snapshot)

    assert any("stale snapshot" in error for error in errors)
    assert any("unresolved wikilink" in error for error in errors)
    module.write_article_snapshots(wiki, snapshot)
    errors = module.validate_wiki(tmp_path, wiki, snapshot)
    assert not any("stale snapshot" in error for error in errors)


@pytest.mark.xfail(
    reason="MODERNIZATION_PLAN.md Phase 1: 24 stale wiki-article snapshots need "
    "regenerating (H8 living-doc drift, tracked as a fast-follow in the plan's §9).",
    strict=False,
)
def test_repository_wiki_contract() -> None:
    module = load_refresh_module()
    wiki = ROOT / "wiki"
    snapshot = module.build_snapshot(ROOT)

    assert len(module.article_paths(wiki)) == 24
    assert module.index_categories(wiki / "index.md") == [
        "Product and Principles",
        "Processing Pipelines",
        "Grounding and Extraction",
        "Interfaces and Operations",
        "Engineering and Assurance",
    ]
    assert module.validate_wiki(ROOT, wiki, snapshot) == []
    assert module.manifests_match(wiki, snapshot)
