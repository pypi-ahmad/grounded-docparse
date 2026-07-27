from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import streamlit as st

from grounded_docparse import extraction, pipeline

SUPPORTED_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff"]
RESULT_VERSION = "2.1.0"


def reset_document_state() -> None:
    st.session_state.result = None
    st.session_state.result_source_hash = None
    st.session_state.schema_text = None
    st.session_state.extraction_result = None


st.set_page_config(
    page_title="Agentic document parser",
    page_icon=":material/document_scanner:",
    layout="wide",
)
if st.session_state.get("result_version") != RESULT_VERSION:
    reset_document_state()
st.session_state.result_version = RESULT_VERSION

st.title("Agentic document parser")
st.caption(
    "Parse a document with bounded specialist agents, then extract grounded structured data."
)

has_environment = bool(os.getenv("OPENAI_API_KEY"))
if not has_environment:
    st.error("OPENAI_API_KEY is required in the environment.")

upload = st.file_uploader(
    "Document",
    type=SUPPORTED_TYPES,
    accept_multiple_files=False,
    max_upload_size=250,
)
source = upload.getvalue() if upload is not None else None
source_hash = hashlib.sha256(source).hexdigest() if source is not None else None

if (
    st.session_state.get("result") is not None
    and st.session_state.get("result_source_hash") != source_hash
):
    reset_document_state()

parse = st.button(
    "Parse document",
    type="primary",
    icon=":material/document_scanner:",
    disabled=source is None or not has_environment,
)

if parse and upload is not None and source is not None:
    try:
        with st.status("Parsing document", expanded=True) as status:

            def show_progress(event) -> None:
                status.write(event.message)

            result = pipeline.DocumentParser().parse(
                source,
                upload.name,
                progress_callback=show_progress,
            )
            status.update(label="Parsing complete", state="complete", expanded=False)
        st.session_state.result = result
        st.session_state.result_source_hash = source_hash
        st.session_state.schema_text = None
        st.session_state.extraction_result = None
    except Exception as exc:  # noqa: BLE001 - provider diagnostics are user-facing
        st.error(f"{type(exc).__name__}: {str(exc)[:1000]}")

result = st.session_state.get("result")
if result is not None and st.session_state.get("result_source_hash") == source_hash:
    source_column, output_column = st.columns([1, 1], gap="large")
    with source_column:
        st.subheader("Source")
        suffix = Path(upload.name).suffix.casefold() if upload is not None else ""
        if suffix == ".pdf":
            st.pdf(source, height=720, key="source-preview")
        else:
            st.image(source, caption=upload.name if upload is not None else None)

    with output_column:
        st.subheader("Output")
        st.caption(
            "AI-extracted — check `needs_review` blocks and the Agent trace tab before relying on values."
        )
        stem = Path(result.document.source_name).stem
        with st.container(horizontal=True):
            st.metric("Input tokens", f"{result.input_tokens:,}", border=True)
            st.metric("Output tokens", f"{result.output_tokens:,}", border=True)

        markdown_tab, agentic_tab, legacy_tab, annotated_tab, trace_tab, extract_tab = (
            st.tabs(
                [
                    "Markdown",
                    "Agentic JSON",
                    "Legacy JSON",
                    "Annotated PDF",
                    "Agent trace",
                    "Extract",
                ]
            )
        )
        with markdown_tab:
            st.download_button(
                "Download Markdown",
                result.markdown,
                file_name=f"{stem}.md",
                mime="text/markdown",
                icon=":material/download:",
                key="download-markdown",
                on_click="ignore",
            )
            view = st.radio(
                "View",
                ["Preview", "Raw"],
                horizontal=True,
                key="markdown-view",
                label_visibility="collapsed",
            )
            if view == "Preview":
                st.markdown(result.markdown)
            else:
                st.code(result.markdown, language="markdown", wrap_lines=True, height=500)

        with agentic_tab:
            st.download_button(
                "Download agentic JSON",
                result.json,
                file_name=f"{stem}.agentic.json",
                mime="application/json",
                icon=":material/download:",
                key="download-agentic-json",
                on_click="ignore",
            )
            view = st.radio(
                "View",
                ["Preview", "Raw"],
                horizontal=True,
                key="agentic-view",
                label_visibility="collapsed",
            )
            if view == "Preview":
                st.json(json.loads(result.json), expanded=2)
            else:
                st.code(result.json, language="json", wrap_lines=True, height=500)

        with legacy_tab:
            st.download_button(
                "Download legacy JSON",
                result.legacy_json,
                file_name=f"{stem}.legacy.json",
                mime="application/json",
                icon=":material/download:",
                key="download-legacy-json",
                on_click="ignore",
            )
            st.json(json.loads(result.legacy_json), expanded=2)

        with annotated_tab:
            st.download_button(
                "Download annotated PDF",
                result.annotated_pdf,
                file_name=f"{stem}.annotated.pdf",
                mime="application/pdf",
                icon=":material/download:",
                key="download-annotated-pdf",
                on_click="ignore",
            )
            st.pdf(result.annotated_pdf, height=720, key="annotated-preview")

        with trace_tab:
            st.json([event.model_dump(mode="json") for event in result.trace], expanded=2)

        with extract_tab:
            instruction = st.text_area(
                "Fields to extract",
                placeholder="For example: invoice number, issue date, supplier, and total",
            )
            if st.button(
                "Generate schema",
                disabled=not instruction.strip(),
                key="generate-schema",
            ):
                try:
                    proposal = extraction.DocumentExtractor().propose_schema(
                        instruction, result
                    )
                    schema_text = json.dumps(proposal.json_schema, indent=2)
                    st.session_state.schema_text = schema_text
                    st.session_state.schema_editor = schema_text
                    st.session_state.extraction_result = None
                except Exception as exc:  # noqa: BLE001 - provider diagnostics are user-facing
                    st.error(f"{type(exc).__name__}: {str(exc)[:1000]}")

            if st.session_state.get("schema_text"):
                if "schema_editor" not in st.session_state:
                    st.session_state.schema_editor = st.session_state.schema_text
                schema_text = st.text_area("JSON Schema", key="schema_editor", height=300)
                if st.button("Run extraction", type="primary", key="run-extraction"):
                    try:
                        selected_schema = json.loads(schema_text)
                    except json.JSONDecodeError as exc:
                        st.error(f"Invalid JSON schema — check syntax. {exc}")
                    else:
                        try:
                            st.session_state.extraction_result = (
                                extraction.DocumentExtractor().extract(
                                    result, selected_schema
                                )
                            )
                        except Exception as exc:  # noqa: BLE001 - provider diagnostics are user-facing
                            st.error(f"{type(exc).__name__}: {str(exc)[:1000]}")

            extraction_result = st.session_state.get("extraction_result")
            if extraction_result is not None:
                st.download_button(
                    "Download extraction JSON",
                    extraction_result.json,
                    file_name=f"{stem}.extraction.json",
                    mime="application/json",
                    icon=":material/download:",
                    key="download-extraction-json",
                    on_click="ignore",
                )
                st.json(extraction_result.data, expanded=2)
                st.caption("Evidence")
                st.json(extraction_result.evidence, expanded=2)
