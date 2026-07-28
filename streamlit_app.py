from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path

import pymupdf
import streamlit as st
from PIL import Image, ImageSequence

from grounded_docparse import pipeline
from grounded_docparse.local_ocr import get_glmocr_runtime
from grounded_docparse.models import Element
from grounded_docparse.render import build_elements, render_annotated_pdf

SUPPORTED_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff"]
RESULT_VERSION = "4.0.0"
THUMBNAILS_PER_GROUP = 12
STAGE_LABELS = (
    ("layout", "Layout detection"),
    ("recognize", "Region recognition"),
    ("assemble", "Markdown assembly"),
    ("annotate", "Annotation"),
)


def reset_document_state() -> None:
    st.session_state.result = None
    st.session_state.result_source_hash = None
    st.session_state.parsed_source = None
    st.session_state.selected_element_id = None
    st.session_state.overview_page = 1


@st.cache_resource
def preload_local_ocr() -> object:
    return get_glmocr_runtime(
        os.getenv("DOCPARSE_GLMOCR_CONFIG_PATH", "config/glmocr.yaml"),
        os.getenv("DOCPARSE_GLMOCR_LAYOUT_DEVICE", "cuda:0"),
    )


@st.cache_data(max_entries=32)
def pdf_page_count(data: bytes) -> int:
    with pymupdf.open(stream=data, filetype="pdf") as document:
        return document.page_count


@st.cache_data(max_entries=16)
def select_pdf_pages(data: bytes, start: int, end: int) -> bytes:
    with pymupdf.open(stream=data, filetype="pdf") as source:
        if not 1 <= start <= end <= source.page_count:
            raise ValueError(f"page range must be within 1-{source.page_count}")
        output = pymupdf.open()
        output.insert_pdf(source, from_page=start - 1, to_page=end - 1)
        try:
            return output.tobytes(garbage=3, deflate=True)
        finally:
            output.close()


@st.cache_data(max_entries=64)
def pdf_page(data: bytes, page_index: int) -> bytes:
    with pymupdf.open(stream=data, filetype="pdf") as source:
        if not 0 <= page_index < source.page_count:
            raise ValueError("preview page is out of range")
        output = pymupdf.open()
        output.insert_pdf(source, from_page=page_index, to_page=page_index)
        try:
            return output.tobytes(garbage=3, deflate=True)
        finally:
            output.close()


@st.cache_data(max_entries=256)
def page_thumbnail(data: bytes, filename: str, page_index: int) -> bytes:
    if Path(filename).suffix.casefold() == ".pdf":
        with pymupdf.open(stream=data, filetype="pdf") as document:
            page = document[page_index]
            scale = min(1.0, 220 / max(page.rect.width, 1))
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return pixmap.tobytes("png")

    with Image.open(io.BytesIO(data)) as image:
        frames = list(ImageSequence.Iterator(image))
        if not 0 <= page_index < len(frames):
            raise ValueError("preview page is out of range")
        frame = frames[page_index].convert("RGB")
        frame.thumbnail((900, 1200))
        output = io.BytesIO()
        frame.save(output, format="PNG")
        return output.getvalue()


@st.cache_data(max_entries=32)
def annotation_variant(
    data: bytes,
    filename: str,
    elements_json: str,
    page_count: int,
    show_annotations: bool,
    show_reading_order: bool,
    selected_element_id: str | None,
) -> bytes:
    elements = [Element.model_validate(item) for item in json.loads(elements_json)]
    return render_annotated_pdf(
        data,
        filename,
        elements if show_annotations else [],
        page_count=page_count,
        show_reading_order=show_reading_order,
        selected_element_id=selected_element_id if show_annotations else None,
    )


def stage_markdown(active: str | None, completed: set[str]) -> str:
    lines = []
    for key, label in STAGE_LABELS:
        marker = "✓" if key in completed else "→" if key == active else "○"
        lines.append(f"{marker} {label}")
    return "  \n".join(lines)


def flattened_blocks(blocks, depth: int = 0):
    for block in sorted(blocks, key=lambda item: item.reading_order):
        yield block, depth
        yield from flattened_blocks(block.children, depth + 1)


