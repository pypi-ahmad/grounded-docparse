from __future__ import annotations

import hashlib
import io
import json
import math
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pymupdf
import streamlit as st
from PIL import Image, ImageSequence

from grounded_docparse import pipeline, runtime_control
from grounded_docparse.agentic import DocumentAgent
from grounded_docparse.batch import (
    BatchArchiveEntry,
    BatchDocument,
    build_batch_documents,
    build_output_archive,
    build_split_archive,
)
from grounded_docparse.config import (
    AlternateOcrEngine,
    CloudModel,
    ExtractionEngine,
    OcrEngine,
    ParserConfig,
    default_alternate_ocr_engine,
)
from grounded_docparse.docling_native import make_docling_rapidocr_converter
from grounded_docparse.models import (
    ClassifierCategory,
    ClassifierProfile,
    Element,
    FormClassificationResult,
    FormSegment,
    ParseResult,
    RunUsage,
    SchemaField,
    StoredSchema,
)
from grounded_docparse.native import (
    NativeParseResult,
    PageRoute,
    ProcessingType,
    render_native_combined_result,
)
from grounded_docparse.native_extraction import LangExtractNativeExtractor
from grounded_docparse.native_parsers import DoclingNativeParser
from grounded_docparse.ocr_services import switch_extraction_engine
from grounded_docparse.ollama_runtime import (
    OllamaOcrModel,
    unload_model,
    warm_model,
)
from grounded_docparse.render import (
    build_elements,
    render_annotated_pdf,
    render_combined_result,
    sanitize_markdown_preview,
)
from grounded_docparse.schema_store import (
    ClassifierProfileStore,
    SchemaStore,
    compile_json_schema,
    parse_markdown_classifier_profile,
    parse_markdown_schema,
    parse_tabular_schema,
)
from grounded_docparse.universal import (
    UniversalDocumentParser,
    detect_source_format,
    inspect_pdf_content,
)
from grounded_docparse.usage_costs import (
    SessionUsageLedger,
    UsageCostSummary,
    summarize_calls,
)
from grounded_docparse.workspace_store import WorkspaceStore

SUPPORTED_TYPES = [
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "csv",
    "odt",
    "odp",
    "ods",
    "html",
    "htm",
    "md",
    "markdown",
    "epub",
    "png",
    "jpg",
    "jpeg",
    "tif",
    "tiff",
]
PROCESSING_LABELS = {
    "Native PDF": ProcessingType.NATIVE_PDF,
    "Scanned PDF": ProcessingType.SCANNED_PDF,
    "Mixed PDF": ProcessingType.MIXED_PDF,
    "Word": ProcessingType.WORD,
    "PowerPoint": ProcessingType.POWERPOINT,
    "Excel": ProcessingType.EXCEL,
    "CSV": ProcessingType.CSV,
    "Image": ProcessingType.IMAGE,
    "Other Native": ProcessingType.OTHER_NATIVE,
}
RESULT_VERSION = "4.6.0"
THUMBNAILS_PER_GROUP = 12
WORKSPACE_SETTING_KEYS = (
    "extraction_engine",
    "cloud_model",
    "cloud_model_label",
    "ollama_model",
    "ai_enhancement",
    "ade_mode",
    "refine_markdown",
    "classify_document",
    "generate_toc",
    "visual_recovery",
    "ocr_disagreement",
    "ocr_disagreement_engine",
    "ocr_engine_label",
    "use_page_range",
    "range_start",
    "range_end",
)
ADE_PRESETS = {
    "Fast": {
        "refine_markdown": False,
        "classify_document": True,
        "generate_toc": False,
    },
    "Full": {
        "refine_markdown": True,
        "classify_document": True,
        "generate_toc": True,
    },
}
STAGE_LABELS = (
    ("layout", "Layout detection"),
    ("recognize", "Region recognition"),
    ("recover", "Luna visual recovery"),
    ("cross_check", "Local OCR cross-check"),
    ("assemble", "Base Markdown"),
    ("annotate", "Annotated PDF"),
    ("enhance", "Luna Markdown refinement"),
    ("classify", "Document classification"),
    ("toc", "Table of contents"),
)
LUNA_REVIEW_WARNING = (
    "Luna output may be incorrect or influenced by instructions inside the document. "
    "Review confidence and cited source regions before consequential use."
)
HTML_PREVIEW_STYLES = """
<style>
.st-key-grounded-html-preview-native,
.st-key-grounded-html-preview-ocr {
    background: #ffffff;
    color: #111827;
    padding: clamp(1rem, 3vw, 2.5rem);
}
.st-key-grounded-html-preview-native [data-testid="stMarkdownContainer"],
.st-key-grounded-html-preview-ocr [data-testid="stMarkdownContainer"],
.st-key-grounded-html-preview-native [data-testid="stMarkdownContainer"] *,
.st-key-grounded-html-preview-ocr [data-testid="stMarkdownContainer"] * {
    color: #111827;
}
.st-key-grounded-html-preview-native [data-testid="stMarkdownContainer"] a,
.st-key-grounded-html-preview-ocr [data-testid="stMarkdownContainer"] a {
    color: #1d4ed8;
}
.st-key-grounded-html-preview-native [data-testid="stMarkdownContainer"] pre,
.st-key-grounded-html-preview-ocr [data-testid="stMarkdownContainer"] pre,
.st-key-grounded-html-preview-native [data-testid="stMarkdownContainer"] code,
.st-key-grounded-html-preview-ocr [data-testid="stMarkdownContainer"] code {
    background: #f3f4f6;
}
.st-key-grounded-html-preview-native [data-testid="stMarkdownContainer"] table,
.st-key-grounded-html-preview-ocr [data-testid="stMarkdownContainer"] table {
    display: block;
    max-width: 100%;
    overflow-x: auto;
}
</style>
"""
def processing_labels_for(suffix: str) -> list[str]:
    return {
        ".pdf": ["Native PDF", "Scanned PDF", "Mixed PDF"],
        ".docx": ["Word"],
        ".pptx": ["PowerPoint"],
        ".xlsx": ["Excel"],
        ".csv": ["CSV"],
        ".png": ["Image"],
        ".jpg": ["Image"],
        ".jpeg": ["Image"],
        ".tif": ["Image"],
        ".tiff": ["Image"],
    }.get(suffix.casefold(), ["Other Native"])


def processing_type_from_selection_key(selection_key: str | None) -> str | None:
    if selection_key is None:
        return None
    parts = selection_key.split(":")
    return next(
        (item.value for item in ProcessingType if item.value in parts),
        None,
    )


def page_routes_from_selection_key(
    selection_key: str | None,
) -> dict[int, PageRoute]:
    if selection_key is None:
        return {}
    marker = f":{ProcessingType.MIXED_PDF.value}:"
    _prefix, separator, tail = selection_key.partition(marker)
    if not separator:
        return {}
    route_text, separator, _version = tail.rpartition(":")
    if not separator:
        return {}
    routes: dict[int, PageRoute] = {}
    for item in route_text.split(","):
        if not item:
            continue
        page, separator, route = item.partition(":")
        if not separator:
            return {}
        try:
            routes[int(page)] = PageRoute(route)
        except (ValueError, TypeError):
            return {}
    return routes


@st.cache_data(max_entries=32)
def cached_pdf_inspection(data: bytes):
    return inspect_pdf_content(data)


def append_session_usage(usage: RunUsage | None, *, skip_calls: int = 0) -> None:
    if usage is None:
        return
    calls = [call.model_copy(deep=True) for call in usage.calls[skip_calls:]]
    session_usage = st.session_state.setdefault("session_usage", RunUsage())
    session_usage.calls.extend(calls)
    launch_session_usage_ledger().extend(calls)


@st.cache_resource
def _launch_session_usage_ledger(session_id: str) -> SessionUsageLedger:
    return SessionUsageLedger()


def launch_session_usage_ledger() -> SessionUsageLedger:
    session_id = os.getenv("DOCPARSE_APP_SESSION_ID", f"process-{os.getpid()}")
    return _launch_session_usage_ledger(session_id)


def launch_usage_summary() -> UsageCostSummary:
    return summarize_calls(launch_session_usage_ledger().snapshot())


def render_usage_metrics(summary: UsageCostSummary) -> None:
    usage_columns = st.columns(4)
    usage_columns[0].metric("Input tokens", f"{summary.input_tokens:,}")
    usage_columns[1].metric("Cache tokens", f"{summary.cached_input_tokens:,}")
    usage_columns[2].metric("Output tokens", f"{summary.output_tokens:,}")
    usage_columns[3].metric("Estimated cost", f"${summary.estimated_cost:.6f}")


def render_session_cost_page() -> None:
    st.title("Session cost")
    st.caption("Metered AI usage for the current Grounded DocParse app launch.")
    summary = launch_usage_summary()
    render_usage_metrics(summary)
    if summary.unavailable_calls:
        st.warning(
            f"Usage telemetry was unavailable for {summary.unavailable_calls} "
            "model call(s), so the estimate may be incomplete."
        )
    if not summary.models:
        st.info("No metered AI calls in this app session yet.")
        return
    rows = [
        {
            "Model": next(
                (item.label for item in CloudModel if item.value == row.model),
                row.model,
            ),
            "Input tokens": row.input_tokens,
            "Cache tokens": row.cached_input_tokens,
            "Output tokens": row.output_tokens,
            "Estimated cost": row.estimated_cost,
        }
        for row in summary.models
    ]
    rows.append(
        {
            "Model": "Total",
            "Input tokens": summary.input_tokens,
            "Cache tokens": summary.cached_input_tokens,
            "Output tokens": summary.output_tokens,
            "Estimated cost": summary.estimated_cost,
        }
    )
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={
            "Estimated cost": st.column_config.NumberColumn(format="$%.6f")
        },
    )
    for row in summary.models:
        cached_rate = (
            row.pricing.cached_input_per_million
            if row.pricing.cached_input_per_million is not None
            else row.pricing.input_per_million
        )
        st.caption(
            f"{row.model}: ${row.pricing.input_per_million:.2f}/M input, "
            f"${cached_rate:.2f}/M cached input, "
            f"${row.pricing.output_per_million:.2f}/M output"
        )
    pricing_date = datetime.now().astimezone().date().isoformat()
    st.caption(f"Pricing as of {pricing_date}; synchronous API rates.")


DOCUMENT_STATE_KEYS = (
    "result",
    "result_source_hash",
    "parsed_source",
    "selected_element_id",
    "overview_page",
    "annotated_page",
    "agentic_analysis",
    "agentic_source_hash",
    "extraction_result",
    "native_extraction_result",
    "custom_classification",
    "routed_extraction_result",
    "routing_review_rows",
    "chat_history",
    "prepared_agentic_context",
    "use_custom_routing",
    "studio_tab",
)


def default_document_state() -> dict[str, object]:
    return {
        "result": None,
        "result_source_hash": None,
        "parsed_source": None,
        "selected_element_id": None,
        "overview_page": 1,
        "annotated_page": 1,
        "agentic_analysis": None,
        "agentic_source_hash": None,
        "extraction_result": None,
        "native_extraction_result": None,
        "custom_classification": None,
        "routed_extraction_result": None,
        "routing_review_rows": None,
        "chat_history": [],
        "prepared_agentic_context": None,
        "use_custom_routing": False,
        "studio_tab": "Overview",
    }


def reset_document_state(*, clear_session_usage: bool = False) -> None:
    st.session_state.update(default_document_state())
    if clear_session_usage:
        st.session_state.session_usage = RunUsage()


def capture_document_state() -> dict[str, object]:
    defaults = default_document_state()
    return {
        key: st.session_state.get(key, defaults[key])
        for key in DOCUMENT_STATE_KEYS
    }


def save_active_workspace() -> None:
    document_id = st.session_state.get("active_document_id")
    workspace = st.session_state.get("batch_workspaces", {}).get(document_id)
    if workspace is not None:
        workspace["state"] = capture_document_state()


def load_workspace(document_id: str | None) -> None:
    reset_document_state()
    workspace = st.session_state.get("batch_workspaces", {}).get(document_id)
    if workspace is not None:
        st.session_state.update(workspace["state"])


def switch_active_document() -> None:
    save_active_workspace()
    document_id = st.session_state.get("batch_document_selector")
    st.session_state.active_document_id = document_id
    load_workspace(document_id)


def workspace_settings() -> dict[str, object]:
    return {
        key: st.session_state[key]
        for key in WORKSPACE_SETTING_KEYS
        if key in st.session_state
    }


def reset_extraction_mode_state() -> None:
    st.session_state.extraction_result = None
    st.session_state.native_extraction_result = None
    st.session_state.custom_classification = None
    st.session_state.routed_extraction_result = None
    st.session_state.routing_review_rows = None


