from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf
import streamlit as st
from PIL import Image, ImageSequence

from grounded_docparse import pipeline
from grounded_docparse.agentic import DocumentAgent
from grounded_docparse.local_ocr import get_glmocr_runtime
from grounded_docparse.models import (
    ClassifierCategory,
    ClassifierProfile,
    Element,
    FormClassificationResult,
    FormSegment,
    SchemaField,
    StoredSchema,
)
from grounded_docparse.render import (
    build_elements,
    render_annotated_pdf,
    render_combined_result,
)
from grounded_docparse.schema_store import (
    ClassifierProfileStore,
    SchemaStore,
    compile_json_schema,
    parse_markdown_classifier_profile,
    parse_markdown_schema,
)

SUPPORTED_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff"]
RESULT_VERSION = "4.5.0"
THUMBNAILS_PER_GROUP = 12
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


def luna_destination() -> str:
    value = os.getenv("OPENAI_BASE_URL")
    if not value:
        return "OpenAI default endpoint"
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "custom endpoint (invalid host)"
    if not hostname:
        return "custom endpoint (invalid host)"
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{host}:{port}" if port is not None else host


def reset_document_state() -> None:
    st.session_state.result = None
    st.session_state.result_source_hash = None
    st.session_state.parsed_source = None
    st.session_state.selected_element_id = None
    st.session_state.overview_page = 1
    st.session_state.annotated_page = 1
    st.session_state.agentic_analysis = None
    st.session_state.agentic_source_hash = None
    st.session_state.extraction_result = None
    st.session_state.custom_classification = None
    st.session_state.routed_extraction_result = None
    st.session_state.routing_review_rows = None
    st.session_state.chat_history = []
    st.session_state.prepared_agentic_context = None


def reset_extraction_mode_state() -> None:
    st.session_state.extraction_result = None
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


schema_store = SchemaStore(
    os.getenv("DOCPARSE_STUDIO_DB_PATH", "data/document_studio.sqlite3")
)
classifier_profile_store = ClassifierProfileStore(
    os.getenv("DOCPARSE_STUDIO_DB_PATH", "data/document_studio.sqlite3")
)