def select_element(element_id: str | None) -> None:
    st.session_state.selected_element_id = element_id


st.set_page_config(
    page_title="Document Parse Studio",
    page_icon=":material/document_scanner:",
    layout="wide",
)

if st.session_state.get("result_version") != RESULT_VERSION:
    reset_document_state()
st.session_state.result_version = RESULT_VERSION

preload_error: str | None = None
if os.getenv("DOCPARSE_PRELOAD_LOCAL_OCR", "false").casefold() in {"1", "true", "yes"}:
    try:
        preload_local_ocr()
    except Exception as exc:  # noqa: BLE001 - startup diagnostics belong in the UI
        preload_error = f"Local OCR preload failed: {type(exc).__name__}: {exc}"

has_environment = bool(os.getenv("OPENAI_API_KEY"))
header_title, header_status = st.columns([4, 1], vertical_alignment="center")
with header_title:
    st.title("Document Parse Studio")
    st.caption("Layout-aware parsing with local GLM-OCR and bounded Luna verification.")

initial_status = "Ready" if has_environment and preload_error is None else "Not ready"
initial_color = "green" if initial_status == "Ready" else "red"
header_status_slot = header_status.empty()
header_status_slot.markdown(f"Status: :{initial_color}[● **{initial_status}**]")

if not has_environment:
    st.error("OPENAI_API_KEY is required in the environment.")
if preload_error is not None:
    st.error(preload_error)

with st.sidebar:
    st.subheader("Upload document")
    upload = st.file_uploader(
        "Document",
        type=SUPPORTED_TYPES,
        accept_multiple_files=False,
        max_upload_size=250,
        label_visibility="collapsed",
    )

source = upload.getvalue() if upload is not None else None
source_hash = hashlib.sha256(source).hexdigest() if source is not None else None
suffix = Path(upload.name).suffix.casefold() if upload is not None else ""

if st.session_state.get("active_upload_hash") != source_hash:
    reset_document_state()
    st.session_state.active_upload_hash = source_hash
    for key in ("range_start", "range_end", "thumbnail_group"):
        st.session_state.pop(key, None)

total_source_pages = pdf_page_count(source) if source is not None and suffix == ".pdf" else 1

with st.sidebar:
    st.subheader("Options")
    use_page_range = st.checkbox(
        "Page range",
        disabled=source is None or suffix != ".pdf",
        help="Parse one inclusive, contiguous page range.",
    )
    if use_page_range and source is not None:
        range_columns = st.columns(2)
        start_page = int(
            range_columns[0].number_input(
                "Start",
                min_value=1,
                max_value=total_source_pages,
                value=1,
                key="range_start",
            )
        )
        end_page = int(
            range_columns[1].number_input(
                "End",
                min_value=start_page,
                max_value=total_source_pages,
                value=total_source_pages,
                key="range_end",
            )
        )
    else:
        start_page, end_page = 1, total_source_pages

    show_reading_order = st.checkbox("Show reading order", value=True)
    selection_key = (
        f"{source_hash}:{start_page}:{end_page}" if source_hash is not None else None
    )
    if (
        st.session_state.get("result") is not None
        and st.session_state.get("result_source_hash") != selection_key
    ):
        reset_document_state()

    parse_clicked = st.button(
        "Parse document",
        type="primary",
        icon=":material/document_scanner:",
        disabled=source is None or not has_environment or preload_error is not None,
        width="stretch",
    )

    st.divider()
    st.subheader("Progress")
    cached_result_matches = (
        st.session_state.get("result") is not None
        and st.session_state.get("result_source_hash") == selection_key
    )
    progress_bar = st.progress(
        1.0 if cached_result_matches else 0,
        text="Parsing complete" if cached_result_matches else "Waiting for a document",
    )
    stage_log = st.empty()
    stage_log.markdown(
        stage_markdown(
            None,
            {key for key, _label in STAGE_LABELS} if cached_result_matches else set(),
        )
    )

