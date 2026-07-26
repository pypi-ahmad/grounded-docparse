from __future__ import annotations

import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image, ImageSequence

from .models import DocumentNode, DocumentTree, NodeType, ParseResult, QualityReport

UNRESOLVED = {"unreadable", "unresolved"}


def _content_nodes(tree: DocumentTree, page_number: int) -> list[DocumentNode]:
    page = next(page for page in tree.pages if page.number == page_number)
    return [tree.nodes[node_id] for node_id in page.content_node_ids]


def _table_stats(tree: DocumentTree, nodes: list[DocumentNode]) -> dict[str, float | int]:
    tables = [node for node in nodes if node.type == NodeType.TABLE.value]
    cells = [
        tree.nodes[cell_id]
        for table in tables
        for row_id in table.children_ids
        if row_id in tree.nodes
        for cell_id in tree.nodes[row_id].children_ids
        if cell_id in tree.nodes
    ]
    return {
        "table_count": len(tables),
        "cell_count": len(cells),
        "nonempty_cell_rate": (
            sum(bool((cell.text or "").strip()) for cell in cells) / len(cells)
            if cells
            else 1.0
        ),
        "exact_cell_grounding_rate": (
            sum(cell.bbox is not None for cell in cells) / len(cells) if cells else 1.0
        ),
        "mean_cell_confidence": (
            sum(cell.confidence.score if cell.confidence else 0 for cell in cells)
            / len(cells)
            if cells
            else 1.0
        ),
    }


def build_quality_report(tree: DocumentTree) -> QualityReport:
    page_reports: list[dict[str, object]] = []
    all_nodes: list[DocumentNode] = []
    for page in tree.pages:
        nodes = _content_nodes(tree, page.number)
        all_nodes.extend(nodes)
        readable = [
            node
            for node in nodes
            if node.verification_status not in UNRESOLVED
            and bool((node.text or "").strip())
            and not (node.text or "").startswith("[UNREADABLE")
        ]
        disagreements = [
            node
            for node in nodes
            if len(node.recognition_candidates) > 1
            and (node.agreement_score or 0) < 0.9
        ]
        unresolved = [node for node in nodes if node.verification_status in UNRESOLVED]
        sources = Counter(
            candidate.source
            for node in nodes
            for candidate in node.recognition_candidates
        )
        page_reports.append(
            {
                "page_number": page.number,
                "region_count": len(nodes),
                "ocr_coverage": len(readable) / len(nodes) if nodes else 1.0,
                "disagreement_count": len(disagreements),
                "unresolved_count": len(unresolved),
                "mean_confidence": (
                    sum(node.confidence.score if node.confidence else 0 for node in nodes)
                    / len(nodes)
                    if nodes
                    else 1.0
                ),
                "provider_candidates": dict(sorted(sources.items())),
                "table_quality": _table_stats(tree, nodes),
            }
        )
    total = len(all_nodes)
    readable_total = sum(
        node.verification_status not in UNRESOLVED
        and bool((node.text or "").strip())
        and not (node.text or "").startswith("[UNREADABLE")
        for node in all_nodes
    )
    disagreement_total = sum(
        len(node.recognition_candidates) > 1 and (node.agreement_score or 0) < 0.9
        for node in all_nodes
    )
    unresolved_total = sum(
        node.verification_status in UNRESOLVED for node in all_nodes
    )
    return QualityReport(
        document_id=tree.document_id,
        source_sha256=tree.source_sha256,
        summary={
            "region_count": total,
            "ocr_coverage": readable_total / total if total else 1.0,
            "disagreement_count": disagreement_total,
            "disagreement_rate": disagreement_total / total if total else 0.0,
            "unresolved_count": unresolved_total,
            "unresolved_rate": unresolved_total / total if total else 0.0,
            "table_quality": _table_stats(tree, all_nodes),
            "warning_count": len(tree.warnings),
            "adaptive_retry_count": len(tree.adaptive_retries),
        },
        pages=page_reports,
        warnings=list(tree.warnings),
    )


def render_quality_json(tree: DocumentTree) -> str:
    return build_quality_report(tree).model_dump_json(indent=2)


def _source(node: DocumentNode) -> str:
    selected = next(
        (
            item.source
            for item in node.recognition_candidates
            if item.id == node.selected_candidate_id
        ),
        None,
    )
    return selected or "unresolved"


def _color(node: DocumentNode, selected: bool = False) -> tuple[float, float, float]:
    if selected:
        return (0.0, 0.35, 1.0)
    if node.verification_status in UNRESOLVED:
        return (0.85, 0.1, 0.1)
    if node.verification_status == "disputed":
        return (1.0, 0.55, 0.0)
    return (0.05, 0.65, 0.25)