def initialize_ade_mode() -> None:
    st.session_state.setdefault("ade_mode", "Fast")
    preset = ADE_PRESETS.get(st.session_state.ade_mode, ADE_PRESETS["Fast"])
    for key, value in preset.items():
        st.session_state.setdefault(key, value)
    st.session_state.setdefault("enable_chat", False)
    st.session_state.setdefault("visual_recovery", True)
    st.session_state.setdefault("ocr_disagreement", False)


def apply_ade_preset() -> None:
    preset = ADE_PRESETS.get(st.session_state.ade_mode)
    if preset is not None:
        st.session_state.update(preset)


def mark_ade_custom() -> None:
    values = {
        key: st.session_state[key]
        for key in ("refine_markdown", "classify_document", "generate_toc")
    }
    if all(values != preset for preset in ADE_PRESETS.values()):
        st.session_state.ade_mode = "Custom"
        return
    st.session_state.ade_mode = next(
        name for name, preset in ADE_PRESETS.items() if values == preset
    )


def apply_engine_selection(target: ExtractionEngine | None = None) -> None:
    target = target or ExtractionEngine(st.session_state.extraction_engine)
    previous_value = st.session_state.get("active_extraction_engine")
    previous = ExtractionEngine(previous_value) if previous_value else None
    if target is previous:
        return
    try:
        if previous is ExtractionEngine.OLLAMA and st.session_state.get("active_ollama_model"):
            unload_model(OllamaOcrModel(st.session_state.active_ollama_model))
        switch_extraction_engine(target, previous)
        if target is ExtractionEngine.OLLAMA:
            model = OllamaOcrModel(st.session_state.ollama_model)
            warm_model(model)
            st.session_state.active_ollama_model = model.value
    except Exception as exc:  # noqa: BLE001 - lifecycle failures must restore UI state
        st.session_state.engine_switch_error = str(exc)
        return
    st.session_state.extraction_engine = target.value
    st.session_state.active_extraction_engine = target.value
    st.session_state.pop("engine_switch_error", None)


def toggle_extraction_engine(target_value: str) -> None:
    target = ExtractionEngine(target_value)
    key = f"engine-toggle-{target.value}"
    previous_value = st.session_state.get("active_extraction_engine")
    previous = ExtractionEngine(previous_value) if previous_value else None
    if not st.session_state[key]:
        if previous is target:
            st.session_state[key] = True
        return
    for engine in ExtractionEngine:
        st.session_state[f"engine-toggle-{engine.value}"] = engine is target
    apply_engine_selection(target)
    if st.session_state.get("engine_switch_error"):
        for engine in ExtractionEngine:
            st.session_state[f"engine-toggle-{engine.value}"] = engine is previous


def change_ollama_model() -> None:
    selected = OllamaOcrModel(st.session_state.ollama_model)
    previous_value = st.session_state.get("active_ollama_model")
    if previous_value == selected.value:
        return
    try:
        if previous_value:
            unload_model(OllamaOcrModel(previous_value))
        warm_model(selected)
    except Exception as exc:  # noqa: BLE001 - model lifecycle errors are user-facing
        st.session_state.engine_switch_error = str(exc)
        if previous_value:
            st.session_state.ollama_model = previous_value
        return
    st.session_state.active_ollama_model = selected.value
    st.session_state.pop("engine_switch_error", None)


def request_managed_shutdown() -> None:
    try:
        runtime_control.schedule_managed_shutdown()
    except RuntimeError as exc:
        st.session_state.shutdown_error = str(exc)
    else:
        st.session_state.pop("shutdown_error", None)
        st.session_state.shutdown_requested = True


@st.dialog(
    "Stop app and background services",
    icon=":material/power_settings_new:",
)
def confirm_managed_shutdown() -> None:
    if st.session_state.get("shutdown_requested"):
        st.info("Stopping Grounded DocParse. You can close this browser tab.")
        return
    if st.session_state.get("shutdown_error"):
        st.error(st.session_state.shutdown_error)
    st.warning(
        "This stops Streamlit and all GLM-OCR, PaddleOCR, vLLM, and Ollama "
        "processes managed by this project."
    )
    st.caption("Saved workspace data is kept. Use either Windows launcher to restart.")
    st.button(
        "Stop now",
        key="confirm-managed-shutdown",
        type="primary",
        icon=":material/power_settings_new:",
        width="stretch",
        on_click=request_managed_shutdown,
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
    recovered_ids_json: str,
) -> bytes:
    elements = [Element.model_validate(item) for item in json.loads(elements_json)]
    return render_annotated_pdf(
        data,
        filename,
        elements if show_annotations else [],
        page_count=page_count,
        show_reading_order=show_reading_order,
        selected_element_id=selected_element_id if show_annotations else None,
        recovered_element_ids=(
            set(json.loads(recovered_ids_json)) if show_annotations else set()
        ),
    )


@st.cache_data(max_entries=8)
def output_archive(entries: tuple[BatchArchiveEntry, ...]) -> bytes:
    return build_output_archive(entries)


@st.cache_data(max_entries=8)
def split_output_archive(
    source: bytes,
    source_name: str,
    result: ParseResult,
    classification: FormClassificationResult,
) -> bytes:
    return build_split_archive(source, source_name, result, classification)


def stage_markdown(active: str | None, completed: set[str]) -> str:
    lines = []
    for key, label in STAGE_LABELS:
        marker = "✓" if key in completed else "→" if key == active else "○"
        lines.append(f"{marker} {label}")
    return "  \n".join(lines)


def render_grounded_html_preview(markdown: str, *, key: str) -> None:
    st.html(HTML_PREVIEW_STYLES)
    st.caption(
        "This HTML view renders grounded document content as a reflowed webpage "
        "for manual comparison; it is not a pixel-perfect copy of the original."
    )
    with st.container(key=key, border=True):
        st.markdown(
            sanitize_markdown_preview(markdown),
            unsafe_allow_html=True,
        )


def flattened_blocks(blocks, depth: int = 0):
    for block in sorted(blocks, key=lambda item: item.reading_order):
        yield block, depth
        yield from flattened_blocks(block.children, depth + 1)


def flattened_toc(sections, prefix: tuple[int, ...] = ()):
    for index, section in enumerate(sections, start=1):
        number = (*prefix, index)
        yield section, ".".join(str(item) for item in number)
        yield from flattened_toc(section.children, number)


def select_element(element_id: str | None) -> None:
    st.session_state.selected_element_id = element_id


def select_source(element_id: str, page: int) -> None:
    st.session_state.selected_element_id = element_id
    st.session_state.annotated_page = page
    st.session_state.studio_tab = "Annotated PDF"


studio_database_path = os.getenv(
    "DOCPARSE_STUDIO_DB_PATH", "data/document_studio.sqlite3"
)
schema_store = SchemaStore(studio_database_path)
classifier_profile_store = ClassifierProfileStore(studio_database_path)
workspace_store = WorkspaceStore(studio_database_path)


def render_schema_builder() -> StoredSchema | None:
    pending_draft = st.session_state.pop("pending_schema_draft", None)
    if pending_draft is not None:
        st.session_state.schema_draft_name = pending_draft["name"]
        st.session_state.schema_draft_mode = pending_draft.get("mode", "Field builder")
        st.session_state.schema_draft_fields = pending_draft.get("fields", [])
        st.session_state.schema_draft_raw = pending_draft.get("raw", "")
        st.session_state.schema_draft_revision = (
            st.session_state.get("schema_draft_revision", 0) + 1
        )

    schemas = schema_store.list()
    names = [schema.name for schema in schemas]
    selected = st.selectbox(
        "Saved schema",
        ["New schema", *names],
        key="schema_dialog_selection",
    )
    if selected != "New schema" and st.button("Load selected schema"):
        loaded = schema_store.get(selected)
        if loaded is not None:
            st.session_state.schema_draft_name = loaded.name
            st.session_state.schema_draft_mode = (
                "Raw JSON Schema" if loaded.version == 2 else "Field builder"
            )
            st.session_state.schema_draft_fields = [
                field.model_dump(mode="json") for field in loaded.fields
            ]
            st.session_state.schema_draft_raw = (
                json.dumps(loaded.json_schema, indent=2)
                if loaded.json_schema is not None
                else ""
            )
            st.session_state.schema_draft_revision = (
                st.session_state.get("schema_draft_revision", 0) + 1
            )
            st.rerun()

    st.session_state.setdefault("schema_draft_name", "")
    st.session_state.setdefault("schema_draft_mode", "Field builder")
    st.session_state.setdefault(
        "schema_draft_fields",
        [{"name": "", "description": "", "type": "string"}],
    )
    st.session_state.setdefault("schema_draft_raw", "")
    revision = st.session_state.setdefault("schema_draft_revision", 0)
    name = st.text_input(
        "Schema name",
        value=st.session_state.schema_draft_name,
        key=f"schema_draft_name_editor_{revision}",
    )
    schema_mode = st.selectbox(
        "Schema format",
        ["Field builder", "Raw JSON Schema"],
        index=0 if st.session_state.schema_draft_mode == "Field builder" else 1,
        key=f"schema_draft_mode_editor_{revision}",
        help="Raw mode supports nested objects, arrays, enums, and checkbox booleans.",
    )
    fields = st.session_state.schema_draft_fields
    raw_schema = st.session_state.schema_draft_raw
    if schema_mode == "Field builder":
        fields = st.data_editor(
            fields,
            num_rows="dynamic",
            hide_index=True,
            key=f"schema_fields_editor_{revision}",
            column_config={
                "name": st.column_config.TextColumn("Field name", required=True),
                "description": st.column_config.TextColumn("Description"),
                "type": st.column_config.SelectboxColumn(
                    "Type",
                    options=["string", "number", "integer", "boolean", "date"],
                    required=True,
                ),
            },
        )
    else:
        raw_schema = st.text_area(
            "JSON Schema",
            value=raw_schema,
            height=360,
            key=f"schema_raw_editor_{revision}",
            help=(
                "Use the strict extraction subset: closed objects, every property "
                "required, and nullable values where the document may omit a field."
            ),
        )
    st.session_state.schema_draft_name = name
    st.session_state.schema_draft_mode = schema_mode
    st.session_state.schema_draft_fields = fields
    st.session_state.schema_draft_raw = raw_schema

    imported = st.file_uploader(
        "Import schema JSON", type=["json"], key="schema_import", max_upload_size=1
    )
    imported_fields = st.file_uploader(
        "Import schema Markdown, CSV, or XLSX",
        type=["md", "csv", "xlsx"],
        key="schema_field_import",
        max_upload_size=1,
    )
    actions = st.columns(3)
    if actions[0].button("Save schema", type="primary"):
        try:
            schema = (
                StoredSchema(
                    name=name.strip(),
                    fields=[SchemaField.model_validate(field) for field in fields],
                )
                if schema_mode == "Field builder"
                else StoredSchema(
                    version=2,
                    name=name.strip(),
                    json_schema=json.loads(raw_schema),
                )
            )
            compile_json_schema(schema)
        except (json.JSONDecodeError, ValueError) as exc:
            st.error(f"Schema is incomplete: {exc}")
        else:
            schema_store.save(schema)
            st.session_state.routed_extraction_result = None
            st.toast(f"Saved schema {schema.name}")
            st.rerun()
    if actions[1].button("Load example"):
        if schema_mode == "Raw JSON Schema":
            st.session_state.schema_draft_name = "Provider participation"
            st.session_state.schema_draft_raw = json.dumps(
                {
                    "type": "object",
                    "properties": {
                        "servicing_facility": {
                            "type": ["object", "null"],
                            "properties": {
                                "participating": {"type": ["boolean", "null"]},
                                "nonparticipating": {"type": ["boolean", "null"]},
                            },
                            "required": ["participating", "nonparticipating"],
                            "additionalProperties": False,
                        }
                    },
                    "required": ["servicing_facility"],
                    "additionalProperties": False,
                },
                indent=2,
            )
        else:
            st.session_state.schema_draft_name = "Invoice"
            st.session_state.schema_draft_fields = [
                {"name": "invoice_number", "description": "Official invoice ID", "type": "string"},
                {"name": "total_amount", "description": "Final amount payable", "type": "number"},
                {"name": "due_date", "description": "Payment due date", "type": "date"},
                {"name": "vendor_name", "description": "Issuing company", "type": "string"},
            ]
        st.session_state.schema_draft_revision += 1
        st.rerun()
    if actions[2].button("Clear"):
        st.session_state.schema_draft_name = ""
        st.session_state.schema_draft_fields = []
        st.session_state.schema_draft_raw = ""
        st.session_state.schema_draft_revision += 1
        st.rerun()

    if imported is not None and st.button("Import JSON"):
        try:
            imported_value = json.loads(imported.getvalue())
            if isinstance(imported_value, dict) and "name" in imported_value:
                schema = StoredSchema.model_validate(imported_value)
            else:
                schema = StoredSchema(
                    version=2,
                    name=Path(imported.name).stem.removesuffix(".schema"),
                    json_schema=imported_value,
                )
            compile_json_schema(schema)
        except (json.JSONDecodeError, ValueError) as exc:
            st.error(f"Schema JSON is invalid: {exc}")
        else:
            schema_store.save(schema)
            st.session_state.routed_extraction_result = None
            st.toast(f"Imported schema {schema.name}")
            st.rerun()
    if imported_fields is not None:
        field_bytes = imported_fields.getvalue()
        import_fingerprint = hashlib.sha256(
            imported_fields.name.encode("utf-8") + b"\0" + field_bytes
        ).hexdigest()
    else:
        field_bytes = None
        import_fingerprint = None
    if (
        field_bytes is not None
        and st.session_state.get("schema_field_import_fingerprint")
        != import_fingerprint
    ):
        try:
            schema = (
                parse_markdown_schema(field_bytes, imported_fields.name)
                if Path(imported_fields.name).suffix.casefold() == ".md"
                else parse_tabular_schema(field_bytes, imported_fields.name)
            )
        except ValueError as exc:
            st.error(f"Schema file is invalid: {exc}")
        else:
            st.session_state.schema_field_import_fingerprint = import_fingerprint
            st.session_state.pending_schema_draft = {
                "name": schema.name,
                "mode": "Field builder",
                "fields": [
                    field.model_dump(mode="json") for field in schema.fields
                ],
            }
            st.toast(f"Loaded schema {schema.name}")
            st.rerun()
    draft = None
    if name.strip() and (fields if schema_mode == "Field builder" else raw_schema.strip()):
        try:
            draft = (
                StoredSchema(
                    name=name.strip(),
                    fields=[SchemaField.model_validate(field) for field in fields],
                )
                if schema_mode == "Field builder"
                else StoredSchema(
                    version=2,
                    name=name.strip(),
                    json_schema=json.loads(raw_schema),
                )
            )
            compile_json_schema(draft)
        except (json.JSONDecodeError, ValueError):
            draft = None
        if draft is not None:
            st.download_button(
                "Export schema JSON",
                draft.model_dump_json(indent=2),
                file_name=f"{draft.name}.schema.json",
                mime="application/json",
                on_click="ignore",
            )
    return draft