if parse_clicked and upload is not None and source is not None:
    completed_stages: set[str] = set()
    progress_state: dict[str, str | None] = {"active": None}
    try:
        header_status_slot.markdown("Status: :blue[● **Parsing**]")
        parsed_source = (
            select_pdf_pages(source, start_page, end_page)
            if suffix == ".pdf" and use_page_range
            else source
        )

        def show_progress(event) -> None:
            stage = event.stage
            if stage == "layout":
                progress_state["active"] = "layout"
                value = 0.30 * event.current / max(event.total, 1)
            elif stage == "recognize":
                completed_stages.add("layout")
                progress_state["active"] = "recognize"
                value = 0.30 + 0.50 * event.current / max(event.total, 1)
            elif stage == "assemble":
                completed_stages.update({"layout", "recognize"})
                progress_state["active"] = "assemble"
                value = 0.88
            elif stage == "annotate":
                completed_stages.update({"layout", "recognize", "assemble"})
                progress_state["active"] = "annotate"
                value = 0.96
            elif stage == "complete":
                completed_stages.update(key for key, _label in STAGE_LABELS)
                progress_state["active"] = None
                value = 1.0
            else:
                value = None
            if value is not None:
                progress_bar.progress(value, text=event.message)
            stage_log.markdown(stage_markdown(progress_state["active"], completed_stages))

        result = pipeline.DocumentParser().parse(
            parsed_source,
            upload.name,
            progress_callback=show_progress,
        )
        st.session_state.result = result
        st.session_state.result_source_hash = selection_key
        st.session_state.parsed_source = parsed_source
        st.session_state.selected_element_id = None
        progress_bar.progress(1.0, text="Parsing complete")
        stage_log.markdown(stage_markdown(None, {key for key, _ in STAGE_LABELS}))
        header_status_slot.markdown("Status: :green[● **Complete**]")
    except Exception as exc:  # noqa: BLE001 - provider diagnostics are user-facing
        progress_bar.progress(0, text="Parsing failed")
        header_status_slot.markdown("Status: :red[● **Error**]")
        st.error(f"{type(exc).__name__}: {str(exc)[:1000]}")

result = st.session_state.get("result")
parsed_source = st.session_state.get("parsed_source")
has_result = (
    result is not None
    and parsed_source is not None
    and st.session_state.get("result_source_hash") == selection_key
)
if has_result:
    header_status_slot.markdown("Status: :green[● **Complete**]")

overview_tab, markdown_tab, annotated_tab, tree_tab = st.tabs(
    ["Overview", "Markdown", "Annotated PDF", "Layout Tree"]
)

if not has_result:
    with overview_tab:
        st.info("Upload a document and select Parse document to begin.")
