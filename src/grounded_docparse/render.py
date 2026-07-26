from __future__ import annotations

import html
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import DocumentNode, DocumentTree, NodeType


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _meta(node: DocumentNode) -> str:
    values = [f'data-node-id="{html.escape(node.id)}"']
    if node.confidence:
        values.append(f'data-confidence="{node.confidence.score:.3f}"')
    if node.bbox:
        bbox = ",".join(
            f"{value:.4f}"
            for value in (node.bbox.x0, node.bbox.y0, node.bbox.x1, node.bbox.y1)
        )
        values.append(f'data-bbox="{bbox}"')
    return " ".join(values)


def _table_html(node: DocumentNode) -> str:
    rows = node.attributes.get("table_rows")
    if not isinstance(rows, list):
        return f'<pre {_meta(node)}>{html.escape(node.text or "[UNREADABLE]")}</pre>'
    output = [f'<table {_meta(node)}>']
    for row in rows:
        if not isinstance(row, list):
            continue
        output.append("  <tr>")
        for cell in row:
            if not isinstance(cell, dict):
                continue
            tag = "th" if cell.get("header") else "td"
            attributes: list[str] = []
            for name in ("rowspan", "colspan"):
                try:
                    value = max(1, min(1000, int(cell.get(name, 1))))
                except (TypeError, ValueError):
                    value = 1
                if value > 1:
                    attributes.append(f'{name}="{value}"')
            if cell.get("citation_id"):
                attributes.append(
                    f'data-citation="{html.escape(str(cell["citation_id"]), quote=True)}"'
                )
            if cell.get("grounding_scope"):
                attributes.append(
                    f'data-grounding-scope="{html.escape(str(cell["grounding_scope"]), quote=True)}"'
                )
            if cell.get("page_number") is not None:
                attributes.append(f'data-page="{int(cell["page_number"])}"')
            if cell.get("confidence") is not None:
                attributes.append(f'data-confidence="{float(cell["confidence"]):.3f}"')
            bbox_value = cell.get("bbox")
            if isinstance(bbox_value, dict):
                try:
                    bbox = ",".join(
                        f"{float(bbox_value[key]):.4f}"
                        for key in ("x0", "y0", "x1", "y1")
                    )
                    attributes.append(f'data-bbox="{bbox}"')
                except (KeyError, TypeError, ValueError):
                    pass
            suffix = f" {' '.join(attributes)}" if attributes else ""
            output.append(
                f"    <{tag}{suffix}>{html.escape(str(cell.get('text', '')))}</{tag}>"
            )
        output.append("  </tr>")
    output.append("</table>")
    return "\n".join(output)


def _render_node_body(node: DocumentNode) -> str:
    text = node.text or ""
    node_type = NodeType(node.type)
    if node_type in {NodeType.SECTION, NodeType.HEADING}:
        level = _bounded_int(node.attributes.get("heading_level"), 2, 1, 6)
        return f"{'#' * level} {html.escape(text or '[UNREADABLE]')}"
    if node_type == NodeType.TABLE:
        return _table_html(node)
    if node_type in {
        NodeType.FIGURE,
        NodeType.IMAGE,
        NodeType.CHART,
        NodeType.SIGNATURE,
        NodeType.SEAL,
    }:
        source = html.escape(str(node.attributes.get("asset_path", "")))
        caption = html.escape(str(node.attributes.get("caption", text)))
        derived = ' data-derived="true"' if node.attributes.get("derived_caption") else ""
        return (
            f'<figure {_meta(node)}>\n'
            f'  <img src="{source}" alt="{caption}">\n'
            f'  <figcaption{derived}>{caption}</figcaption>\n'
            "</figure>"
        )
    if node_type == NodeType.FORMULA:
        formula = text.strip() or "\\text{[UNREADABLE]}"
        return f'<pre data-role="formula" {_meta(node)}>{html.escape(formula)}</pre>'
    if node_type == NodeType.LIST_ITEM:
        depth = _bounded_int(node.attributes.get("depth"), 0, 0, 8)
        return f"{'  ' * depth}- {html.escape(text or '[UNREADABLE]')}"
    if node_type == NodeType.FORM_FIELD and node.form_field:
        return (
            f'<dl data-role="form-field" {_meta(node)}>'
            f"<dt>{html.escape(node.form_field.label)}</dt>"
            f"<dd>{html.escape(node.form_field.value or '[UNREADABLE]')}</dd></dl>"
        )
    if node_type == NodeType.CHECKBOX and node.form_field:
        marker = {"checked": "[x]", "unchecked": "[ ]"}.get(
            node.form_field.state or "unknown", "[?]"
        )
        return f"{marker} {html.escape(node.form_field.label)}"
    if node_type == NodeType.FOOTNOTE:
        return f"[^{node.id}]: {html.escape(text or '[UNREADABLE]')}"
    if node_type == NodeType.HEADER:
        return f'<header {_meta(node)}>{html.escape(text)}</header>'
    if node_type == NodeType.FOOTER:
        return f'<footer {_meta(node)}>{html.escape(text)}</footer>'
    if node_type in {NodeType.SIDEBAR, NodeType.REFERENCE}:
        return f'<aside {_meta(node)}>{html.escape(text)}</aside>'
    if node_type in {NodeType.PARAGRAPH, NodeType.OCR_BLOCK, NodeType.CAPTION}:
        return f'<p {_meta(node)}>{html.escape(text or "[UNREADABLE]")}</p>'
    return html.escape(text)