def _profile_rows(profile: ClassifierProfile) -> list[dict]:
    return [
        {
            "key": category.key,
            "description": category.description,
            "extract": category.extract,
            "schema_name": category.schema_name or "",
        }
        for category in profile.categories
    ]


def _profile_from_draft(name: str, instructions: str, rows: list[dict]) -> ClassifierProfile:
    categories = []
    for row in rows:
        if not any(
            str(row.get(key) or "").strip()
            for key in ("key", "description", "schema_name")
        ) and not bool(row.get("extract")):
            continue
        schema_name = str(row.get("schema_name") or "").strip() or None
        categories.append(
            ClassifierCategory(
                key=str(row.get("key") or "").strip(),
                description=str(row.get("description") or "").strip(),
                extract=bool(row.get("extract")),
                schema_name=schema_name,
            )
        )
    return ClassifierProfile(
        name=name.strip(),
        instructions=instructions.strip(),
        categories=categories,
    )


def _missing_profile_schemas(profile: ClassifierProfile) -> list[str]:
    available = {schema.name.casefold() for schema in schema_store.list()}
    return sorted(
        {
            category.schema_name
            for category in profile.categories
            if category.extract
            and category.schema_name
            and category.schema_name.casefold() not in available
        }
    )


def render_classifier_profile_builder() -> ClassifierProfile | None:
    pending = st.session_state.pop("pending_classifier_profile", None)
    if pending is not None:
        st.session_state.classifier_draft_name = pending.name
        st.session_state.classifier_draft_instructions = pending.instructions
        st.session_state.classifier_draft_categories = _profile_rows(pending)
        st.session_state.classifier_draft_revision = (
            st.session_state.get("classifier_draft_revision", 0) + 1
        )

    profiles = classifier_profile_store.list()
    profile_names = [profile.name for profile in profiles]
    selected = st.selectbox(
        "Saved routing profile",
        ["New routing profile", *profile_names],
        key="classifier_profile_selection",
    )
    if selected != "New routing profile" and st.button("Load routing profile"):
        loaded = classifier_profile_store.get(selected)
        if loaded is not None:
            st.session_state.pending_classifier_profile = loaded
            st.rerun()

    st.session_state.setdefault("classifier_draft_name", "")
    st.session_state.setdefault("classifier_draft_instructions", "")
    st.session_state.setdefault(
        "classifier_draft_categories",
        [{"key": "", "description": "", "extract": False, "schema_name": ""}],
    )
    revision = st.session_state.setdefault("classifier_draft_revision", 0)
    name = st.text_input(
        "Routing profile name",
        value=st.session_state.classifier_draft_name,
        key=f"classifier_name_{revision}",
    )
    instructions = st.text_area(
        "Optional routing instructions",
        value=st.session_state.classifier_draft_instructions,
        key=f"classifier_instructions_{revision}",
        placeholder="Example: Treat fax cover sheets as part of the following form.",
    )
    schema_names = [schema.name for schema in schema_store.list()]
    categories = st.data_editor(
        st.session_state.classifier_draft_categories,
        num_rows="dynamic",
        hide_index=True,
        key=f"classifier_categories_{revision}",
        column_config={
            "key": st.column_config.TextColumn("Category", required=True),
            "description": st.column_config.TextColumn("Description", required=True),
            "extract": st.column_config.CheckboxColumn("Extract"),
            "schema_name": st.column_config.SelectboxColumn(
                "Extraction schema", options=["", *schema_names]
            ),
        },
    )
    st.session_state.classifier_draft_name = name
    st.session_state.classifier_draft_instructions = instructions
    st.session_state.classifier_draft_categories = categories
    st.caption("`other` is always included as a non-extractable fallback category.")

    imported_json = st.file_uploader(
        "Import routing profile JSON", type=["json"], key="classifier_json_import"
    )
    imported_markdown = st.file_uploader(
        "Import routing profile Markdown",
        type=["md"],
        key="classifier_markdown_import",
        max_upload_size=1,
    )
    actions = st.columns(3)
    if actions[0].button("Save routing profile", type="primary"):
        try:
            profile = _profile_from_draft(name, instructions, categories)
            missing = _missing_profile_schemas(profile)
            if missing:
                raise ValueError(f"missing saved extraction schemas: {', '.join(missing)}")
        except ValueError as exc:
            st.error(f"Routing profile is incomplete: {exc}")
        else:
            classifier_profile_store.save(profile)
            st.toast(f"Saved routing profile {profile.name}")
            st.rerun()
    if actions[1].button("Load routing example"):
        default_schema = "New Authorization" if "New Authorization" in schema_names else ""
        st.session_state.pending_classifier_profile = ClassifierProfile(
            name="Medical fax routing",
            instructions="Treat fax cover sheets as part of the following form.",
            categories=[
                ClassifierCategory(
                    key="newauth",
                    description="Initial request for a new authorization",
                    extract=bool(default_schema),
                    schema_name=default_schema or None,
                ),
                ClassifierCategory(
                    key="authupdate",
                    description="Update to an existing authorization",
                ),
                ClassifierCategory(
                    key="medical_records",
                    description="Medical records without an authorization request",
                ),
            ],
        )
        st.rerun()
    if actions[2].button("Clear routing profile"):
        st.session_state.pending_classifier_profile = ClassifierProfile(
            name="New profile",
            categories=[ClassifierCategory(key="category", description="Describe category")],
        )
        st.rerun()

    if imported_json is not None and st.button("Import routing JSON"):
        try:
            profile = ClassifierProfile.model_validate_json(imported_json.getvalue())
            missing = _missing_profile_schemas(profile)
            if missing:
                raise ValueError(f"missing saved extraction schemas: {', '.join(missing)}")
        except ValueError as exc:
            st.error(f"Routing profile JSON is invalid: {exc}")
        else:
            classifier_profile_store.save(profile)
            st.toast(f"Imported routing profile {profile.name}")
            st.rerun()

    if imported_markdown is not None:
        markdown_bytes = imported_markdown.getvalue()
        fingerprint = hashlib.sha256(
            imported_markdown.name.encode("utf-8") + b"\0" + markdown_bytes
        ).hexdigest()
        if st.session_state.get("classifier_markdown_fingerprint") != fingerprint:
            try:
                profile = parse_markdown_classifier_profile(
                    markdown_bytes, imported_markdown.name
                )
            except ValueError as exc:
                st.error(f"Routing profile Markdown is invalid: {exc}")
            else:
                st.session_state.classifier_markdown_fingerprint = fingerprint
                st.session_state.pending_classifier_profile = profile
                st.toast(f"Loaded routing profile {profile.name}")
                st.rerun()

    try:
        draft = _profile_from_draft(name, instructions, categories)
    except ValueError:
        return None
    missing = _missing_profile_schemas(draft)
    if missing:
        st.warning(f"Missing saved extraction schemas: {', '.join(missing)}")
        return None
    st.download_button(
        "Export routing profile JSON",
        draft.model_dump_json(indent=2),
        file_name=f"{draft.name}.routing.json",
        mime="application/json",
        on_click="ignore",
    )
    return draft


def _classification_rows(classification: FormClassificationResult) -> list[dict]:
    return [
        {
            "id": segment.id,
            "start_page": segment.start_page,
            "end_page": segment.end_page,
            "category": segment.category,
            "confidence": segment.confidence,
            "reasoning": segment.reasoning,
            "approved": segment.approved,
            "eligible": segment.eligible,
            "schema_name": segment.schema_name or "",
        }
        for segment in classification.segments
    ]


def _apply_routing_review(
    classification: FormClassificationResult,
    rows: list[dict],
    page_count: int,
) -> FormClassificationResult:
    category_by_key = {
        category.key: category for category in classification.profile.categories
    }
    original_by_id = {segment.id: segment for segment in classification.segments}
    segments: list[FormSegment] = []
    for index, row in enumerate(rows, start=1):
        start_page = int(row["start_page"])
        end_page = int(row["end_page"])
        category_key = str(row["category"])
        if category_key != "other" and category_key not in category_by_key:
            raise ValueError(f"unknown category {category_key!r}")
        if not 1 <= start_page <= end_page <= page_count:
            raise ValueError(f"invalid page range {start_page}-{end_page}")
        segment_id = str(row.get("id") or f"form-{index:03d}")
        original = original_by_id.get(segment_id)
        changed = original is None or (
            start_page,
            end_page,
            category_key,
        ) != (original.start_page, original.end_page, original.category)
        approved = bool(row.get("approved"))
        category = category_by_key.get(category_key)
        eligible = bool(category and category.extract)
        if approved:
            review_status = (
                "user_corrected"
                if changed
                else "auto_approved"
                if original and original.review_status == "auto_approved"
                else "user_confirmed"
            )
        else:
            review_status = "needs_review"
        segments.append(
            FormSegment(
                id=segment_id,
                predicted_start_page=(
                    original.predicted_start_page if original else start_page
                ),
                predicted_end_page=original.predicted_end_page if original else end_page,
                predicted_category=(
                    original.predicted_category if original else category_key
                ),
                start_page=start_page,
                end_page=end_page,
                category=category_key,
                confidence=(
                    original.confidence
                    if original
                    else float(row.get("confidence") or 0)
                ),
                reasoning=original.reasoning if original else "User-created segment",
                evidence_element_ids=(original.evidence_element_ids if original else []),
                approved=approved,
                review_status=review_status,
                eligible=eligible,
                schema_name=category.schema_name if eligible else None,
            )
        )
    segments.sort(key=lambda item: (item.start_page, item.end_page))
    covered = [
        page
        for segment in segments
        for page in range(segment.start_page, segment.end_page + 1)
    ]
    if covered != list(range(1, page_count + 1)):
        raise ValueError("segments must cover every page exactly once without gaps")
    for index, segment in enumerate(segments, start=1):
        segment.id = f"form-{index:03d}"
    return classification.model_copy(update={"segments": segments}, deep=True)


st.set_page_config(
    page_title="Document Parse Studio",
    page_icon=":material/document_scanner:",
    layout="wide",
)

if st.session_state.get("result_version") != RESULT_VERSION:
    reset_document_state(clear_session_usage=True)
    st.session_state.batch_workspaces = {}
    st.session_state.active_document_id = None
    st.session_state.pop("batch_document_selector", None)
