from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf

from .models import Document, FormClassificationResult, ParseResult
from .render import render_agentic_document, render_annotated_pdf

MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BatchDocument:
    id: str
    name: str
    display_name: str
    source: bytes
    mime_type: str
    content_sha256: str

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.casefold()


@dataclass(frozen=True, slots=True)
class BatchArchiveEntry:
    name: str
    source: bytes
    status: Literal["pending", "complete", "failed"]
    error: str | None = None
    markdown: str | None = None
    annotated_pdf: bytes | None = None
    full_json: str | None = None
    extraction_json: str | None = None


def build_batch_documents(
    uploads: Sequence[tuple[str, bytes, str]], *, total_size: int | None = None
) -> list[BatchDocument]:
    if len(uploads) > MAX_BATCH_FILES:
        raise ValueError(f"Upload at most {MAX_BATCH_FILES} files in one batch.")
    measured_size = sum(len(source) for _name, source, _mime in uploads)
    if (measured_size if total_size is None else total_size) > MAX_BATCH_BYTES:
        raise ValueError("The combined upload size must not exceed 1 GB.")

    name_totals = Counter(name.casefold() for name, _source, _mime in uploads)
    name_occurrences: defaultdict[str, int] = defaultdict(int)
    content_occurrences: defaultdict[str, int] = defaultdict(int)
    documents: list[BatchDocument] = []
    for name, source, mime_type in uploads:
        content_sha256 = hashlib.sha256(source).hexdigest()
        identity = hashlib.sha256(name.encode("utf-8") + b"\0" + source).hexdigest()
        content_occurrences[identity] += 1
        document_id = f"{identity}:{content_occurrences[identity]}"
        normalized_name = name.casefold()
        name_occurrences[normalized_name] += 1
        display_name = (
            f"{name} ({name_occurrences[normalized_name]})"
            if name_totals[normalized_name] > 1
            else name
        )
        documents.append(
            BatchDocument(
                id=document_id,
                name=name,
                display_name=display_name,
                source=source,
                mime_type=mime_type,
                content_sha256=content_sha256,
            )
        )
    return documents


def _safe_name(value: str, fallback: str) -> str:
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    cleaned = re.sub(r"[^\w. -]+", "_", leaf, flags=re.UNICODE).strip(" .")
    return cleaned or fallback


def build_output_archive(entries: Sequence[BatchArchiveEntry]) -> bytes:
    output = io.BytesIO()
    manifest = {"version": 1, "documents": []}
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for index, entry in enumerate(entries, start=1):
            source_name = _safe_name(entry.name, f"document-{index}")
            stem = _safe_name(Path(source_name).stem, f"document-{index}")
            folder = f"{index:02d}-{stem}"
            outputs: list[str] = []

            original_path = f"{folder}/original/{source_name}"
            bundle.writestr(original_path, entry.source)
            outputs.append(original_path)

            generated = (
                (f"{folder}/{stem}.md", entry.markdown),
                (f"{folder}/{stem}.annotated.pdf", entry.annotated_pdf),
                (f"{folder}/{stem}.full.json", entry.full_json),
                (f"{folder}/{stem}.extract.json", entry.extraction_json),
            )
            for path, value in generated:
                if value is not None:
                    bundle.writestr(path, value)
                    outputs.append(path)

            manifest["documents"].append(
                {
                    "name": entry.name,
                    "sha256": hashlib.sha256(entry.source).hexdigest(),
                    "status": entry.status,
                    "error": entry.error,
                    "folder": folder,
                    "files": outputs,
                }
            )
        bundle.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )
    return output.getvalue()


def _pdf_range(source: bytes, start_page: int, end_page: int) -> bytes:
    with pymupdf.open(stream=source, filetype="pdf") as document:
        output = pymupdf.open()
        output.insert_pdf(document, from_page=start_page - 1, to_page=end_page - 1)
        try:
            return output.tobytes(garbage=3, deflate=True)
        finally:
            output.close()


def build_split_archive(
    source: bytes,
    source_name: str,
    parse_result: ParseResult,
    classification: FormClassificationResult,
) -> bytes:
    segments = sorted(
        classification.segments,
        key=lambda segment: (segment.start_page, segment.end_page, segment.id),
    )
    if any(not segment.approved for segment in segments):
        raise ValueError("all form segments must be approved before split export")
    covered = [
        page
        for segment in segments
        for page in range(segment.start_page, segment.end_page + 1)
    ]
    if covered != [page.number for page in parse_result.document.pages]:
        raise ValueError("form segments must cover every parsed page exactly once")

    source_pdf = render_annotated_pdf(
        source,
        source_name,
        [],
        page_count=len(parse_result.document.pages),
        show_reading_order=False,
    )
    pages = {page.number: page for page in parse_result.document.pages}
    output = io.BytesIO()
    manifest = {
        "version": 1,
        "source": {
            "name": source_name,
            "sha256": hashlib.sha256(source).hexdigest(),
        },
        "segments": [],
    }
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for index, segment in enumerate(segments, start=1):
            document = Document(
                source_name=parse_result.document.source_name,
                source_sha256=parse_result.document.source_sha256,
                pages=[
                    pages[number].model_copy(deep=True)
                    for number in range(segment.start_page, segment.end_page + 1)
                ],
            )
            rendered = render_agentic_document(document)
            segment_id = _safe_name(segment.id, f"form-{index:03d}").replace(" ", "_")
            category = _safe_name(segment.category, "other").replace(" ", "_")
            stem = (
                f"{index:03d}-{segment_id}-{category}-pages-"
                f"{segment.start_page:03d}-{segment.end_page:03d}"
            )
            files = [f"{stem}.pdf", f"{stem}.md", f"{stem}.json"]
            bundle.writestr(
                files[0],
                _pdf_range(source_pdf, segment.start_page, segment.end_page),
            )
            bundle.writestr(files[1], rendered.markdown)
            bundle.writestr(files[2], rendered.json)
            manifest["segments"].append(
                {
                    "segment": segment.model_dump(mode="json"),
                    "files": files,
                }
            )
        bundle.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )
    return output.getvalue()