def render_node(node: DocumentNode) -> str:
    body = _render_node_body(node)
    if node.visual_analysis:
        visual = node.visual_analysis
        details: list[str] = []
        if visual.chart_type:
            details.append(f"Chart type: {html.escape(visual.chart_type)}")
        if visual.axes:
            details.append(f"Axes: {html.escape('; '.join(visual.axes))}")
        if visual.legends:
            details.append(f"Legends: {html.escape('; '.join(visual.legends))}")
        if visual.data_points:
            rows = ["<table data-role=\"chart-data\"><tr><th>Series</th><th>Label</th><th>Value</th></tr>"]
            rows.extend(
                "<tr>"
                f"<td>{html.escape(point.series or '')}</td>"
                f"<td>{html.escape(point.label or '')}</td>"
                f"<td>{html.escape(point.value)}</td>"
                "</tr>"
                for point in visual.data_points
            )
            rows.append("</table>")
            details.append("\n".join(rows))
        if visual.derived_summary:
            details.append(
                '<p data-derived="true" data-literal="false">'
                f"{html.escape(visual.derived_summary)}</p>"
            )
        if details:
            body = f"{body}\n" + "\n".join(details)
    links = [
        link
        for link in node.links
        if urlparse(link.uri).scheme.lower() in {"http", "https", "mailto"}
    ]
    if not links:
        return body
    suffix = " ".join(
        f'<a href="{html.escape(link.uri, quote=True)}">source link</a>'
        for link in links
    )
    return f"{body}\n{suffix}" if body else suffix


def render_markdown(tree: DocumentTree) -> str:
    lines = [
        "---",
        f"schema_version: {tree.schema_version}",
        f"document_id: {tree.document_id}",
        f"source: {json.dumps(tree.source_name, ensure_ascii=False)}",
        f"pages: {len(tree.pages)}",
        "---",
        "",
    ]
    for page in tree.pages:
        lines.extend([f"<!-- page: {page.number}; node: {page.id} -->", ""])
        nodes = [tree.nodes[node_id] for node_id in page.content_node_ids]
        nodes.sort(key=lambda node: node.reading_order if node.reading_order is not None else 10**9)
        for node in nodes:
            if (
                node.parent_id
                and tree.nodes[node.parent_id].type
                in {NodeType.FIGURE.value, NodeType.IMAGE.value}
                and node.type == NodeType.CAPTION.value
            ):
                continue
            rendered = render_node(node).strip()
            if rendered:
                lines.extend([rendered, ""])
    if tree.warnings:
        warnings = "\n".join(html.escape(item) for item in tree.warnings)
        lines.extend([f'<pre data-role="parser-warnings">{warnings}</pre>', ""])
    return "\n".join(lines).rstrip() + "\n"


def _box_reference(box: Any) -> str:
    coordinates = ",".join(
        f"{value:.4f}" for value in (box.x0, box.y0, box.x1, box.y1)
    )
    return f"{box.unit}:{coordinates}"


def _source_comment(tree: DocumentTree, node: DocumentNode) -> str:
    ancestors: list[str] = []
    parent_id = node.parent_id
    semantic_containers = {
        NodeType.SECTION.value,
        NodeType.LIST.value,
        NodeType.FIGURE.value,
        NodeType.CHART.value,
        NodeType.TABLE.value,
    }
    while parent_id:
        parent = tree.nodes[parent_id]
        if parent.type in semantic_containers:
            ancestors.append(parent.id)
        parent_id = parent.parent_id
    citation = node.citations[0] if node.citations else None
    values = [f"citation={citation.id if citation else tree.document_id + ':' + node.id}", f"node={node.id}"]
    page_number = citation.page_number if citation else node.page_number
    bbox = citation.bbox if citation else node.bbox
    source_bbox = citation.source_bbox if citation else node.source_bbox
    confidence = citation.confidence if citation else (
        node.confidence.score if node.confidence else None
    )
    if page_number is not None:
        values.append(f"page={page_number}")
    if citation and citation.segment_page_number is not None:
        values.append(f"segment_page={citation.segment_page_number}")
    if bbox is not None:
        values.append(f"bbox={_box_reference(bbox)}")
    if source_bbox is not None:
        values.append(f"source_bbox={_box_reference(source_bbox)}")
    if confidence is not None:
        values.append(f"confidence={confidence:.3f}")
    if citation:
        values.append(f"grounding_scope={citation.grounding_scope}")
    if ancestors:
        values.append(f"section_path={'/'.join(reversed(ancestors))}")
    repeat_pages = node.attributes.get("repeat_pages")
    if isinstance(repeat_pages, list):
        values.append(f"repeat_pages={','.join(str(item) for item in repeat_pages)}")
    return f"<!-- source {'; '.join(values)} -->"