st.session_state.result_version = RESULT_VERSION
initialize_ade_mode()
st.session_state.setdefault("session_usage", RunUsage())
st.session_state.setdefault("batch_workspaces", {})
st.session_state.setdefault("active_document_id", None)
st.session_state.setdefault("workspace_upload_revision", 0)
if not st.session_state.get("durable_workspace_loaded"):
    try:
        durable_workspace = workspace_store.load(result_version=RESULT_VERSION)
    except Exception as exc:  # noqa: BLE001 - corrupt local state must not block startup
        durable_workspace = None
        st.session_state.workspace_restore_error = (
            f"Could not restore the saved workspace: {type(exc).__name__}: {exc}"
        )
    if durable_workspace is not None:
        for key, value in durable_workspace.settings.items():
            if key in WORKSPACE_SETTING_KEYS:
                st.session_state[key] = value
        st.session_state.session_usage = durable_workspace.usage
        st.session_state.restored_batch_documents = [
            item.document for item in durable_workspace.documents
        ]
        st.session_state.batch_workspaces = {
            item.document.id: {
                "status": item.status,
                "error": item.error,
                "processing_type": processing_type_from_selection_key(
                    item.selection_key
                ),
                "selection_key": item.selection_key,
                "progress": item.progress,
                "state": {
                    **default_document_state(),
                    "result": item.result,
                    "result_source_hash": item.selection_key,
                    "parsed_source": item.parsed_source,
                    "agentic_analysis": item.analysis,
                    "agentic_source_hash": item.analysis_key,
                    "native_extraction_result": item.extraction,
                },
            }
            for item in durable_workspace.documents
        }
        first_document_id = durable_workspace.documents[0].document.id
        st.session_state.active_document_id = first_document_id
        st.session_state.batch_document_selector = first_document_id
        load_workspace(first_document_id)
        st.session_state.workspace_restored_at = durable_workspace.updated_at
    st.session_state.durable_workspace_loaded = True
app_view = st.sidebar.segmented_control(
    "View",
    ("Studio", "Session cost"),
    default="Studio",
    key="app-view",
)
if app_view == "Session cost":
    render_session_cost_page()
    st.stop()
st.session_state.setdefault("extraction_engine", ExtractionEngine.PADDLE_VLLM.value)
st.session_state.setdefault("active_extraction_engine", None)
st.session_state.setdefault("cloud_model", CloudModel.GPT_5_6_LUNA.value)
st.session_state.setdefault("cloud_model_label", CloudModel.GPT_5_6_LUNA.label)
st.session_state.setdefault("ollama_model", OllamaOcrModel.GLM_OCR.value)
if st.session_state.active_extraction_engine is None:
    apply_engine_selection()
selected_extraction_engine = ExtractionEngine(st.session_state.extraction_engine)
for engine in ExtractionEngine:
    st.session_state.setdefault(
        f"engine-toggle-{engine.value}", engine is selected_extraction_engine
    )
default_ocr_engine = (
    selected_extraction_engine.parser_ocr_engine or OcrEngine.PADDLEOCR_VL_1_6
)
st.session_state.setdefault("ocr_engine_label", default_ocr_engine.label)
ocr_engines = {engine.label: engine for engine in OcrEngine}
selected_ocr_engine = ocr_engines.get(
    st.session_state.ocr_engine_label, default_ocr_engine
)
available_alternate_ocr_engines = [
    engine
    for engine in AlternateOcrEngine
    if not engine.matches_primary(selected_ocr_engine, st.session_state.ollama_model)
]
default_alternate = default_alternate_ocr_engine(
    selected_ocr_engine, st.session_state.ollama_model
)
available_alternate_values = {engine.value for engine in available_alternate_ocr_engines}
if st.session_state.get("ocr_disagreement_engine") not in available_alternate_values:
    st.session_state.ocr_disagreement_engine = default_alternate.value

preload_error = st.session_state.get("engine_switch_error")

selected_cloud_model = next(model for model in CloudModel if model.label == st.session_state.cloud_model_label)
has_environment = bool(os.getenv(selected_cloud_model.api_key_name))
header_title, header_status = st.columns([4, 1], vertical_alignment="center")
with header_title:
    st.title("Document Parse Studio")
    st.caption(f"Powered by {selected_extraction_engine.label} + {selected_cloud_model.label}")

initial_status = "Ready" if preload_error is None else "Not ready"
initial_color = "green" if initial_status == "Ready" else "red"
header_status_slot = header_status.empty()
header_status_slot.markdown(f"Status: :{initial_color}[● **{initial_status}**]")
session_usage_slot = st.container()

if not has_environment:
    st.warning(
        f"{selected_cloud_model.api_key_name} is not set. Local parsing remains "
        "available; AI extraction and enhancement will be skipped."
    )
elif selected_cloud_model is CloudModel.GPT_5_6_LUNA and not os.getenv("OPENAI_BASE_URL"):
    st.caption("Luna destination: OpenAI default endpoint")
if preload_error is not None:
    st.error(preload_error)
if st.session_state.get("workspace_restore_error"):
    st.error(st.session_state.workspace_restore_error)

with st.sidebar:
    st.subheader("Upload documents")
    uploaded_files = st.file_uploader(
        "Documents",
        type=SUPPORTED_TYPES,
        accept_multiple_files=True,
        max_upload_size=250,
        label_visibility="collapsed",
        key=f"documents-upload-{st.session_state.workspace_upload_revision}",
    )
    restored_documents = st.session_state.get("restored_batch_documents", [])
    if restored_documents and not uploaded_files:
        st.caption(f"Restored {len(restored_documents)} document(s) from local storage.")
    confirm_clear_workspace = st.checkbox(
        "Confirm clearing saved workspace",
        key="confirm_clear_workspace",
        disabled=not bool(restored_documents),
    )
    if st.button(
        "Clear saved workspace",
        disabled=not (restored_documents and confirm_clear_workspace),
        icon=":material/delete:",
    ):
        workspace_store.clear()
        st.session_state.restored_batch_documents = []
        st.session_state.batch_workspaces = {}
        st.session_state.active_document_id = None
        st.session_state.pop("batch_document_selector", None)
        st.session_state.workspace_upload_revision += 1
        reset_document_state(clear_session_usage=True)
        st.rerun()

batch_error: str | None = None
try:
    batch_documents = (
        build_batch_documents(
            [
                (
                    item.name,
                    item.getvalue(),
                    item.type or "application/octet-stream",
                )
                for item in uploaded_files
            ]
        )
        if uploaded_files
        else list(st.session_state.get("restored_batch_documents", []))
    )
except ValueError as exc:
    batch_documents = []
    batch_error = str(exc)

document_ids = [document.id for document in batch_documents]
previous_ids = list(st.session_state.batch_workspaces)
if batch_error is None and document_ids != previous_ids:
    save_active_workspace()
    existing_workspaces = st.session_state.batch_workspaces
    st.session_state.batch_workspaces = {
        document.id: existing_workspaces.get(
            document.id,
            {
                "status": "pending",
                "error": None,
                "processing_type": None,
                "selection_key": None,
                "progress": None,
                "state": default_document_state(),
            },
        )
        for document in batch_documents
    }
    for workspace in st.session_state.batch_workspaces.values():
        workspace.setdefault("processing_type", None)
    try:
        workspace_store.sync_documents(
            batch_documents,
            settings=workspace_settings(),
            result_version=RESULT_VERSION,
        )
    except Exception as exc:  # noqa: BLE001 - persistence failure is user-facing
        batch_error = f"Could not save the batch workspace: {type(exc).__name__}: {exc}"
    else:
        st.session_state.restored_batch_documents = list(batch_documents)
    previous_active_id = st.session_state.get("active_document_id")
    active_document_id = (
        previous_active_id
        if previous_active_id in st.session_state.batch_workspaces
        else (document_ids[0] if document_ids else None)
    )
    st.session_state.active_document_id = active_document_id
    st.session_state.batch_document_selector = active_document_id
    if active_document_id != previous_active_id:
        load_workspace(active_document_id)
        for key in ("range_start", "range_end", "thumbnail_group"):
            st.session_state.pop(key, None)

documents_by_id = {document.id: document for document in batch_documents}
active_document = documents_by_id.get(st.session_state.active_document_id)
if len(batch_documents) > 1:
    document_option_labels = {
        document.id: document.display_name
        for document in batch_documents
    }
    with st.sidebar:
        st.selectbox(
            "Document results",
            document_ids,
            key="batch_document_selector",
            format_func=document_option_labels.__getitem__,
            on_change=switch_active_document,
        )

processing_types: dict[str, ProcessingType] = {}
page_routes_by_document: dict[str, dict[int, PageRoute]] = {}
processing_errors: list[str] = []
if batch_documents:
    with st.sidebar:
        st.subheader("Processing types")
        for document in batch_documents:
            options = processing_labels_for(document.suffix)
            selector_key = f"processing-type-{document.id}"
            previous_value = st.session_state.batch_workspaces[document.id].get(
                "processing_type"
            )
            previous = next(
                (
                    label
                    for label, value in PROCESSING_LABELS.items()
                    if value.value == previous_value and label in options
                ),
                None,
            )
            if selector_key not in st.session_state:
                st.session_state[selector_key] = previous
            selected_label = st.selectbox(
                f"Processing type · {document.display_name}",
                options,
                index=None,
                placeholder="Select processing type",
                key=selector_key,
            )
            selected_type = (
                PROCESSING_LABELS[selected_label] if selected_label is not None else None
            )
            st.session_state.batch_workspaces[document.id]["processing_type"] = (
                selected_type.value if selected_type is not None else None
            )
            if selected_type is None:
                continue
            processing_types[document.id] = selected_type
            if selected_type is not ProcessingType.MIXED_PDF:
                continue
            try:
                inspection = cached_pdf_inspection(document.source)
            except Exception as exc:  # noqa: BLE001 - preflight is user-facing
                processing_errors.append(
                    f"{document.display_name}: PDF inspection failed: {exc}"
                )
                continue
            if inspection.pdf_type != "mixed":
                processing_errors.append(
                    f"{document.display_name}: selected Mixed PDF, but pdf-inspector "
                    f"classified it as {inspection.pdf_type}"
                )
                continue
            restored_routes = page_routes_from_selection_key(
                st.session_state.batch_workspaces[document.id].get("selection_key")
            )
            st.caption(f"{document.display_name} page routes")
            review = st.data_editor(
                [
                    {
                        "Page": page,
                        "Suggested": (
                            "OCR"
                            if page in inspection.pages_needing_ocr
                            else "Native"
                        ),
                        "User selection": (
                            "OCR"
                            if restored_routes.get(page)
                            is PageRoute.OCR
                            else "Native"
                            if restored_routes.get(page)
                            is PageRoute.NATIVE
                            else (
                                "OCR"
                                if page in inspection.pages_needing_ocr
                                else "Native"
                            )
                        ),
                    }
                    for page in range(1, inspection.page_count + 1)
                ],
                column_config={
                    "Page": st.column_config.NumberColumn("Page", disabled=True),
                    "Suggested": st.column_config.TextColumn(
                        "Suggested", disabled=True
                    ),
                    "User selection": st.column_config.SelectboxColumn(
                        "User selection",
                        options=["Native", "OCR"],
                        required=True,
                    ),
                },
                disabled=["Page", "Suggested"],
                hide_index=True,
                key=f"page-route-review-{document.id}",
            )
            routes = {
                int(row["Page"]): (
                    PageRoute.NATIVE
                    if row["User selection"] == "Native"
                    else PageRoute.OCR
                )
                for row in review
                if row.get("User selection") in {"Native", "OCR"}
            }
            confirmed = st.checkbox(
                "Confirm page routes",
                value=bool(restored_routes),
                key=f"page-route-confirmed-{document.id}",
            )
            if len(routes) != inspection.page_count:
                processing_errors.append(
                    f"{document.display_name}: select a route for every page"
                )
            elif not confirmed:
                processing_errors.append(
                    f"{document.display_name}: confirm the reviewed page routes"
                )
            else:
                page_routes_by_document[document.id] = routes

upload = active_document
source = active_document.source if active_document is not None else None
source_hash = active_document.content_sha256 if active_document is not None else None
suffix = active_document.suffix if active_document is not None else ""

if batch_error is not None:
    st.error(batch_error)
for error in processing_errors:
    st.error(error)
processing_ready = bool(batch_documents) and (
    len(processing_types) == len(batch_documents) and not processing_errors
)

if source is not None and suffix == ".pdf" and len(batch_documents) == 1:
    try:
        total_source_pages = pdf_page_count(source)
    except Exception:  # noqa: BLE001 - parsing reports malformed input per document
        total_source_pages = 1