else:
    elements = result.elements or build_elements(result.document)
    elements_json = json.dumps(
        [element.model_dump(mode="json") for element in elements],
        ensure_ascii=False,
    )
    parsed_pages = len(result.document.pages)
    stem = Path(result.document.source_name).stem
    selected_element_id = st.session_state.get("selected_element_id")

    with overview_tab:
        counts = {
            "tables": sum(element.type == "table" for element in elements),
            "figures": sum(
                element.type in {"figure", "image", "chart"} for element in elements
            ),
        }
        metrics = st.columns(5)
        metrics[0].metric("Pages", f"{parsed_pages:,}")
        metrics[1].metric("Regions", f"{len(elements):,}")
        metrics[2].metric("Tables", f"{counts['tables']:,}")
        metrics[3].metric("Figures", f"{counts['figures']:,}")
        metrics[4].metric("Time", f"{result.metadata.processing_time:.1f}s")

        st.subheader("Pages")
        group_count = max(1, math.ceil(parsed_pages / THUMBNAILS_PER_GROUP))
        group = (
            int(
                st.selectbox(
                    "Thumbnail group",
                    range(1, group_count + 1),
                    format_func=lambda value: f"Pages {(value - 1) * THUMBNAILS_PER_GROUP + 1}-"
                    f"{min(value * THUMBNAILS_PER_GROUP, parsed_pages)}",
                )
            )
            if group_count > 1
            else 1
        )
        first = (group - 1) * THUMBNAILS_PER_GROUP
        last = min(first + THUMBNAILS_PER_GROUP, parsed_pages)
        for row_start in range(first, last, 4):
            thumbnail_columns = st.columns(4)
            for column, page_index in zip(
                thumbnail_columns,
                range(row_start, min(row_start + 4, last)),
                strict=False,
            ):
                with column:
                    st.image(
                        page_thumbnail(parsed_source, upload.name, page_index),
                        width="stretch",
                    )
                    if st.button(
                        f"Page {page_index + 1}",
                        key=f"overview-page-{page_index + 1}",
                        type=(
                            "primary"
                            if st.session_state.overview_page == page_index + 1
                            else "secondary"
                        ),
                        width="stretch",
                    ):
                        st.session_state.overview_page = page_index + 1

        selected_page = min(max(st.session_state.overview_page, 1), parsed_pages)
        st.subheader(f"Original page {selected_page}")
        if suffix == ".pdf":
            st.pdf(
                pdf_page(parsed_source, selected_page - 1),
                height=720,
                key=f"original-page-{selected_page}",
            )
        else:
            st.image(
                page_thumbnail(parsed_source, upload.name, selected_page - 1),
                width="stretch",
            )

    with markdown_tab:
        show_raw_markdown = st.toggle("Show raw Markdown")
        if show_raw_markdown:
            st.code(result.markdown, language="markdown", wrap_lines=True, height=650)
            st.caption("Use the copy control in the code toolbar.")
        else:
            st.markdown(result.markdown)

    with annotated_tab:
        show_annotations = st.toggle("Show annotations", value=True)
        st.markdown(
            ":blue[■] Text / title · :green[■] Table / form · "
            ":orange[■] Figure · :violet[■] Formula · :red[■] Seal"
        )
        if selected_element_id:
            st.caption(f"Selected region: `{selected_element_id}`")
        viewer_pdf = annotation_variant(
            parsed_source,
            upload.name,
            elements_json,
            parsed_pages,
            show_annotations,
            show_reading_order,
            selected_element_id,
        )
        st.pdf(viewer_pdf, height=780, key=f"annotated-{show_annotations}")

    with tree_tab:
        st.caption(
            "Select a region, then open Annotated PDF to see its highlighted box."
        )
        order_by_id = {element.id: element.reading_order for element in elements}
        if selected_element_id:
            st.button(
                "Clear selection",
                icon=":material/close:",
                key="clear-element-selection",
                on_click=select_element,
                args=(None,),
            )
        for page in result.document.pages:
            with st.expander(f"Page {page.number}", expanded=page.number == 1):
                for block, depth in flattened_blocks(page.blocks):
                    preview = " ".join(block.text.split())[:72] or "No text"
                    label = (
                        f"{'    ' * depth}"
                        f"{order_by_id.get(block.id, block.reading_order + 1)} · "
                        f"{block.type.value.replace('_', ' ').title()} — {preview}"
                    )
                    st.button(
                        label,
                        key=f"select-element-{block.id}",
                        on_click=select_element,
                        args=(block.id,),
                    )

    canonical_annotated_pdf = annotation_variant(
        parsed_source,
        upload.name,
        elements_json,
        parsed_pages,
        True,
        show_reading_order,
        None,
    )
    with st.container(border=True):
        with st.container(horizontal=True, horizontal_alignment="distribute"):
            st.download_button(
                "Download Markdown",
                result.markdown,
                file_name=f"{stem}.md",
                mime="text/markdown",
                icon=":material/download:",
                key="download-markdown",
                on_click="ignore",
            )
            st.download_button(
                "Download annotated PDF",
                canonical_annotated_pdf,
                file_name=f"{stem}.annotated.pdf",
                mime="application/pdf",
                icon=":material/download:",
                key="download-annotated-pdf",
                on_click="ignore",
            )
            st.download_button(
                "Download JSON",
                result.json,
                file_name=f"{stem}.json",
                mime="application/json",
                icon=":material/download:",
                key="download-json",
                on_click="ignore",
            )
        st.caption(
            f"Engine: {result.metadata.engine} · Time: "
            f"{result.metadata.processing_time:.1f}s · Pages: {parsed_pages} · "
            f"Luna input tokens: {result.input_tokens:,} · "
            f"Luna output tokens: {result.output_tokens:,}"
        )