def render_llm_markdown(tree: DocumentTree) -> str:
    lines = [
        "---",
        "format: grounded-llm-markdown-v1",
        f"schema_version: {tree.schema_version}",
        f"document_id: {tree.document_id}",
        f"source: {json.dumps(tree.source_name, ensure_ascii=False)}",
        f"pages: {len(tree.pages)}",
        f"processing_profile: {tree.processing_profile}",
        "document_profile: "
        + (
            str(tree.document_classification.profile)
            if tree.document_classification
            else "unclassified"
        ),
        "---",
        "",
    ]
    if tree.grounded_fields:
        lines.extend(["## Grounded document fields", ""])
        for field in tree.grounded_fields:
            source_refs = "|".join(
                f"{source.node_id}@p{source.page_number or 'unknown'}"
                + (f"@{_box_reference(source.bbox)}" if source.bbox else "")
                for source in field.sources
            )
            lines.extend(
                [
                    f"<!-- grounded-field path={field.path}; sources={source_refs}; confidence={field.confidence:.3f} -->",
                    f"- **{html.escape(field.path)}:** {html.escape(field.normalized_value or field.raw_value)}",
                ]
            )
        lines.append("")
    form_nodes = [
        node
        for node in tree.nodes.values()
        if node.type in {NodeType.FORM_FIELD.value, NodeType.CHECKBOX.value}
        and node.form_field
    ]
    if form_nodes:
        lines.extend(["## Grounded form fields", ""])
        for node in sorted(
            form_nodes,
            key=lambda item: (
                item.page_number or 0,
                item.reading_order if item.reading_order is not None else 10**9,
            ),
        ):
            lines.extend([_source_comment(tree, node), render_node(node), ""])
    for page in tree.pages:
        lines.extend([f"<!-- page: {page.number}; node: {page.id} -->", ""])
        nodes = [tree.nodes[node_id] for node_id in page.content_node_ids]
        nodes.sort(
            key=lambda node: node.reading_order
            if node.reading_order is not None
            else 10**9
        )
        for node in nodes:
            if node.attributes.get("repeated_decoration") and any(
                relation.type == "repeats" for relation in node.relationships
            ):
                continue
            if (
                node.parent_id
                and tree.nodes[node.parent_id].type
                in {NodeType.FIGURE.value, NodeType.IMAGE.value, NodeType.CHART.value}
                and node.type == NodeType.CAPTION.value
            ):
                continue
            rendered = render_node(node).strip()
            if rendered:
                comments = [_source_comment(tree, node)]
                if node.type in {
                    NodeType.FIGURE.value,
                    NodeType.IMAGE.value,
                    NodeType.CHART.value,
                }:
                    comments.extend(
                        _source_comment(tree, tree.nodes[child_id])
                        for child_id in node.children_ids
                        if tree.nodes[child_id].type == NodeType.CAPTION.value
                    )
                lines.extend([*comments, rendered, ""])
    if tree.warnings:
        warnings = "\n".join(html.escape(item) for item in tree.warnings)
        lines.extend([f'<pre data-role="parser-warnings">{warnings}</pre>', ""])
    return "\n".join(lines).rstrip() + "\n"


def render_json(tree: DocumentTree) -> str:
    return tree.model_dump_json(indent=2)


def build_bundle(
    source_name: str,
    markdown: str,
    llm_markdown: str,
    audit_json: str,
    json_text: str,
    assets: dict[str, bytes],
    extra_files: dict[str, bytes | str] | None = None,
) -> bytes:
    stem = Path(source_name).stem
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{stem}.md", markdown)
        archive.writestr(f"{stem}.llm.md", llm_markdown)
        archive.writestr(f"{stem}.audit.json", audit_json)
        archive.writestr(f"{stem}.json", json_text)
        for path, content in sorted(assets.items()):
            archive.writestr(path, content)
        for path, content in sorted((extra_files or {}).items()):
            archive.writestr(path, content)
    return buffer.getvalue()