else:
    total_source_pages = 1

with st.sidebar:
    st.subheader("Options")
    with st.container(border=True):
        st.caption("Document extraction engine — one active at a time")
        for engine in ExtractionEngine:
            st.toggle(
                engine.label,
                key=f"engine-toggle-{engine.value}",
                on_change=toggle_extraction_engine,
                args=(engine.value,),
            )
    selected_extraction_engine = ExtractionEngine(st.session_state.extraction_engine)
    selected_ocr_engine = (
        selected_extraction_engine.parser_ocr_engine or OcrEngine.PADDLEOCR_VL_1_6
    )
    st.session_state.ocr_engine_label = selected_ocr_engine.label
    if st.session_state.get("engine_switch_error"):
        st.error(f"Engine switch failed; previous engine restored: {st.session_state.engine_switch_error}")
    selected_cloud_model = st.selectbox(
        "AI model",
        [model.label for model in CloudModel],
        key="cloud_model_label",
    )
    selected_cloud_model = next(model for model in CloudModel if model.label == selected_cloud_model)
    st.session_state.cloud_model = selected_cloud_model.value
    if selected_extraction_engine is ExtractionEngine.OLLAMA:
        selected_ollama_model = st.selectbox(
            "Ollama OCR model",
            [model.value for model in OllamaOcrModel],
            key="ollama_model",
            on_change=change_ollama_model,
        )
    ai_enhancement = st.toggle(
        "AI enhancement for failed or <75% confidence regions",
        value=False,
        disabled=selected_extraction_engine is ExtractionEngine.PURE_AI,
        key="ai_enhancement",
    )
    single_pdf = (
        len(batch_documents) == 1
        and suffix == ".pdf"
        and active_document is not None
        and processing_types.get(active_document.id) is ProcessingType.SCANNED_PDF
    )
    use_page_range = st.checkbox(
        "Page range",
        disabled=not single_pdf,
        help=(
            "Parse one inclusive, contiguous page range. Multiple-file batches "
            "always process every page."
        ),
    )
    use_page_range = bool(use_page_range and single_pdf)
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
    st.selectbox(
        "ADE mode",
        ["Fast", "Full", "Custom"],
        key="ade_mode",
        on_change=apply_ade_preset,
        help="Fast minimizes Luna calls. Full adds refinement and a table of contents.",
    )
    st.toggle(
        "Enhance with gpt-5.6-luna",
        key="refine_markdown",
        on_change=mark_ade_custom,
        help=(
            "Controls final Markdown refinement only. Visual recovery is configured "
            "separately below."
        ),
    )
    st.toggle(
        "Enable visual recovery on hard regions",
        key="visual_recovery",
        disabled=not has_environment,
        help=(
            "Uses medium-effort Luna vision on prioritized hard regions. The budget "
            "scales from 8 to 64 crops by document length, with at most 3 per page; "
            + (
                "local GLM recovery runs first."
                if selected_ocr_engine is OcrEngine.GLM_OCR
                else "PaddleOCR output is used directly before Luna recovery."
            )
        ),
    )
    cross_check_supported = selected_extraction_engine in {
        ExtractionEngine.PADDLE_VLLM,
        ExtractionEngine.GLM_VLLM,
        ExtractionEngine.OLLAMA,
    }
    if not cross_check_supported:
        st.session_state.ocr_disagreement = False
    st.toggle(
        "Cross-check uncertain regions with alternate local OCR",
        key="ocr_disagreement",
        disabled=not cross_check_supported,
        help=(
            "Audits at most 16 uncertain crops (2 per page). Disagreements are "
            "flagged for review; primary OCR text is never replaced."
        ),
    )
    if st.session_state.ocr_disagreement:
        alternate_labels = {
            engine.value: engine.label for engine in available_alternate_ocr_engines
        }
        st.selectbox(
            "Alternate local OCR",
            [engine.value for engine in available_alternate_ocr_engines],
            format_func=alternate_labels.__getitem__,
            key="ocr_disagreement_engine",
            help=(
                "The app batches uncertain crops, temporarily swaps GPU models when "
                "needed, and restores the selected primary engine afterward."
            ),
        )
    st.toggle(
        "Classify document type",
        key="classify_document",
        on_change=mark_ade_custom,
        disabled=not has_environment,
    )
    st.toggle(
        "Generate table of contents",
        key="generate_toc",
        on_change=mark_ade_custom,
        disabled=not has_environment,
    )
    refine_markdown = st.session_state.refine_markdown
    classify_document = st.session_state.classify_document
    generate_toc = st.session_state.generate_toc
    visual_recovery = bool(ai_enhancement and has_environment)
    st.toggle(
        "Enable document chat",
        key="enable_chat",
        disabled=not has_environment,
    )
    enable_chat = st.session_state.enable_chat
    def document_selection_key(document: BatchDocument) -> str:
        page_selection = (
            f"{start_page}:{end_page}"
            if use_page_range and document.id == st.session_state.active_document_id
            else "all"
        )
        processing_type = processing_types.get(document.id)
        routes = page_routes_by_document.get(document.id, {})
        route_key = ",".join(
            f"{page}:{route.value}" for page, route in sorted(routes.items())
        )
        return (
            f"{document.id}:{page_selection}:{refine_markdown}:"
            f"{visual_recovery}:{has_environment}:{selected_extraction_engine.value}:"
            f"{selected_cloud_model.value}:{st.session_state.ollama_model}:"
            f"{st.session_state.ocr_disagreement}:"
            f"{st.session_state.ocr_disagreement_engine}:"
            f"{processing_type.value if processing_type else 'unselected'}:"
            f"{route_key}:{RESULT_VERSION}"
        )

    selection_keys = {
        document.id: document_selection_key(document)
        for document in batch_documents
    }
    selection_key = (
        selection_keys.get(active_document.id) if active_document is not None else None
    )
    save_active_workspace()
    active_was_invalidated = False
    for document in batch_documents:
        workspace = st.session_state.batch_workspaces[document.id]
        previous_selection_key = workspace.get("selection_key")
        if previous_selection_key is not None and previous_selection_key != selection_keys[document.id]:
            workspace.update(
                status="pending",
                error=None,
                selection_key=None,
                progress=None,
                state=default_document_state(),
            )
            workspace_store.save_document(document.id, status="pending")
            active_was_invalidated |= document.id == st.session_state.active_document_id
    if active_was_invalidated:
        load_workspace(st.session_state.active_document_id)
    if batch_error is None and isinstance(st.session_state.session_usage, RunUsage):
        workspace_store.save_workspace(
            settings=workspace_settings(),
            usage=st.session_state.session_usage,
        )

    parse_clicked = st.button(
        (
            "Resume batch"
            if any(
                workspace["status"] == "interrupted"
                for workspace in st.session_state.batch_workspaces.values()
            )
            else (
                "Parse document"
                if len(batch_documents) <= 1
                else f"Process {len(batch_documents)} documents"
            )
        ),
        type="primary",
        icon=":material/document_scanner:",
        disabled=(
            source is None
            or batch_error is not None
            or not processing_ready
            or (
                preload_error is not None
                and selected_ocr_engine is OcrEngine.GLM_OCR
            )
        ),
        width="stretch",
    )

    st.divider()
    st.subheader("Progress")
    expected_agentic_key = (
        f"{selection_key}:{classify_document}:{generate_toc}"
        if selection_key is not None
        else None
    )
    cached_result_matches = bool(
        active_document is not None
        and st.session_state.batch_workspaces[active_document.id]["status"] == "complete"
        and st.session_state.get("result") is not None
        and st.session_state.get("result_source_hash") == selection_key
        and st.session_state.get("agentic_source_hash") == expected_agentic_key
    )
    active_workspace = (
        st.session_state.batch_workspaces.get(active_document.id)
        if active_document is not None
        else None
    )
    retained_progress = active_workspace.get("progress") if active_workspace else None
    retained_fraction = (
        retained_progress.get("current", 0) / max(retained_progress.get("total", 1), 1)
        if retained_progress
        else 0
    )
    retained_text = (
        f"Interrupted at {retained_progress.get('message', retained_progress.get('stage', 'processing'))}; resume the batch"
        if active_workspace
        and active_workspace.get("status") == "interrupted"
        and retained_progress
        else "Waiting for a document"
    )
    progress_bar = st.progress(
        1.0 if cached_result_matches else retained_fraction,
        text="Parsing complete" if cached_result_matches else retained_text,
    )
    stage_log = st.empty()
    stage_log.markdown(
        stage_markdown(
            None,
            {key for key, _label in STAGE_LABELS} if cached_result_matches else set(),
        )
    )
    st.divider()
    managed_shutdown = runtime_control.managed_shutdown_available()
    if st.button(
        "Stop app",
        key="stop-managed-app",
        icon=":material/power_settings_new:",
        disabled=not managed_shutdown,
        help=(
            "Stop this app and its managed background services."
            if managed_shutdown
            else "Available when the app is started with a Windows launcher."
        ),
        width="stretch",
    ):
        confirm_managed_shutdown()