def _as_pdf(data: bytes, filename: str) -> bytes:
    if Path(filename).suffix.casefold() == ".pdf":
        return data
    output = pymupdf.open()
    with Image.open(io.BytesIO(data)) as image:
        for frame in ImageSequence.Iterator(image):
            rgb = frame.convert("RGB")
            buffer = io.BytesIO()
            rgb.save(buffer, "PNG")
            page = output.new_page(width=rgb.width, height=rgb.height)
            page.insert_image(page.rect, stream=buffer.getvalue())
    result = output.tobytes()
    output.close()
    return result


def render_annotated_pdf(
    data: bytes,
    filename: str,
    tree: DocumentTree,
    *,
    selected_node_id: str | None = None,
) -> bytes:
    source = _as_pdf(data, filename)
    document = pymupdf.open(stream=source, filetype="pdf")
    for page_record in tree.pages:
        target_number = page_record.segment_page_number or page_record.number
        if not 1 <= target_number <= document.page_count:
            continue
        page = document[target_number - 1]
        for node in _content_nodes(tree, page_record.number):
            if node.bbox is None:
                continue
            rect = pymupdf.Rect(
                node.bbox.x0 * page.rect.width,
                node.bbox.y0 * page.rect.height,
                node.bbox.x1 * page.rect.width,
                node.bbox.y1 * page.rect.height,
            )
            color = _color(node, node.id == selected_node_id)
            page.draw_rect(rect, color=color, width=2 if node.id == selected_node_id else 1)
            confidence = node.confidence.score if node.confidence else 0
            label = f"#{(node.reading_order or 0) + 1} {confidence:.0%} {_source(node)}"
            point = pymupdf.Point(rect.x0, max(7, rect.y0 - 2))
            page.insert_text(point, label[:80], fontsize=6, color=color, overlay=True)
    result = document.tobytes(garbage=3, deflate=True)
    document.close()
    return result


def render_annotated_page(
    annotated_pdf: bytes,
    page_number: int,
    *,
    dpi: int = 130,
) -> bytes:
    with pymupdf.open(stream=annotated_pdf, filetype="pdf") as document:
        if not 1 <= page_number <= document.page_count:
            raise ValueError("page number is outside the annotated PDF")
        pixmap = document[page_number - 1].get_pixmap(
            matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False
        )
        return pixmap.tobytes("png")


def render_review_page(
    data: bytes,
    filename: str,
    tree: DocumentTree,
    page_number: int,
    *,
    selected_node_id: str | None = None,
    dpi: int = 130,
) -> bytes:
    source = _as_pdf(data, filename)
    with pymupdf.open(stream=source, filetype="pdf") as document:
        page_record = next(page for page in tree.pages if page.number == page_number)
        target_number = page_record.segment_page_number or page_record.number
        if not 1 <= target_number <= document.page_count:
            raise ValueError("page number is outside the source document")
        page = document[target_number - 1]
        for node in _content_nodes(tree, page_number):
            if node.bbox is None:
                continue
            rect = pymupdf.Rect(
                node.bbox.x0 * page.rect.width,
                node.bbox.y0 * page.rect.height,
                node.bbox.x1 * page.rect.width,
                node.bbox.y1 * page.rect.height,
            )
            selected = node.id == selected_node_id
            color = _color(node, selected)
            page.draw_rect(rect, color=color, width=3 if selected else 1)
            confidence = node.confidence.score if node.confidence else 0
            label = f"#{(node.reading_order or 0) + 1} {confidence:.0%} {_source(node)}"
            page.insert_text(
                pymupdf.Point(rect.x0, max(7, rect.y0 - 2)),
                label[:80],
                fontsize=6,
                color=color,
                overlay=True,
            )
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False
        )
        return pixmap.tobytes("png")


def build_batch_bundle(
    items: list[tuple[str, ParseResult | None, str | None]],
) -> bytes:
    buffer = io.BytesIO()
    manifest: list[dict[str, object]] = []
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for index, (filename, result, error_code) in enumerate(items, start=1):
            stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip(".-")
            stem = stem or "document"
            prefix = f"documents/{index:04d}-{stem}"
            while prefix.casefold() in used:
                prefix += "-copy"
            used.add(prefix.casefold())
            entry = {
                "index": index,
                "source_name": filename,
                "status": "complete" if result is not None else "failed",
                "document_id": result.tree.document_id if result is not None else None,
                "error_code": error_code if result is None else None,
                "path": prefix if result is not None else None,
            }
            manifest.append(entry)
            if result is None:
                continue
            with zipfile.ZipFile(io.BytesIO(result.bundle)) as archive:
                for member in archive.infolist():
                    normalized = Path(member.filename.replace("\\", "/"))
                    if normalized.is_absolute() or ".." in normalized.parts:
                        continue
                    output.writestr(f"{prefix}/{normalized.as_posix()}", archive.read(member))
        output.writestr(
            "batch.manifest.json",
            json.dumps(
                {"schema_version": "1.0.0", "documents": manifest},
                ensure_ascii=False,
                indent=2,
            ),
        )
    return buffer.getvalue()
