from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from .agentic import DocumentAgent
from .config import ParserConfig
from .models import StoredSchema
from .native import (
    NativeParseResult,
    PageRoute,
    ProcessingType,
    render_native_combined_result,
)
from .native_extraction import LangExtractNativeExtractor
from .pipeline import DocumentParser
from .render import render_combined_result
from .schema_store import (
    MAX_MARKDOWN_SCHEMA_BYTES,
    compile_json_schema,
    parse_markdown_schema,
)
from .universal import UniversalDocumentParser

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
UNIVERSAL_SUFFIXES = SUPPORTED_SUFFIXES | {
    ".docx",
    ".pptx",
    ".xlsx",
    ".csv",
    ".odt",
    ".odp",
    ".ods",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".epub",
}


def _safe_stem(path: Path) -> str:
    value = re.sub(r"[^\w. -]+", "_", path.stem, flags=re.UNICODE).strip(" .")
    return value or "document"


def _write(path: Path, value: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if isinstance(value, bytes):
        temporary.write_bytes(value)
    else:
        temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grounded-docparse")
    commands = parser.add_subparsers(dest="command", required=True)
    parse = commands.add_parser("parse", help="Parse documents into grounded outputs")
    parse.add_argument("inputs", nargs="+", type=Path)
    parse.add_argument("--schema", type=Path)
    parse.add_argument("--output", required=True, type=Path)
    parse.add_argument("--overwrite", action="store_true")
    parse.add_argument(
        "--ocr-disagreement",
        action="store_true",
        help="Cross-check only uncertain regions with the alternate local OCR engine",
    )
    ingest = commands.add_parser(
        "ingest", help="Parse manually classified native and OCR documents"
    )
    ingest.add_argument("inputs", nargs="+", type=Path)
    ingest.add_argument(
        "--processing-type",
        action="append",
        required=True,
        metavar="PATH=TYPE",
    )
    ingest.add_argument(
        "--page-route",
        action="append",
        default=[],
        metavar="PATH#PAGE=ROUTE",
    )
    ingest.add_argument("--output", required=True, type=Path)
    ingest.add_argument("--schema", type=Path)
    ingest.add_argument("--overwrite", action="store_true")
    return parser


def _load_schema(path: Path) -> tuple[StoredSchema, dict]:
    data = path.read_bytes()
    if len(data) > MAX_MARKDOWN_SCHEMA_BYTES:
        raise ValueError("schema exceeds 1 MB")
    if path.suffix.casefold() == ".md":
        stored = parse_markdown_schema(data, path.name)
    elif path.suffix.casefold() == ".json":
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON schema is malformed") from exc
        stored = (
            StoredSchema.model_validate(value)
            if isinstance(value, dict) and "name" in value
            else StoredSchema(version=2, name=path.stem, json_schema=value)
        )
    else:
        raise ValueError("schema must use the .json or .md extension")
    return stored, compile_json_schema(stored)


def _discover(
    inputs: Sequence[Path],
    suffixes: set[str] = SUPPORTED_SUFFIXES,
) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for value in inputs:
        if not value.exists():
            raise ValueError(f"input does not exist: {value}")
        if value.is_dir():
            candidates = sorted(
                (
                    path
                    for path in value.iterdir()
                    if path.is_file() and path.suffix.casefold() in suffixes
                ),
                key=lambda path: path.name.casefold(),
            )
        elif value.suffix.casefold() not in suffixes:
            raise ValueError(f"unsupported input type: {value}")
        else:
            candidates = [value]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                discovered.append(candidate)
    if not discovered:
        raise ValueError("no supported documents were found")
    return discovered


def _processing_types(
    values: Sequence[str],
    sources: Sequence[Path],
) -> dict[Path, ProcessingType]:
    assignments: dict[Path, ProcessingType] = {}
    for value in values:
        raw_path, separator, raw_type = value.rpartition("=")
        if not separator or not raw_path or not raw_type:
            raise ValueError("--processing-type must use PATH=TYPE")
        path = Path(raw_path).resolve()
        if path in assignments:
            raise ValueError(f"duplicate processing type for {raw_path}")
        try:
            assignments[path] = ProcessingType(raw_type)
        except ValueError as exc:
            raise ValueError(f"unknown processing type: {raw_type}") from exc
    expected = {path.resolve() for path in sources}
    missing = expected - assignments.keys()
    unused = assignments.keys() - expected
    if missing:
        raise ValueError(
            "missing processing type for: "
            + ", ".join(sorted(path.name for path in missing))
        )
    if unused:
        raise ValueError(
            "processing type provided for unknown input: "
            + ", ".join(sorted(str(path) for path in unused))
        )
    return assignments


def _page_routes(values: Sequence[str]) -> dict[Path, dict[int, PageRoute]]:
    assignments: dict[Path, dict[int, PageRoute]] = {}
    for value in values:
        target, separator, raw_route = value.rpartition("=")
        raw_path, page_separator, raw_page = target.rpartition("#")
        if not separator or not page_separator or not raw_path:
            raise ValueError("--page-route must use PATH#PAGE=ROUTE")
        try:
            page = int(raw_page)
            route = PageRoute(raw_route)
        except ValueError as exc:
            raise ValueError(f"invalid page route: {value}") from exc
        if page < 1:
            raise ValueError("page route numbers must be positive")
        routes = assignments.setdefault(Path(raw_path).resolve(), {})
        if page in routes:
            raise ValueError(f"duplicate page route for {raw_path} page {page}")
        routes[page] = route
    return assignments


def _parse(args: argparse.Namespace) -> int:
    stored_schema = None
    compiled_schema = None
    if args.schema is not None:
        stored_schema, compiled_schema = _load_schema(args.schema)
    sources = [
        (path, data, hashlib.sha256(data).hexdigest())
        for path in _discover(args.inputs)
        for data in [path.read_bytes()]
    ]
    parser = DocumentParser(
        replace(
            ParserConfig.from_env(),
            ocr_disagreement_enabled=args.ocr_disagreement,
        )
    )
    agent = DocumentAgent() if compiled_schema is not None else None
    documents = []
    had_error = False
    used_folders: set[str] = set()
    for index, (source_path, source, digest) in enumerate(sources, start=1):
        stem = _safe_stem(source_path)
        base_folder = f"{stem}-{digest[:8]}"
        folder_name = base_folder
        duplicate_index = 2
        while folder_name.casefold() in used_folders:
            folder_name = f"{base_folder}-{duplicate_index}"
            duplicate_index += 1
        used_folders.add(folder_name.casefold())
        folder = args.output / folder_name
        entry = {
            "source": str(source_path),
            "name": source_path.name,
            "sha256": digest,
            "status": "complete",
            "failed_stage": None,
            "error": None,
            "folder": folder.name,
            "files": [],
        }
        print(
            f"[{index}/{len(sources)}] {source_path.name}: parsing",
            file=sys.stderr,
        )
        try:
            result = parser.parse(source, source_path.name)
        except Exception as exc:  # noqa: BLE001 - isolate batch documents
            error = f"{type(exc).__name__}: {str(exc)[:1000]}"
            entry.update(status="failed", failed_stage="parse", error=error)
            had_error = True
            print(f"{source_path.name}: {error}", file=sys.stderr)
            documents.append(entry)
            continue

        extraction = None
        if agent is not None:
            try:
                extraction = agent.extract(result, compiled_schema)
            except Exception as exc:  # noqa: BLE001 - preserve parse outputs
                error = f"{type(exc).__name__}: {str(exc)[:1000]}"
                entry.update(status="failed", failed_stage="extract", error=error)
                had_error = True
                print(f"{source_path.name}: {error}", file=sys.stderr)
        files = [
            f"{folder.name}/{stem}.md",
            f"{folder.name}/{stem}.annotated.pdf",
            f"{folder.name}/{stem}.full.json",
        ]
        try:
            _write(folder / f"{stem}.md", result.markdown)
            _write(folder / f"{stem}.annotated.pdf", result.annotated_pdf)
            _write(
                folder / f"{stem}.full.json",
                render_combined_result(result, extraction=extraction) + "\n",
            )
            if extraction is not None:
                files.append(f"{folder.name}/{stem}.extract.json")
                _write(folder / f"{stem}.extract.json", extraction.json + "\n")
            entry["files"] = files
        except Exception as exc:  # noqa: BLE001 - isolate output failures
            error = f"{type(exc).__name__}: {str(exc)[:1000]}"
            entry.update(status="failed", failed_stage="write", error=error)
            had_error = True
            print(f"{source_path.name}: {error}", file=sys.stderr)
        documents.append(entry)

    manifest = {
        "version": 1,
        "command": "parse",
        "schema": (
            {
                "name": stored_schema.name,
                "path": str(args.schema),
                "sha256": hashlib.sha256(args.schema.read_bytes()).hexdigest(),
            }
            if stored_schema is not None
            else None
        ),
        "documents": documents,
    }
    _write(args.output / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    print(
        f"{len(documents) - sum(item['status'] == 'failed' for item in documents)} "
        f"succeeded, {sum(item['status'] == 'failed' for item in documents)} failed; "
        f"manifest: {args.output / 'manifest.json'}"
    )
    return int(had_error)


def _ingest(args: argparse.Namespace) -> int:
    stored_schema = None
    compiled_schema = None
    if args.schema is not None:
        stored_schema, compiled_schema = _load_schema(args.schema)
    sources = _discover(args.inputs, UNIVERSAL_SUFFIXES)
    processing_types = _processing_types(args.processing_type, sources)
    page_routes = _page_routes(args.page_route)
    unknown_routes = page_routes.keys() - {path.resolve() for path in sources}
    if unknown_routes:
        raise ValueError(
            "page route provided for unknown input: "
            + ", ".join(sorted(str(path) for path in unknown_routes))
        )
    parser = UniversalDocumentParser()
    documents = []
    had_error = False
    for index, source_path in enumerate(sources, start=1):
        source = source_path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        stem = _safe_stem(source_path)
        folder = args.output / f"{stem}-{digest[:8]}"
        processing_type = processing_types[source_path.resolve()]
        entry = {
            "source": str(source_path),
            "name": source_path.name,
            "sha256": digest,
            "processing_type": processing_type.value,
            "status": "complete",
            "failed_stage": None,
            "error": None,
            "folder": folder.name,
            "files": [],
        }
        print(
            f"[{index}/{len(sources)}] {source_path.name}: {processing_type.value}",
            file=sys.stderr,
        )
        try:
            result = parser.parse(
                source,
                source_path.name,
                processing_type=processing_type,
                page_routes=page_routes.get(source_path.resolve()),
            )
            extraction = None
            if stored_schema is not None:
                if isinstance(result, NativeParseResult):
                    extraction = LangExtractNativeExtractor().extract(
                        result, stored_schema
                    )
                    full_json = render_native_combined_result(result, extraction)
                else:
                    extraction = DocumentAgent().extract(result, compiled_schema)
                    full_json = render_combined_result(result, extraction=extraction)
            else:
                full_json = result.json
            files = [f"{folder.name}/{stem}.md", f"{folder.name}/{stem}.full.json"]
            _write(folder / f"{stem}.md", result.markdown)
            _write(folder / f"{stem}.full.json", full_json + "\n")
            if extraction is not None:
                files.append(f"{folder.name}/{stem}.extract.json")
                _write(folder / f"{stem}.extract.json", extraction.json + "\n")
            annotated_pdf = getattr(result, "annotated_pdf", None)
            if annotated_pdf is not None:
                files.append(f"{folder.name}/{stem}.annotated.pdf")
                _write(folder / f"{stem}.annotated.pdf", annotated_pdf)
            entry["files"] = files
        except Exception as exc:  # noqa: BLE001 - isolate batch documents
            error = f"{type(exc).__name__}: {str(exc)[:1000]}"
            entry.update(status="failed", failed_stage="parse", error=error)
            had_error = True
            print(f"{source_path.name}: {error}", file=sys.stderr)
        documents.append(entry)
    manifest = {
        "version": 1,
        "command": "ingest",
        "schema": str(args.schema) if stored_schema is not None else None,
        "documents": documents,
    }
    _write(args.output / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return int(had_error)


def _validate_output(args: argparse.Namespace) -> None:
    if args.output.exists() and not args.output.is_dir():
        raise ValueError("output path must be a directory")
    if args.output.exists() and any(args.output.iterdir()) and not args.overwrite:
        raise ValueError("output directory is not empty; use --overwrite")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "parse":
        try:
            if args.schema is not None and not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is required when --schema is used")
            _validate_output(args)
            return _parse(args)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.command == "ingest":
        try:
            if args.schema is not None and not os.getenv("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is required when --schema is used")
            _validate_output(args)
            return _ingest(args)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
