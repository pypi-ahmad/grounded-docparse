"""Build the static, multipage documentation website.

Run from the repository root:
    uv run --with markdown python scripts/build_docs_site.py
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import markdown
except ImportError as exc:  # pragma: no cover - build-time guidance
    raise SystemExit(
        "Install the temporary build dependency with: "
        "uv run --with markdown python scripts/build_docs_site.py"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs-site"
ASSETS = OUTPUT / "assets"
REPOSITORY_URL = "https://github.com/pypi-ahmad/grounded-docparse"
SKIP_DIRECTORIES = {".git", ".venv", "docs-site", "graphify-out"}
SECURITY_FILE_MARKERS = ("security", "threat-model", "threat_model")

GROUP_ORDER = (
    (
        "Start here",
        (
            "README.md",
            "docs/complete-user-guide.md",
            "docs/tutorial.md",
            "docs/zero-to-hero-tutorial.md",
        ),
    ),
    (
        "Business workflows",
        (
            "docs/business-user-extraction-workflow.md",
            "docs/layout-aware-large-field-extraction-workflow.md",
            "docs/how-it-works.md",
        ),
    ),
    (
        "Setup & operations",
        (
            "SETUP.md",
            "docs/run.md",
            "docs/local-glmocr.md",
            "docs/azure-bulk-fax-deployment.md",
        ),
    ),
    (
        "Architecture & reference",
        (
            "docs/architecture.md",
            "docs/spec.md",
            "docs/api.md",
            "docs/research.md",
            "docs/extraction-quality-research.md",
        ),
    ),
    (
        "Project",
        (
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/feature_request.md",
        ),
    ),
)


@dataclass(frozen=True)
class Document:
    source: Path
    relative: str
    output_name: str
    title: str
    summary: str
    raw_body: str
    front_matter: str
    words: int
    headings: tuple[str, ...]


def is_security_document(path: Path) -> bool:
    name = path.name.casefold()
    return any(marker in name for marker in SECURITY_FILE_MARKERS)


def discover_markdown() -> tuple[list[Path], list[Path]]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    included: list[Path] = []
    excluded: list[Path] = []
    for relative in result.stdout.splitlines():
        path = ROOT / relative
        relative_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRECTORIES for part in relative_parts):
            continue
        (excluded if is_security_document(path) else included).append(path)
    return sorted(included), sorted(excluded)


def output_name(relative: str) -> str:
    if relative == "README.md":
        return "index.html"
    path = Path(relative)
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] == "docs":
        parts = parts[1:]
    if parts[:2] == [".github", "ISSUE_TEMPLATE"]:
        parts = ["issue-template", *parts[2:]]
    slug = "--".join(parts).casefold().replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
    return f"{slug}.html"


def split_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    marker = text.find("\n---\n", 4)
    if marker == -1:
        return "", text
    return text[4:marker].strip(), text[marker + 5 :].lstrip()


def normalize_indented_fences(text: str) -> str:
    """Make list-indented fenced blocks render consistently in Python-Markdown."""
    lines = text.splitlines()
    normalized: list[str] = []
    fence_indent: int | None = None
    fence_marker = ""
    for line in lines:
        match = re.match(r"^( {1,3})(`{3,}|~{3,})(.*)$", line)
        if fence_indent is None and match:
            fence_indent = len(match.group(1))
            fence_marker = match.group(2)[0]
            normalized.append(line[fence_indent:])
            continue
        if fence_indent is not None:
            candidate = line[fence_indent:] if line.startswith(" " * fence_indent) else line
            normalized.append(candidate)
            if re.match(rf"^{re.escape(fence_marker)}{{3,}}\s*$", candidate):
                fence_indent = None
                fence_marker = ""
            continue
        normalized.append(line)
    return "\n".join(normalized)


def extract_document(path: Path) -> Document:
    relative = path.relative_to(ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    front_matter, body = split_front_matter(text)
    title_match = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem.replace("-", " ").title()
    if title_match:
        body = body[: title_match.start()] + body[title_match.end() :]
        body = body.lstrip("\n")
    paragraphs = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"\n\s*\n", body)
        if part.strip()
        and not part.lstrip().startswith(("#", "```", "|", "- ", "* ", ">"))
    ]
    summary = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", paragraphs[0]) if paragraphs else ""
    summary = re.sub(r"[`*_]", "", summary)[:240]
    headings = tuple(
        re.sub(r"[`*_]", "", match.group(1)).strip()
        for match in re.finditer(r"^#{2,4}\s+(.+?)\s*$", body, flags=re.MULTILINE)
    )
    words = len(re.findall(r"\b[\w'-]+\b", text))
    return Document(
        source=path,
        relative=relative,
        output_name=output_name(relative),
        title=title,
        summary=summary,
        raw_body=body,
        front_matter=front_matter,
        words=words,
        headings=headings,
    )


def rewrite_links(rendered: str, document: Document, mapping: dict[str, Document], excluded: set[str]) -> str:
    def replace_href(match: re.Match[str]) -> str:
        quote, raw_target = match.group(1), html.unescape(match.group(2))
        parsed = urlsplit(raw_target)
        if parsed.scheme or raw_target.startswith(("#", "mailto:", "tel:")):
            return match.group(0)
        target_path = unquote(parsed.path)
        if not target_path:
            return match.group(0)
        resolved = (document.source.parent / target_path).resolve()
        try:
            relative = resolved.relative_to(ROOT).as_posix()
        except ValueError:
            return match.group(0)
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        if relative in mapping:
            target = f"{mapping[relative].output_name}{fragment}"
        elif relative in excluded:
            target = "security-content-excluded.html"
        elif resolved.exists():
            kind = "tree" if resolved.is_dir() else "blob"
            target = f"{REPOSITORY_URL}/{kind}/main/{relative}{fragment}"
        else:
            target = raw_target
        return f"href={quote}{html.escape(target, quote=True)}{quote}"

    return re.sub(r"href=([\"'])(.*?)\1", replace_href, rendered)


def copy_local_images(rendered: str, document: Document) -> str:
    def replace_src(match: re.Match[str]) -> str:
        quote, raw_target = match.group(1), html.unescape(match.group(2))
        parsed = urlsplit(raw_target)
        if parsed.scheme or parsed.netloc or raw_target.startswith("#"):
            return match.group(0)
        resolved = (document.source.parent / unquote(parsed.path)).resolve()
        try:
            relative = resolved.relative_to(ROOT)
        except ValueError:
            return match.group(0)
        if not resolved.is_file():
            return match.group(0)
        destination_relative = Path("assets") / "content" / relative
        destination = OUTPUT / destination_relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(resolved, destination)
        target = destination_relative.as_posix()
        return f"src={quote}{html.escape(target, quote=True)}{quote}"

    return re.sub(r"src=([\"'])(.*?)\1", replace_src, rendered)


def grouped_documents(documents: dict[str, Document]) -> list[tuple[str, list[Document]]]:
    grouped: list[tuple[str, list[Document]]] = []
    assigned: set[str] = set()
    for label, paths in GROUP_ORDER:
        items = [documents[path] for path in paths if path in documents]
        if items:
            grouped.append((label, items))
            assigned.update(item.relative for item in items)
    extras = [document for key, document in sorted(documents.items()) if key not in assigned]
    if extras:
        grouped.append(("More documents", extras))
    return grouped


def nav_html(groups: list[tuple[str, list[Document]]], current: Document) -> str:
    sections = []
    for label, documents in groups:
        links = "".join(
            (
                f'<a class="shelf-link{" is-active" if item == current else ""}" '
                f'href="{item.output_name}" data-search="{html.escape((item.title + " " + item.relative).casefold())}">'
                f'<span>{html.escape(item.title)}</span>'
                f'<small>{html.escape(item.relative)}</small></a>'
            )
            for item in documents
        )
        sections.append(
            f'<section class="shelf-group"><h2>{html.escape(label)}</h2>{links}</section>'
        )
    return "".join(sections)


def search_index(documents: list[Document]) -> str:
    payload = [
        {
            "title": document.title,
            "path": document.relative,
            "url": document.output_name,
            "summary": document.summary,
            "headings": list(document.headings),
        }
        for document in documents
    ]
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def document_cards(groups: list[tuple[str, list[Document]]]) -> str:
    cards = []
    for group, documents in groups:
        visible = [document for document in documents if document.relative != "README.md"]
        if not visible:
            continue
        links = "".join(
            f'<a class="document-card" href="{document.output_name}">'
            f'<span class="card-path">{html.escape(document.relative)}</span>'
            f'<strong>{html.escape(document.title)}</strong>'
            f'<span>{html.escape(document.summary or "Open document")}</span>'
            f'<em>{max(1, round(document.words / 220))} min read</em></a>'
            for document in visible
        )
        cards.append(
            f'<section class="collection"><div class="collection-heading">'
            f'<p>Collection</p><h2>{html.escape(group)}</h2></div>'
            f'<div class="document-grid">{links}</div></section>'
        )
    return "".join(cards)


def page_template(
    document: Document,
    body: str,
    toc: str,
    nav: str,
    index_data: str,
    previous: Document | None,
    following: Document | None,
    groups: list[tuple[str, list[Document]]],
    document_count: int,
    excluded_count: int,
) -> str:
    front_matter = ""
    if document.front_matter:
        front_matter = (
            '<details class="front-matter"><summary>Document metadata</summary>'
            f'<pre><code>{html.escape(document.front_matter)}</code></pre></details>'
        )
    source_link = (
        f'<a href="{REPOSITORY_URL}/blob/main/{document.relative}">View Markdown source ↗</a>'
        if document.source.is_file()
        else ""
    )
    previous_link = (
        f'<a class="pager-link previous" href="{previous.output_name}"><span>Previous</span>'
        f'<strong>{html.escape(previous.title)}</strong></a>'
        if previous
        else '<span class="pager-spacer"></span>'
    )
    next_link = (
        f'<a class="pager-link next" href="{following.output_name}"><span>Next</span>'
        f'<strong>{html.escape(following.title)}</strong></a>'
        if following
        else '<span class="pager-spacer"></span>'
    )
    home_hero = ""
    if document.relative == "README.md":
        home_hero = (
            '<section class="library-hero" aria-labelledby="library-title">'
            '<div class="hero-kicker">Grounded DocParse / reading room</div>'
            '<h1 id="library-title">Every guide.<br><em>One evidence trail.</em></h1>'
            '<p>Read product, workflow, architecture, API, setup, research, and project documentation '
            'without leaving the site.</p>'
            f'<div class="hero-stats"><span><strong>{document_count}</strong> included documents</span>'
            f'<span><strong>{excluded_count}</strong> security documents intentionally excluded</span></div>'
            '<label class="hero-search"><span>Search titles and sections</span>'
            '<input type="search" data-global-search placeholder="Try “routing”, “Azure”, or “API”" '
            'autocomplete="off"></label><div class="search-results" data-search-results></div>'
            '</section>'
            f'<div class="collections">{document_cards(groups)}</div>'
            '<div class="readme-divider"><span>Repository overview</span></div>'
        )
    article_title = "Repository overview" if document.relative == "README.md" else document.title
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="theme-color" content="#0b1118">
  <meta name="description" content="{html.escape(document.summary or document.title, quote=True)}">
  <title>{html.escape(document.title)} · Grounded DocParse Docs</title>
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="assets/styles.css">
  <script>window.DOCS_SEARCH_INDEX = {index_data};</script>
  <script defer src="assets/app.js"></script>
</head>
<body data-page="{html.escape(document.output_name)}">
  <a class="skip-link" href="#content">Skip to content</a>
  <div class="reading-progress" aria-hidden="true"><span></span></div>
  <header class="topbar">
    <button class="icon-button menu-button" type="button" data-menu-toggle aria-label="Open document navigation" aria-expanded="false">
      <span></span><span></span><span></span>
    </button>
    <a class="brand" href="index.html" aria-label="Grounded DocParse documentation home">
      <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
      <span><strong>Grounded DocParse</strong><small>Documentation</small></span>
    </a>
    <div class="topbar-path"><span>Source</span>{html.escape(document.relative)}</div>
    <button class="icon-button search-button" type="button" data-search-toggle aria-label="Focus document search">/</button>
  </header>
  <div class="site-shell">
    <aside class="document-shelf" data-document-shelf aria-label="Document navigation">
      <div class="shelf-search">
        <label for="shelf-search">Find a document</label>
        <input id="shelf-search" type="search" data-shelf-search placeholder="Filter the shelf…" autocomplete="off">
        <span class="keyboard-hint">/</span>
      </div>
      <nav>{nav}</nav>
      <footer><span>{document_count} documents</span><a href="{REPOSITORY_URL}">Repository ↗</a></footer>
    </aside>
    <button class="shelf-backdrop" type="button" data-menu-close aria-label="Close document navigation"></button>
    <main id="content" class="reading-pane">
      {home_hero}
      <article class="document-article">
        <header class="document-header title-frame">
          <span class="corner top-left"></span><span class="corner top-right"></span>
          <span class="corner bottom-left"></span><span class="corner bottom-right"></span>
          <p class="document-path">{html.escape(document.relative)}</p>
          <h1>{html.escape(article_title)}</h1>
          <div class="document-meta">
            <span>{document.words:,} words</span>
            <span>{max(1, round(document.words / 220))} min read</span>
            {source_link}
          </div>
        </header>
        {front_matter}
        <div class="markdown-body">{body}</div>
        <nav class="document-pager" aria-label="Previous and next documents">{previous_link}{next_link}</nav>
      </article>
    </main>
    <aside class="page-outline" aria-label="On this page">
      <p>On this page</p>
      <div class="outline-scroll">{toc or '<span class="outline-empty">No section headings</span>'}</div>
      <a class="back-to-top" href="#content">Back to top ↑</a>
    </aside>
  </div>
</body>
</html>
"""