def render_schema_builder() -> StoredSchema | None:
    pending_draft = st.session_state.pop("pending_schema_draft", None)
    if pending_draft is not None:
        st.session_state.schema_draft_name = pending_draft["name"]
        st.session_state.schema_draft_fields = pending_draft["fields"]
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
            st.session_state.schema_draft_fields = [
                field.model_dump(mode="json") for field in loaded.fields
            ]
            st.session_state.schema_draft_revision = (
                st.session_state.get("schema_draft_revision", 0) + 1
            )
            st.rerun()

    st.session_state.setdefault("schema_draft_name", "")
    st.session_state.setdefault(
        "schema_draft_fields",
        [{"name": "", "description": "", "type": "string"}],
    )
    revision = st.session_state.setdefault("schema_draft_revision", 0)
    name = st.text_input(
        "Schema name",
        value=st.session_state.schema_draft_name,
        key=f"schema_draft_name_editor_{revision}",
    )
    fields = st.data_editor(
        st.session_state.schema_draft_fields,
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
    st.session_state.schema_draft_name = name
    st.session_state.schema_draft_fields = fields

    imported = st.file_uploader("Import schema JSON", type=["json"], key="schema_import")
    imported_markdown = st.file_uploader(
        "Import schema Markdown",
        type=["md"],
        key="schema_markdown_import",
        max_upload_size=1,
    )
    actions = st.columns(3)
    if actions[0].button("Save schema", type="primary"):
        try:
            schema = StoredSchema(
                name=name.strip(),
                fields=[SchemaField.model_validate(field) for field in fields],
            )
        except ValueError as exc:
            st.error(f"Schema is incomplete: {exc}")
        else:
            schema_store.save(schema)
            st.session_state.routed_extraction_result = None
            st.toast(f"Saved schema {schema.name}")
            st.rerun()
    if actions[1].button("Load example"):
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
        st.session_state.schema_draft_revision += 1
        st.rerun()

    if imported is not None and st.button("Import JSON"):
        schema = StoredSchema.model_validate_json(imported.getvalue())
        schema_store.save(schema)
        st.session_state.routed_extraction_result = None
        st.toast(f"Imported schema {schema.name}")
        st.rerun()
    if imported_markdown is not None:
        markdown_bytes = imported_markdown.getvalue()
        import_fingerprint = hashlib.sha256(
            imported_markdown.name.encode("utf-8") + b"\0" + markdown_bytes
        ).hexdigest()
    else:
        markdown_bytes = None
        import_fingerprint = None
    if (
        markdown_bytes is not None
        and st.session_state.get("schema_markdown_import_fingerprint")
        != import_fingerprint
    ):
        try:
            schema = parse_markdown_schema(markdown_bytes, imported_markdown.name)
        except ValueError as exc:
            st.error(f"Markdown schema is invalid: {exc}")
        else:
            st.session_state.schema_markdown_import_fingerprint = import_fingerprint
            st.session_state.pending_schema_draft = {
                "name": schema.name,
                "fields": [
                    field.model_dump(mode="json") for field in schema.fields
                ],
            }
            st.toast(f"Loaded schema {schema.name}")
            st.rerun()
    draft = None
    if name.strip() and fields:
        try:
            draft = StoredSchema(
                name=name.strip(),
                fields=[SchemaField.model_validate(field) for field in fields],
            )
        except ValueError:
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
    reset_document_state()
st.session_state.result_version = RESULT_VERSION
initialize_ade_mode()

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
    st.caption("Powered by GLM-OCR + gpt-5.6-luna")

initial_status = "Ready" if preload_error is None else "Not ready"
initial_color = "green" if initial_status == "Ready" else "red"
header_status_slot = header_status.empty()
header_status_slot.markdown(f"Status: :{initial_color}[● **{initial_status}**]")

if not has_environment:
    st.warning(
        "OPENAI_API_KEY is not set. GLM-OCR parsing remains available; Luna visual "
        "recovery and Markdown refinement will be skipped."
    )
elif os.getenv("OPENAI_BASE_URL"):
    st.warning(
        f"Luna requests will send document content to custom endpoint: "
        f"`{luna_destination()}`."
    )
else:
    st.caption(f"Luna destination: {luna_destination()}")
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
        help="Uses high-effort Luna vision on at most eight prioritized crops per document.",
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
    visual_recovery = bool(st.session_state.visual_recovery and has_environment)
    st.toggle(
        "Enable document chat",
        key="enable_chat",
        disabled=not has_environment,
    )
    enable_chat = st.session_state.enable_chat
    selection_key = (
        f"{source_hash}:{start_page}:{end_page}:{refine_markdown}:"
        f"{visual_recovery}:{has_environment}:"
        f"{RESULT_VERSION}"
        if source_hash is not None
        else None
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
        disabled=source is None or preload_error is not None,
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
                value = 0.30 + 0.42 * event.current / max(event.total, 1)
            elif stage in {"verify", "delegate", "recover"}:
                completed_stages.add("layout")
                progress_state["active"] = "recover"
                value = 0.76
            elif stage == "assemble":
                completed_stages.update({"layout", "recognize", "recover"})
                progress_state["active"] = "assemble"
                value = 0.82
            elif stage == "annotate":
                completed_stages.update({"layout", "recognize", "recover", "assemble"})
                progress_state["active"] = "annotate"
                value = 0.90
            elif stage == "enhance":
                completed_stages.update(
                    {"layout", "recognize", "recover", "assemble", "annotate"}
                )
                progress_state["active"] = "enhance"
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

        result = st.session_state.get("result") if cached_result_matches else None
        if result is None:
            result = pipeline.DocumentParser().parse(
                parsed_source,
                upload.name,
                progress_callback=show_progress,
                refine_markdown=refine_markdown,
                visual_recovery=visual_recovery,
            )
            st.session_state.result = result
            st.session_state.result_source_hash = selection_key
            st.session_state.parsed_source = parsed_source
            st.session_state.selected_element_id = None
            st.session_state.annotated_page = 1
            st.session_state.extraction_result = None
            st.session_state.chat_history = []
            st.session_state.prepared_agentic_context = DocumentAgent.prepare(result)

        prepared_context = st.session_state.get("prepared_agentic_context")
        if prepared_context is None:
            prepared_context = DocumentAgent.prepare(result)
            st.session_state.prepared_agentic_context = prepared_context

        agentic_key = f"{selection_key}:{classify_document}:{generate_toc}"
        if st.session_state.get("agentic_source_hash") != agentic_key:
            completed_stages.update(
                {"layout", "recognize", "recover", "assemble", "annotate", "enhance"}
            )
            progress_state["active"] = "classify"
            progress_bar.progress(0.97, text="Running Luna document analysis")
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
            st.session_state.agentic_source_hash = agentic_key
        progress_bar.progress(1.0, text="Parsing complete")
        stage_log.markdown(stage_markdown(None, {key for key, _ in STAGE_LABELS}))
        header_status_slot.markdown("Status: :green[● **Complete**]")
    except Exception as exc:  # noqa: BLE001 - provider diagnostics are user-facing
        progress_bar.progress(0, text="Parsing failed")
        header_status_slot.markdown("Status: :red[● **Error**]")
        st.error(f"{type(exc).__name__}: {str(exc)[:1000]}")

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
)
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

tab_labels = ["Overview", "Markdown", "Annotated PDF"]
if has_result:
    tab_labels.append("Extract")
if enable_chat:
    tab_labels.append("Chat")
tab_labels.append("Layout Tree")
tabs = st.tabs(tab_labels, key="studio_tab", on_change="rerun")
tab_by_name = dict(zip(tab_labels, tabs, strict=True))

if not has_result:
    with tab_by_name["Overview"]:
        st.info("Upload a document and select Parse document to begin.")
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
            show_raw_markdown = st.toggle("Show raw Markdown")
            if show_raw_markdown:
                st.code(result.markdown, language="markdown", wrap_lines=True, height=650)
                st.caption("Use the copy control in the code toolbar.")
            else:
                st.markdown(result.markdown)

    annotated_tab = tab_by_name["Annotated PDF"]
    if annotated_tab.open:
        with annotated_tab:
            show_annotations = st.toggle("Show annotations", value=True)
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
                    with st.form("routing_review_form"):
                        edited_rows = st.data_editor(
                            rows,
                            num_rows="dynamic",
                            hide_index=True,
                            key="routing_review_editor",
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
                    if st.button(
                        "Extract eligible forms",
                        type="primary",
                        icon=":material/data_object:",
                        disabled=not routing_ready,
                    ):
                        schemas_by_name = {}
                        for segment in eligible:
                            stored = schema_store.get(segment.schema_name or "")
                            if stored is not None:
                                schemas_by_name[segment.schema_name] = compile_json_schema(
                                    stored
                                )
                        try:
                            with st.spinner("Extracting eligible forms..."):
                                routed_extraction_result = DocumentAgent().extract_forms(
                                    result,
                                    custom_classification,
                                    schemas_by_name,
                                )
                            st.session_state.routed_extraction_result = (
                                routed_extraction_result
                            )
                        except Exception as exc:  # noqa: BLE001 - isolated feature error
                            st.error(f"Routed extraction failed: {type(exc).__name__}: {exc}")

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
                                st.error(form.error)
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
                    with st.spinner("Extracting grounded fields..."):
                        extraction_result = DocumentAgent().extract(
                            result,
                            compile_json_schema(extraction_schema),
                            prepared_context=st.session_state.prepared_agentic_context,
                        )
                    st.session_state.extraction_result = extraction_result
                    st.session_state.custom_classification = None
                    st.session_state.routed_extraction_result = None
                except Exception as exc:  # noqa: BLE001 - isolated feature error
                    st.error(f"Extraction failed: {type(exc).__name__}: {exc}")
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
                        st.warning(warning)

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
        analysis_input = analysis.usage.input_tokens if analysis is not None else 0
        analysis_output = analysis.usage.output_tokens if analysis is not None else 0
        extract_input = extraction_result.input_tokens if extraction_result else 0
        extract_output = extraction_result.output_tokens if extraction_result else 0
        routing_input = routing_activity.usage.input_tokens if routing_activity else 0
        routing_output = routing_activity.usage.output_tokens if routing_activity else 0
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
            f"Visual recovery: {recovery_status} · "
            f"Luna input tokens: "
            f"{result.input_tokens + analysis_input + extract_input + routing_input:,} · "
            f"Luna output tokens: "
            f"{result.output_tokens + analysis_output + extract_output + routing_output:,}"
        )