if parse_clicked and batch_documents:
    save_active_workspace()
    documents_to_process = []
    for document in batch_documents:
        workspace = st.session_state.batch_workspaces[document.id]
        expected_selection_key = selection_keys[document.id]
        expected_analysis_key = (
            f"{expected_selection_key}:{classify_document}:{generate_toc}"
        )
        state = workspace["state"]
        if not (
            workspace["status"] == "complete"
            and state.get("result") is not None
            and state.get("result_source_hash") == expected_selection_key
            and state.get("agentic_source_hash") == expected_analysis_key
        ):
            documents_to_process.append(document)

    try:
        if documents_to_process:
            header_status_slot.markdown("Status: :blue[● **Parsing**]")
            requires_ocr = any(
                processing_types[document.id]
                in {ProcessingType.SCANNED_PDF, ProcessingType.IMAGE}
                or (
                    processing_types[document.id] is ProcessingType.MIXED_PDF
                    and PageRoute.OCR
                    in page_routes_by_document.get(document.id, {}).values()
                )
                for document in documents_to_process
            )
            parser_config = replace(
                ParserConfig.from_env(),
                ocr_engine=selected_ocr_engine,
                cloud_model=CloudModel(st.session_state.cloud_model),
                ollama_model=st.session_state.ollama_model,
                local_ocr_enabled=(
                    selected_extraction_engine is not ExtractionEngine.PURE_AI
                ),
                ocr_disagreement_enabled=bool(st.session_state.ocr_disagreement),
                ocr_disagreement_engine=AlternateOcrEngine(
                    st.session_state.ocr_disagreement_engine
                ),
            )
            parser = UniversalDocumentParser(
                parser_config,
                legacy_parser=pipeline.DocumentParser(parser_config),
            )
        else:
            parser = None
    except Exception as exc:  # noqa: BLE001 - provider diagnostics are user-facing
        parser = None
        progress_bar.progress(0, text="OCR service is unavailable")
        header_status_slot.markdown("Status: :red[● **Error**]")
        st.error(f"OCR service startup failed: {type(exc).__name__}: {str(exc)[:1000]}")
    else:
        total_documents = len(batch_documents)
        for document_index, document in enumerate(batch_documents, start=1):
            workspace = st.session_state.batch_workspaces[document.id]
            expected_selection_key = selection_keys[document.id]
            agentic_key = (
                f"{expected_selection_key}:{classify_document}:{generate_toc}"
            )
            state = workspace["state"]
            if (
                workspace["status"] == "complete"
                and state.get("result") is not None
                and state.get("result_source_hash") == expected_selection_key
                and state.get("agentic_source_hash") == agentic_key
            ):
                progress_bar.progress(
                    document_index / total_documents,
                    text=(
                        f"{document_index}/{total_documents} "
                        f"{document.display_name}: already complete"
                    ),
                )
                continue

            initial_progress = {
                "stage": "layout",
                "current": 0,
                "total": 1,
                "message": "Starting document",
            }
            workspace.update(
                status="processing",
                error=None,
                progress=initial_progress,
            )
            workspace_store.save_progress(
                document.id,
                status="processing",
                progress=initial_progress,
            )
            reset_document_state()
            st.session_state.update(state)
            completed_stages: set[str] = set()
            progress_state: dict[str, str | None] = {"active": None}
            parsed_document_source = (
                select_pdf_pages(document.source, start_page, end_page)
                if use_page_range and document.id == st.session_state.active_document_id
                else document.source
            )

            def show_progress(
                event,
                *,
                index=document_index,
                item=document,
                completed_stages=completed_stages,
                progress_state=progress_state,
                workspace=workspace,
            ) -> None:
                stage = event.stage
                if stage == "layout":
                    progress_state["active"] = "layout"
                    document_progress = 0.30 * event.current / max(event.total, 1)
                elif stage == "recognize":
                    completed_stages.add("layout")
                    progress_state["active"] = "recognize"
                    document_progress = (
                        0.30 + 0.42 * event.current / max(event.total, 1)
                    )
                elif stage in {"verify", "delegate", "recover"}:
                    completed_stages.add("layout")
                    progress_state["active"] = "recover"
                    document_progress = 0.76
                elif stage == "assemble":
                    completed_stages.update({"layout", "recognize", "recover"})
                    progress_state["active"] = "assemble"
                    document_progress = 0.82
                elif stage == "annotate":
                    completed_stages.update(
                        {"layout", "recognize", "recover", "assemble"}
                    )
                    progress_state["active"] = "annotate"
                    document_progress = 0.90
                elif stage == "enhance":
                    completed_stages.update(
                        {"layout", "recognize", "recover", "assemble", "annotate"}
                    )
                    progress_state["active"] = "enhance"
                    document_progress = 0.96
                elif stage == "complete":
                    completed_stages.update(key for key, _label in STAGE_LABELS)
                    progress_state["active"] = None
                    document_progress = 1.0
                else:
                    document_progress = None
                if document_progress is not None:
                    overall_progress = (
                        index - 1 + document_progress
                    ) / total_documents
                    progress_bar.progress(
                        overall_progress,
                        text=(
                            f"{index}/{total_documents} {item.display_name}: "
                            f"{event.message}"
                        ),
                    )
                    durable_progress = {
                        "stage": stage,
                        "current": event.current,
                        "total": event.total,
                        "message": event.message,
                    }
                    workspace["progress"] = durable_progress
                    workspace_store.save_progress(
                        item.id,
                        status="processing",
                        progress=durable_progress,
                    )
                stage_log.markdown(
                    stage_markdown(progress_state["active"], completed_stages)
                )

            try:
                result = (
                    st.session_state.get("result")
                    if st.session_state.get("result_source_hash")
                    == expected_selection_key
                    else None
                )
                if result is None:
                    if parser is None:
                        raise RuntimeError("OCR parser did not start")
                    if selected_extraction_engine is ExtractionEngine.DOCLING_RAPIDOCR:
                        result = DoclingNativeParser(
                            parser_config,
                            converter=make_docling_rapidocr_converter(),
                        ).parse(
                            parsed_document_source,
                            document.name,
                            source_format=detect_source_format(parsed_document_source, document.name),
                            processing_type=processing_types[document.id],
                        )
                    else:
                        effective_processing_type = (
                            ProcessingType.NATIVE_PDF
                            if selected_extraction_engine is ExtractionEngine.PDF_INSPECTOR
                            else processing_types[document.id]
                        )
                        result = parser.parse(
                            parsed_document_source,
                            document.name,
                            progress_callback=show_progress,
                            processing_type=effective_processing_type,
                            page_routes=page_routes_by_document.get(document.id),
                            refine_markdown=refine_markdown,
                            visual_recovery=visual_recovery,
                        )
                    st.session_state.result = result
                    append_session_usage(result.usage)
                    st.session_state.result_source_hash = expected_selection_key
                    st.session_state.parsed_source = parsed_document_source
                    st.session_state.selected_element_id = None
                    st.session_state.annotated_page = 1
                    st.session_state.extraction_result = None
                    st.session_state.native_extraction_result = None
                    st.session_state.chat_history = []
                    st.session_state.prepared_agentic_context = (
                        None
                        if isinstance(result, NativeParseResult)
                        else DocumentAgent.prepare(result)
                    )
                    workspace["state"] = capture_document_state()
                    workspace_store.save_document(
                        document.id,
                        status="processing",
                        selection_key=expected_selection_key,
                        parsed_source=parsed_document_source,
                        result=result,
                        progress=workspace.get("progress"),
                    )

                prepared_context = st.session_state.get("prepared_agentic_context")
                if prepared_context is None and not isinstance(
                    result, NativeParseResult
                ):
                    prepared_context = DocumentAgent.prepare(result)
                    st.session_state.prepared_agentic_context = prepared_context

                if isinstance(result, NativeParseResult):
                    st.session_state.agentic_analysis = None
                    st.session_state.agentic_source_hash = agentic_key
                elif st.session_state.get("agentic_source_hash") != agentic_key:
                    completed_stages.update(
                        {
                            "layout",
                            "recognize",
                            "recover",
                            "assemble",
                            "annotate",
                            "enhance",
                        }
                    )
                    progress_state["active"] = "classify"
                    analysis_progress = {
                        "stage": "classify",
                        "current": 0,
                        "total": 1,
                        "message": "Running Luna document analysis",
                    }
                    workspace["progress"] = analysis_progress
                    workspace_store.save_progress(
                        document.id,
                        status="processing",
                        progress=analysis_progress,
                    )
                    progress_bar.progress(
                        (document_index - 0.03) / total_documents,
                        text=(
                            f"{document_index}/{total_documents} "
                            f"{document.display_name}: running Luna document analysis"
                        ),
                    )
                    stage_log.markdown(
                        stage_markdown(progress_state["active"], completed_stages)
                    )
                    analysis = DocumentAgent().analyze(
                        result,
                        classify=classify_document,
                        generate_toc=generate_toc,
                        prepared_context=prepared_context,
                    )
                    st.session_state.agentic_analysis = analysis
                    append_session_usage(analysis.usage)
                    st.session_state.agentic_source_hash = agentic_key

                workspace.update(
                    status="complete",
                    error=None,
                    selection_key=expected_selection_key,
                    progress={
                        "stage": "complete",
                        "current": 1,
                        "total": 1,
                        "message": "Parsing complete",
                    },
                    state=capture_document_state(),
                )
                workspace_store.save_document(
                    document.id,
                    status="complete",
                    selection_key=expected_selection_key,
                    analysis_key=agentic_key,
                    progress=workspace["progress"],
                    parsed_source=st.session_state.parsed_source,
                    result=st.session_state.result,
                    analysis=st.session_state.agentic_analysis,
                    extraction=st.session_state.get("native_extraction_result"),
                )
                workspace_store.save_workspace(
                    settings=workspace_settings(),
                    usage=st.session_state.session_usage,
                )
                progress_bar.progress(
                    document_index / total_documents,
                    text=(
                        f"{document_index}/{total_documents} "
                        f"{document.display_name}: complete"
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - isolate per-document failures
                error = f"{type(exc).__name__}: {str(exc)[:1000]}"
                workspace.update(
                    status="failed",
                    error=error,
                    selection_key=expected_selection_key,
                    progress=workspace.get("progress"),
                    state=capture_document_state(),
                )
                workspace_store.save_document(
                    document.id,
                    status="failed",
                    error=error,
                    selection_key=expected_selection_key,
                    analysis_key=st.session_state.get("agentic_source_hash"),
                    progress=workspace.get("progress"),
                    parsed_source=st.session_state.get("parsed_source"),
                    result=st.session_state.get("result"),
                    analysis=st.session_state.get("agentic_analysis"),
                    extraction=st.session_state.get("native_extraction_result"),
                )
                workspace_store.save_workspace(
                    settings=workspace_settings(),
                    usage=st.session_state.session_usage,
                )
                progress_bar.progress(
                    document_index / total_documents,
                    text=(
                        f"{document_index}/{total_documents} "
                        f"{document.display_name}: failed"
                    ),
                )

        load_workspace(st.session_state.active_document_id)
        statuses = [workspace["status"] for workspace in st.session_state.batch_workspaces.values()]
        failed_count = statuses.count("failed")
        if failed_count == 0:
            stage_log.markdown(stage_markdown(None, {key for key, _ in STAGE_LABELS}))
            header_status_slot.markdown("Status: :green[● **Complete**]")
        elif failed_count < len(statuses):
            header_status_slot.markdown("Status: :orange[● **Partial**]")
            st.warning(
                f"{failed_count} of {len(statuses)} documents failed. "
                "Completed documents were kept; run the batch again to retry failures."
            )
        else:
            header_status_slot.markdown("Status: :red[● **Error**]")
            st.error("Every document failed. Run the batch again after resolving the errors.")

if batch_documents:
    with st.sidebar, st.expander("Batch status", expanded=len(batch_documents) > 1):
        st.dataframe(
            [
                {
                    "File": document.display_name,
                    "Status": st.session_state.batch_workspaces[document.id]["status"],
                    "Progress": (
                        (
                            st.session_state.batch_workspaces[document.id].get("progress")
                            or {}
                        ).get("message", "")
                    ),
                    "Error": st.session_state.batch_workspaces[document.id]["error"]
                    or "",
                }
                for document in batch_documents
            ],
            hide_index=True,
            width="stretch",
        )

result = st.session_state.get("result")
parsed_source = st.session_state.get("parsed_source")
analysis = st.session_state.get("agentic_analysis")
extraction_result = st.session_state.get("extraction_result")
custom_classification = st.session_state.get("custom_classification")
routed_extraction_result = st.session_state.get("routed_extraction_result")
has_result = (
    result is not None
    and parsed_source is not None
    and st.session_state.get("result_source_hash") == selection_key
    and not isinstance(result, NativeParseResult)
)
has_native_result = (
    isinstance(result, NativeParseResult)
    and parsed_source is not None
    and st.session_state.get("result_source_hash") == selection_key
)
if has_native_result:
    header_status_slot.markdown("Status: :green[● **Complete**]")
    native_tab_labels = ["Overview", "Markdown", "HTML View"]
    if result.annotated_pdf is not None:
        native_tab_labels.append("Annotated PDF")
    native_tab_labels.extend(["Extract", "JSON", "Source Structure"])
    native_tabs = st.tabs(
        native_tab_labels,
        key="native_studio_tab",
        on_change="rerun",
    )
    native_tab_by_name = dict(zip(native_tab_labels, native_tabs, strict=True))
    with native_tab_by_name["Overview"]:
        native_count = sum(
            unit.effective_route is PageRoute.NATIVE
            for unit in result.document.units
        )
        ocr_count = len(result.document.units) - native_count
        unit_label = "Pages" if result.document.source_format.value == "pdf" else "Source units"
        st.metric(unit_label, len(result.document.units))
        st.caption(f"Native units: {native_count} · OCR units: {ocr_count}")
        if result.document.assets:
            st.caption(
                f"Embedded images: {len(result.document.assets)} · OCR performed: no"
            )
        for warning in result.document.warnings:
            st.warning(warning)
    with native_tab_by_name["Markdown"]:
        st.markdown(result.markdown)
    with native_tab_by_name["HTML View"]:
        render_grounded_html_preview(
            result.markdown,
            key="grounded-html-preview-native",
        )
    if "Annotated PDF" in native_tab_by_name:
        with native_tab_by_name["Annotated PDF"]:
            st.pdf(result.annotated_pdf, height=900)
    with native_tab_by_name["Extract"]:
        native_schema = render_schema_builder()
        if st.button(
            "Run grounded extraction",
            type="primary",
            disabled=native_schema is None,
        ):
            try:
                with st.spinner("Extracting exact values from immutable source text"):
                    native_extraction = LangExtractNativeExtractor().extract(
                        result, native_schema
                    )
            except Exception as exc:  # noqa: BLE001 - present provider errors in UI
                st.error(f"Extraction failed: {type(exc).__name__}: {exc}")
            else:
                st.session_state.native_extraction_result = native_extraction
                append_session_usage(native_extraction.usage)
                save_active_workspace()
                if active_document is not None:
                    active_state = st.session_state.batch_workspaces[
                        active_document.id
                    ]
                    workspace_store.save_document(
                        active_document.id,
                        status=active_state["status"],
                        selection_key=active_state.get("selection_key"),
                        parsed_source=parsed_source,
                        result=result,
                        extraction=native_extraction,
                    )
                st.rerun()
        native_extraction = st.session_state.get("native_extraction_result")
        if native_extraction is not None:
            st.json(native_extraction.data)
            st.dataframe(
                [
                    {
                        "Field": value.pointer,
                        "Value": value.value,
                        "Exact source": value.evidence.source_text,
                        "Start": value.evidence.char_interval.start,
                        "End": value.evidence.char_interval.end,
                        "Anchor": value.evidence.source_spans[0].anchor.model_dump(
                            mode="json"
                        ),
                    }
                    for value in native_extraction.values
                ],
                hide_index=True,
                width="stretch",
            )
            for warning in native_extraction.warnings:
                st.warning(warning)
    with native_tab_by_name["JSON"]:
        st.code(result.json, language="json")
    with native_tab_by_name["Source Structure"]:
        st.dataframe(
            [
                {
                    "Unit": element.source.anchor.unit_id,
                    "Order": element.reading_order + 1,
                    "Type": element.type,
                    "Text": element.text,
                    "Anchor": element.source.anchor.model_dump(mode="json"),
                }
                for element in result.document.elements
            ]
            + [
                {
                    "Unit": asset.anchor.unit_id,
                    "Order": None,
                    "Type": asset.type,
                    "Text": asset.alt_text or asset.filename or asset.reference or "",
                    "Anchor": asset.anchor.model_dump(mode="json"),
                }
                for asset in result.document.assets
            ],
            hide_index=True,
            width="stretch",
        )
    with st.container(border=True):
        native_extraction = st.session_state.get("native_extraction_result")
        full_json = render_native_combined_result(result, native_extraction)
        st.download_button(
            "Download Markdown",
            result.markdown,
            file_name=f"{Path(upload.name).stem}.md",
            mime="text/markdown",
            on_click="ignore",
        )
        if result.annotated_pdf is not None:
            st.download_button(
                "Download annotated PDF",
                result.annotated_pdf,
                file_name=f"{Path(upload.name).stem}.annotated.pdf",
                mime="application/pdf",
                on_click="ignore",
            )
        st.download_button(
            "Download Full JSON",
            full_json,
            file_name=f"{Path(upload.name).stem}.full.json",
            mime="application/json",
            on_click="ignore",
        )
        if native_extraction is not None:
            st.download_button(
                "Download extraction JSON",
                native_extraction.json,
                file_name=f"{Path(upload.name).stem}.extract.json",
                mime="application/json",
                on_click="ignore",
            )
    st.stop()
if has_result:
    header_status_slot.markdown("Status: :green[● **Complete**]")
    for warning in result.metadata.enhancement.warnings:
        st.warning(warning)
    if analysis is not None:
        if analysis.classification is not None:
            header_title.badge(
                f"Detected: {analysis.classification.primary_type} "
                f"({analysis.classification.confidence:.0%})",
                color="blue",
            )
        for feature in analysis.features.values():
            for warning in feature.warnings:
                st.warning(warning)
    has_luna_output = (
        result.metadata.visual_recovery_crops > 0
        or bool(result.usage and result.usage.calls)
        or bool(analysis and analysis.usage.calls)
        or bool(extraction_result and extraction_result.usage.calls)
        or bool(custom_classification and custom_classification.usage.calls)
        or bool(routed_extraction_result and routed_extraction_result.usage.calls)
        or any(turn.get("confidence") for turn in st.session_state.chat_history)
    )
    if has_luna_output:
        st.warning(LUNA_REVIEW_WARNING)
elif active_document is not None:
    active_workspace = st.session_state.batch_workspaces[active_document.id]
    if active_workspace["status"] == "failed":
        st.error(
            f"{active_document.display_name} failed: {active_workspace['error']}"
        )

tab_labels = ["Overview", "Markdown", "HTML View", "Annotated PDF"]
if has_result:
    tab_labels.append("Extract")
if enable_chat:
    tab_labels.append("Chat")
tab_labels.append("Layout Tree")
tabs = st.tabs(tab_labels, key="studio_tab", on_change="rerun")
tab_by_name = dict(zip(tab_labels, tabs, strict=True))

if not has_result:
    with tab_by_name["Overview"]:
        st.info(
            "Upload one or more documents and select Parse document or Process "
            "documents to begin."
        )
else:
    elements = result.elements or build_elements(result.document)
    elements_by_id = {element.id: element for element in elements}
    elements_json = json.dumps(
        [element.model_dump(mode="json") for element in elements],
        ensure_ascii=False,
    )
    recovered_element_ids = [
        element.id for element in elements if element.source == "luna-recovery"
    ]
    recovered_ids_json = json.dumps(
        recovered_element_ids,
        ensure_ascii=False,
    )
    parsed_pages = len(result.document.pages)
    stem = Path(result.document.source_name).stem
    selected_element_id = st.session_state.get("selected_element_id")

    overview_tab = tab_by_name["Overview"]
    if overview_tab.open:
        with overview_tab:
            counts = {
                "tables": sum(element.type == "table" for element in elements),
                "figures": sum(
                    element.type in {"figure", "image", "chart"}
                    for element in elements
                ),
            }
            metrics = st.columns(6)
            metrics[0].metric("Pages", f"{parsed_pages:,}")
            metrics[1].metric("Regions", f"{len(elements):,}")
            metrics[2].metric("Tables", f"{counts['tables']:,}")
            metrics[3].metric("Figures", f"{counts['figures']:,}")
            metrics[4].metric("Time", f"{result.metadata.processing_time:.1f}s")
            metrics[5].metric(
                "Recovered",
                f"{len(recovered_element_ids):,}",
            )

            if result.ocr_comparisons:
                st.subheader("Local OCR cross-check")
                st.dataframe(
                    [
                        {
                            "Page": item.page,
                            "Block": item.block_id or "—",
                            "Status": item.status,
                            "Similarity": item.similarity,
                            "Primary engine": item.primary_engine,
                            "Primary text": item.primary_text,
                            "Alternate engine": item.secondary_engine,
                            "Alternate text": item.secondary_text or "",
                        }
                        for item in result.ocr_comparisons
                    ],
                    hide_index=True,
                    width="stretch",
                )

            if analysis is not None and analysis.classification is not None:
                st.subheader("Document type")
                st.write(
                    f"**{analysis.classification.primary_type}** · "
                    f"{analysis.classification.confidence:.0%} confidence"
                )
                if analysis.classification.reasoning:
                    st.caption(analysis.classification.reasoning)

            if analysis is not None and analysis.toc is not None:
                st.subheader("Table of contents")
                for section, number in flattened_toc(analysis.toc.sections):
                    label = f"{number} {section.title} · page {section.page}"
                    if section.element_id:
                        st.button(
                            label,
                            key=f"toc-{number}-{section.element_id}",
                            on_click=select_source,
                            args=(section.element_id, section.page),
                        )
                    else:
                        st.write(label)

            st.subheader("Pages")
            group_count = max(1, math.ceil(parsed_pages / THUMBNAILS_PER_GROUP))
            group = (
                int(
                    st.selectbox(
                        "Thumbnail group",
                        range(1, group_count + 1),
                        format_func=lambda value: (
                            f"Pages {(value - 1) * THUMBNAILS_PER_GROUP + 1}-"
                            f"{min(value * THUMBNAILS_PER_GROUP, parsed_pages)}"
                        ),
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

    markdown_tab = tab_by_name["Markdown"]
    if markdown_tab.open:
        with markdown_tab:
            show_raw_markdown = st.toggle(
                "Show raw Markdown",
                key=f"show_raw_markdown_{active_document.id}",
            )
            if show_raw_markdown:
                st.code(result.markdown, language="markdown", wrap_lines=True, height=650)
                st.caption("Use the copy control in the code toolbar.")
            else:
                st.markdown(
                    sanitize_markdown_preview(result.markdown),
                    unsafe_allow_html=True,
                )

    html_tab = tab_by_name["HTML View"]
    if html_tab.open:
        with html_tab:
            render_grounded_html_preview(
                result.base_markdown or result.markdown,
                key="grounded-html-preview-ocr",
            )

    annotated_tab = tab_by_name["Annotated PDF"]
    if annotated_tab.open:
        with annotated_tab:
            show_annotations = st.toggle(
                "Show annotations",
                value=True,
                key=f"show_annotations_{active_document.id}",
            )
            st.markdown(
                ":blue[■] Text / title · :green[■] Table / form · "
                ":orange[■] Figure · :violet[■] Formula · :red[■] Seal · "
                ":orange[--] Luna recovery"
            )
            page_columns = st.columns([1, 2, 1])
            if page_columns[0].button("Previous", disabled=st.session_state.annotated_page <= 1):
                st.session_state.annotated_page -= 1
                st.rerun()
            annotated_page = int(
                page_columns[1].number_input(
                    "Page",
                    min_value=1,
                    max_value=parsed_pages,
                    key="annotated_page",
                )
            )
            if page_columns[2].button("Next", disabled=annotated_page >= parsed_pages):
                st.session_state.annotated_page += 1
                st.rerun()
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
                recovered_ids_json,
            )
            st.pdf(
                pdf_page(viewer_pdf, annotated_page - 1),
                height=780,
                key=f"annotated-{show_annotations}-{annotated_page}-{selected_element_id}",
            )
            page_elements = [item for item in elements if item.page == annotated_page]
            with st.expander("Page elements"):
                for element in page_elements:
                    preview = " ".join(element.text.split())[:90] or "No text"
                    st.button(
                        f"{element.reading_order} · {element.type} — {preview}",
                        key=f"page-element-{element.id}",
                        on_click=select_source,
                        args=(element.id, element.page),
                    )

    extract_tab = tab_by_name["Extract"]
    if extract_tab.open:
        with extract_tab:
            st.caption(
                "Define the field keys to extract and optionally route multi-form documents."
            )
            if not has_environment:
                st.info("Set OPENAI_API_KEY to use schema extraction.")
                extraction_schema = None
                routing_profile = None
            else:
                use_custom_routing = st.toggle(
                    "Use custom form routing",
                    key="use_custom_routing",
                    help="Classify page ranges and extract only eligible categories.",
                    on_change=reset_extraction_mode_state,
                )
                with st.expander(
                    "Extraction schemas", expanded=not use_custom_routing
                ):
                    extraction_schema = render_schema_builder()
                routing_profile = None
                if use_custom_routing:
                    with st.expander("Routing profile", expanded=True):
                        routing_profile = render_classifier_profile_builder()

            if has_environment and use_custom_routing:
                if routing_profile is not None and st.button(
                    "Classify forms",
                    type="primary",
                    icon=":material/account_tree:",
                ):
                    try:
                        with st.spinner("Classifying and segmenting forms..."):
                            custom_classification = DocumentAgent().classify_forms(
                                result,
                                routing_profile,
                                prepared_context=st.session_state.prepared_agentic_context,
                            )
                        st.session_state.custom_classification = custom_classification
                        append_session_usage(custom_classification.usage)
                        st.session_state.extraction_result = None
                        st.session_state.routing_review_rows = _classification_rows(
                            custom_classification
                        )
                        st.session_state.routed_extraction_result = None
                    except Exception as exc:  # noqa: BLE001 - isolated feature error
                        st.error(f"Classification failed: {type(exc).__name__}: {exc}")

                custom_classification = st.session_state.get("custom_classification")
                if custom_classification is not None:
                    if routing_profile != custom_classification.profile:
                        st.session_state.routed_extraction_result = None
                        st.warning(
                            "The routing profile changed. Rerun classification before extraction."
                        )
                    for warning in custom_classification.warnings:
                        st.warning(warning)
                    st.subheader("Classified form segments")
                    category_keys = [
                        category.key
                        for category in custom_classification.profile.categories
                    ] + ["other"]
                    rows = st.session_state.get("routing_review_rows") or _classification_rows(
                        custom_classification
                    )
                    with st.form(f"routing_review_form_{active_document.id}"):
                        edited_rows = st.data_editor(
                            rows,
                            num_rows="dynamic",
                            hide_index=True,
                            key=f"routing_review_editor_{active_document.id}",
                            column_config={
                                "id": st.column_config.TextColumn("Segment", disabled=True),
                                "start_page": st.column_config.NumberColumn(
                                    "Start page", min_value=1, max_value=parsed_pages, required=True
                                ),
                                "end_page": st.column_config.NumberColumn(
                                    "End page", min_value=1, max_value=parsed_pages, required=True
                                ),
                                "category": st.column_config.SelectboxColumn(
                                    "Category", options=category_keys, required=True
                                ),
                                "confidence": st.column_config.NumberColumn(
                                    "Confidence", format="percent", disabled=True
                                ),
                                "reasoning": st.column_config.TextColumn(
                                    "Reasoning", disabled=True
                                ),
                                "approved": st.column_config.CheckboxColumn("Approved"),
                                "eligible": st.column_config.CheckboxColumn(
                                    "Eligible", disabled=True
                                ),
                                "schema_name": st.column_config.TextColumn(
                                    "Extraction schema", disabled=True
                                ),
                            },
                        )
                        apply_review = st.form_submit_button(
                            "Apply routing review", icon=":material/check:"
                        )
                    if apply_review:
                        try:
                            custom_classification = _apply_routing_review(
                                custom_classification, edited_rows, parsed_pages
                            )
                        except (TypeError, ValueError) as exc:
                            st.error(f"Routing review is invalid: {exc}")
                        else:
                            st.session_state.custom_classification = custom_classification
                            st.session_state.routing_review_rows = _classification_rows(
                                custom_classification
                            )
                            st.session_state.routed_extraction_result = None
                            st.toast("Applied routing review")
                            st.rerun()

                    unapproved = [
                        segment.id
                        for segment in custom_classification.segments
                        if not segment.approved
                    ]
                    eligible = [
                        segment
                        for segment in custom_classification.segments
                        if segment.eligible
                    ]
                    st.caption(
                        f"{len(eligible)} eligible segment(s) · "
                        f"{len(unapproved)} awaiting review"
                    )
                    routing_ready = (
                        not unapproved
                        and bool(eligible)
                        and routing_profile == custom_classification.profile
                    )
                    split_ready = (
                        not unapproved
                        and routing_profile == custom_classification.profile
                    )
                    if split_ready:
                        try:
                            split_archive = split_output_archive(
                                parsed_source,
                                upload.name,
                                result,
                                custom_classification,
                            )
                        except Exception as exc:  # noqa: BLE001 - isolated export error
                            st.error(
                                "Could not build split ZIP: "
                                f"{type(exc).__name__}: {exc}"
                            )
                        else:
                            st.download_button(
                                "Download split documents",
                                data=split_archive,
                                file_name=f"{stem}.segments.zip",
                                mime="application/zip",
                                icon=":material/folder_zip:",
                                on_click="ignore",
                                key="download-split-documents",
                            )
                    if st.button(
                        "Extract eligible forms",
                        type="primary",
                        icon=":material/data_object:",
                        disabled=not routing_ready,
                    ):
                        schemas_by_name = {}
                        try:
                            for segment in eligible:
                                stored = schema_store.get(segment.schema_name or "")
                                if stored is not None:
                                    schemas_by_name[segment.schema_name] = (
                                        compile_json_schema(stored)
                                    )
                        except (json.JSONDecodeError, ValueError) as exc:
                            st.error(
                                f"Schema validation failed: {type(exc).__name__}: {exc}"
                            )
                        else:
                            try:
                                with st.spinner("Extracting eligible forms..."):
                                    routed_extraction_result = (
                                        DocumentAgent().extract_forms(
                                            result,
                                            custom_classification,
                                            schemas_by_name,
                                        )
                                    )
                                st.session_state.routed_extraction_result = (
                                    routed_extraction_result
                                )
                                append_session_usage(
                                    routed_extraction_result.usage,
                                    skip_calls=len(custom_classification.usage.calls),
                                )
                            except Exception as exc:  # noqa: BLE001 - isolated feature error
                                st.error(
                                    "Model extraction failed: "
                                    f"{type(exc).__name__}: {exc}"
                                )

                routed_extraction_result = st.session_state.get(
                    "routed_extraction_result"
                )
                if routed_extraction_result is not None:
                    for form in routed_extraction_result.forms:
                        with st.container(border=True):
                            st.markdown(
                                f"**{form.segment_id} · {form.category}** · pages "
                                f"{form.start_page}-{form.end_page} · `{form.status}`"
                            )
                            if form.error:
                                st.error(f"Model output validation failed: {form.error}")
                            if form.extraction is not None:
                                for name, field in form.extraction.fields.items():
                                    st.markdown(f"**{name}** · `{field.confidence}`")
                                    st.write(field.value)
                                    if field.element_id and field.page:
                                        st.button(
                                            "Show source",
                                            key=f"routed-source-{form.segment_id}-{name}",
                                            on_click=select_source,
                                            args=(field.element_id, field.page),
                                        )
            elif has_environment and extraction_schema is not None and st.button(
                "Run extraction", type="primary", icon=":material/data_object:"
            ):
                try:
                    compiled_schema = compile_json_schema(extraction_schema)
                except (json.JSONDecodeError, ValueError) as exc:
                    st.error(f"Schema validation failed: {type(exc).__name__}: {exc}")
                else:
                    try:
                        with st.spinner("Extracting grounded fields..."):
                            extraction_result = DocumentAgent().extract(
                                result,
                                compiled_schema,
                                prepared_context=(
                                    st.session_state.prepared_agentic_context
                                ),
                            )
                        st.session_state.extraction_result = extraction_result
                        append_session_usage(extraction_result.usage)
                        st.session_state.custom_classification = None
                        st.session_state.routed_extraction_result = None
                    except Exception as exc:  # noqa: BLE001 - isolated feature error
                        st.error(
                            f"Model extraction failed: {type(exc).__name__}: {exc}"
                        )
            if not st.session_state.get("use_custom_routing", False):
                extraction_result = st.session_state.get("extraction_result")
                if extraction_result is not None:
                    for name, field in extraction_result.fields.items():
                        with st.container(border=True):
                            st.markdown(f"**{name}** · `{field.confidence}`")
                            st.write(field.value)
                            if field.element_id and field.page:
                                st.button(
                                    "Show source",
                                    key=f"extract-source-{name}",
                                    on_click=select_source,
                                    args=(field.element_id, field.page),
                                )
                    for warning in extraction_result.warnings:
                        st.warning(f"Validation/post-processing: {warning}")

    if enable_chat:
        chat_tab = tab_by_name["Chat"]
        if chat_tab.open:
            with chat_tab:
                history = st.session_state.chat_history
                for turn_index, turn in enumerate(history):
                    with st.chat_message(turn["role"]):
                        st.markdown(turn["content"])
                        if turn.get("confidence"):
                            st.caption(f"Confidence: {turn['confidence']}")
                        for citation in turn.get("sources", []):
                            st.button(
                                f"Show source · page {citation['page']}",
                                key=f"chat-source-{turn_index}-{citation['element_id']}",
                                on_click=select_source,
                                args=(citation["element_id"], citation["page"]),
                            )
                if question := st.chat_input(
                    "Ask about this document", submit_mode="disable"
                ):
                    history.append({"role": "user", "content": question})
                    try:
                        answer = DocumentAgent().chat(
                            result,
                            question,
                            history[:-1],
                            prepared_context=st.session_state.prepared_agentic_context,
                        )
                        append_session_usage(answer.usage)
                        history.append(
                            {
                                "role": "assistant",
                                "content": answer.answer,
                                "sources": [
                                    citation.model_dump(mode="json")
                                    for citation in answer.sources
                                ],
                                "confidence": answer.confidence,
                                "usage": answer.usage.model_dump(mode="json"),
                                "trace": [
                                    event.model_dump(mode="json")
                                    for event in answer.trace
                                ],
                            }
                        )
                    except Exception as exc:  # noqa: BLE001 - isolated feature error
                        history.append(
                            {
                                "role": "assistant",
                                "content": f"Chat failed: {type(exc).__name__}: {exc}",
                            }
                        )
                    st.rerun()

    tree_tab = tab_by_name["Layout Tree"]
    if tree_tab.open:
        with tree_tab:
            st.caption("Select a region to open its highlighted annotated page.")
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
                        with st.container(horizontal=True):
                            st.button(
                                label,
                                key=f"select-element-{block.id}",
                                on_click=select_source,
                                args=(block.id, page.number),
                            )
                            if elements_by_id[block.id].source == "luna-recovery":
                                st.badge(
                                    "Luna",
                                    icon=":material/auto_fix_high:",
                                    color="violet",
                                )

    canonical_annotated_pdf = annotation_variant(
        parsed_source,
        upload.name,
        elements_json,
        parsed_pages,
        True,
        show_reading_order,
        None,
        recovered_ids_json,
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
            routed_extraction_result = st.session_state.get("routed_extraction_result")
            custom_classification = st.session_state.get("custom_classification")
            if extraction_result is not None or routed_extraction_result is not None:
                extraction_json = (
                    routed_extraction_result.json
                    if routed_extraction_result is not None
                    else extraction_result.json
                )
                st.download_button(
                    "Download Extract JSON",
                    extraction_json,
                    file_name=f"{stem}.extract.json",
                    mime="application/json",
                    icon=":material/download:",
                    key="download-extract-json",
                    on_click="ignore",
                )
            st.download_button(
                "Download Full JSON",
                render_combined_result(
                    result,
                    analysis,
                    extraction_result,
                    custom_classification=custom_classification,
                    routed_extraction=routed_extraction_result,
                ),
                file_name=f"{stem}.full.json",
                mime="application/json",
                icon=":material/download:",
                key="download-full-json",
                on_click="ignore",
            )
        analysis_ms = (
            sum(feature.duration_ms for feature in analysis.features.values())
            if analysis is not None
            else 0
        )
        routing_activity = routed_extraction_result or custom_classification
        extraction_ms = (
            sum(event.duration_ms for event in extraction_result.trace)
            if extraction_result is not None
            else 0
        ) + (
            sum(event.duration_ms for event in routing_activity.trace)
            if routing_activity is not None
            else 0
        )
        luna_agentic_time = (
            result.metadata.luna_agentic_time
            + (analysis_ms + extraction_ms) / 1000
        )
        recovery_status = (
            "off"
            if not result.metadata.visual_recovery_enabled
            else (
                f"{result.metadata.visual_recovery_crops} crops · "
                f"{len(recovered_element_ids)} regions recovered"
            )
        )
        st.caption(
            f"GLM-OCR: {result.metadata.glm_time:.1f}s · Luna recovery: "
            f"{result.metadata.luna_recovery_time:.1f}s · Luna agentic: "
            f"{luna_agentic_time:.1f}s · Pages: {parsed_pages} · "
            f"Visual recovery: {recovery_status}"
        )

if batch_documents:
    save_active_workspace()
    archive_entries: list[BatchArchiveEntry] = []
    try:
        for document in batch_documents:
            workspace = st.session_state.batch_workspaces[document.id]
            workspace_status = workspace["status"]
            entry_status = (
                workspace_status
                if workspace_status in {"complete", "failed"}
                else "pending"
            )
            state = workspace["state"]
            stored_result = state.get("result") if entry_status == "complete" else None
            stored_source = state.get("parsed_source")
            if stored_result is None or stored_source is None:
                archive_entries.append(
                    BatchArchiveEntry(
                        name=document.name,
                        source=document.source,
                        status=entry_status,
                        error=workspace.get("error"),
                    )
                )
                continue
            if isinstance(stored_result, NativeParseResult):
                stored_native_extraction = state.get("native_extraction_result")
                archive_entries.append(
                    BatchArchiveEntry(
                        name=document.name,
                        source=document.source,
                        status="complete",
                        markdown=stored_result.markdown,
                        annotated_pdf=stored_result.annotated_pdf,
                        full_json=render_native_combined_result(
                            stored_result, stored_native_extraction
                        ),
                        extraction_json=(
                            stored_native_extraction.json
                            if stored_native_extraction is not None
                            else None
                        ),
                    )
                )
                continue

            stored_elements = stored_result.elements or build_elements(
                stored_result.document
            )
            stored_elements_json = json.dumps(
                [element.model_dump(mode="json") for element in stored_elements],
                ensure_ascii=False,
            )
            stored_recovered_ids_json = json.dumps(
                [
                    element.id
                    for element in stored_elements
                    if element.source == "luna-recovery"
                ],
                ensure_ascii=False,
            )
            stored_extraction = state.get("extraction_result")
            stored_custom_classification = state.get("custom_classification")
            stored_routed_extraction = state.get("routed_extraction_result")
            archive_entries.append(
                BatchArchiveEntry(
                    name=document.name,
                    source=document.source,
                    status="complete",
                    markdown=stored_result.markdown,
                    annotated_pdf=annotation_variant(
                        stored_source,
                        document.name,
                        stored_elements_json,
                        len(stored_result.document.pages),
                        True,
                        show_reading_order,
                        None,
                        stored_recovered_ids_json,
                    ),
                    full_json=render_combined_result(
                        stored_result,
                        state.get("agentic_analysis"),
                        stored_extraction,
                        custom_classification=stored_custom_classification,
                        routed_extraction=stored_routed_extraction,
                    ),
                    extraction_json=(
                        stored_routed_extraction.json
                        if stored_routed_extraction is not None
                        else (
                            stored_extraction.json
                            if stored_extraction is not None
                            else None
                        )
                    ),
                )
            )
        archive_data = output_archive(tuple(archive_entries))
    except Exception as exc:  # noqa: BLE001 - keep individual downloads available
        st.error(f"Could not build output ZIP: {type(exc).__name__}: {exc}")
    else:
        archive_name = (
            f"{Path(batch_documents[0].name).stem}.outputs.zip"
            if len(batch_documents) == 1
            else "document-batch.outputs.zip"
        )
        with st.container(border=True):
            st.download_button(
                "Download all outputs",
                archive_data,
                file_name=archive_name,
                mime="application/zip",
                icon=":material/folder_zip:",
                key="download-all-outputs",
                on_click="ignore",
            )

with session_usage_slot:
    summary = launch_usage_summary()
    if summary.models or summary.unavailable_calls:
        render_usage_metrics(summary)