def excluded_page(nav: str, index_data: str, document_count: int, excluded_count: int) -> str:
    placeholder = Document(
        source=ROOT,
        relative="Excluded content",
        output_name="security-content-excluded.html",
        title="Content intentionally excluded",
        summary="Security-specific documentation is not included in this website.",
        raw_body="",
        front_matter="",
        words=15,
        headings=(),
    )
    body = (
        '<div class="exclusion-notice"><p class="eyebrow">Not part of this build</p>'
        '<h2>Security-specific documentation is intentionally excluded.</h2>'
        '<p>Return to the document shelf to continue reading the included product, workflow, '
        'architecture, operations, research, and project documentation.</p>'
        '<a class="button-link" href="index.html">Return to documentation home</a></div>'
    )
    return page_template(
        placeholder,
        body,
        "",
        nav,
        index_data,
        None,
        None,
        [],
        document_count,
        excluded_count,
    )


def main() -> None:
    paths, excluded_paths = discover_markdown()
    documents = {document.relative: document for document in map(extract_document, paths)}
    excluded = {path.relative_to(ROOT).as_posix() for path in excluded_paths}
    groups = grouped_documents(documents)
    ordered = [document for _label, items in groups for document in items]
    mapping = {document.relative: document for document in ordered}
    index_data = search_index(ordered)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    manifest_path = OUTPUT / "site-manifest.json"
    expected_pages = {document.output_name for document in ordered}
    expected_pages.add("security-content-excluded.html")
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        for filename in previous.get("pages", []):
            candidate = OUTPUT / Path(filename).name
            if candidate.name not in expected_pages and candidate.parent == OUTPUT:
                candidate.unlink(missing_ok=True)

    for index, document in enumerate(ordered):
        converter = markdown.Markdown(
            extensions=["extra", "sane_lists", "toc"],
            extension_configs={
                "toc": {
                    "permalink": "#",
                    "permalink_class": "heading-anchor",
                    "permalink_title": "Copy section link",
                    "toc_depth": "2-4",
                }
            },
            output_format="html5",
        )
        rendered = converter.convert(normalize_indented_fences(document.raw_body))
        rendered = rewrite_links(rendered, document, mapping, excluded)
        rendered = copy_local_images(rendered, document)
        page = page_template(
            document=document,
            body=rendered,
            toc=converter.toc,
            nav=nav_html(groups, document),
            index_data=index_data,
            previous=ordered[index - 1] if index else None,
            following=ordered[index + 1] if index + 1 < len(ordered) else None,
            groups=groups,
            document_count=len(ordered),
            excluded_count=len(excluded_paths),
        )
        page = re.sub(r"[ \t]+(?=\n)", "", page)
        (OUTPUT / document.output_name).write_text(page, encoding="utf-8", newline="\n")

    current = documents["README.md"]
    exclusion_page = excluded_page(
        nav_html(groups, current), index_data, len(ordered), len(excluded_paths)
    )
    exclusion_page = re.sub(r"[ \t]+(?=\n)", "", exclusion_page)
    (OUTPUT / "security-content-excluded.html").write_text(
        exclusion_page,
        encoding="utf-8",
        newline="\n",
    )
    manifest = {
        "included": [document.relative for document in ordered],
        "excluded_count": len(excluded_paths),
        "pages": [document.output_name for document in ordered],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Built {len(ordered)} documentation pages in {OUTPUT}")
    print(f"Excluded {len(excluded_paths)} security-related Markdown files")


if __name__ == "__main__":
    main()
