from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from grounded_docparse import (
    DocumentParser,
    DocumentProfile,
    ParserConfig,
    ProcessingProfile,
    SegmentationMode,
    evaluate_tree,
    load_gold_tree,
)
from grounded_docparse.models import DocumentTree, ProgressEvent
from grounded_docparse.review import build_batch_bundle, render_review_page

SUPPORTED_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff"]
MAX_BATCH_FILES = 10
MAX_BATCH_BYTES = 1024 * 1024 * 1024


@st.cache_data(max_entries=8, show_spinner=False)
def _review_page(
    source: bytes,
    filename: str,
    tree_json: str,
    page_number: int,
    selected_node_id: str | None,
) -> bytes:
    tree = DocumentTree.model_validate_json(tree_json)
    return render_review_page(
        source,
        filename,
        tree,
        page_number,
        selected_node_id=selected_node_id,
    )


def _show_source(data: bytes, filename: str) -> None:
    if Path(filename).suffix.casefold() == ".pdf":
        st.pdf(data, height=650, key="source-pdf-preview")
    else:
        st.image(data, caption=filename)


st.set_page_config(page_title="Grounded document parser", layout="wide")
st.session_state.setdefault("batch_results", [])
st.session_state.setdefault("batch_bundle", b"")
st.session_state.setdefault("evaluation_report", None)

st.title("Grounded document parser")
st.caption("Layout-aware parsing, auditable evidence, and automatic quality recovery.")

mode = st.segmented_control("Mode", ["Parse", "Evaluate"], default="Parse") or "Parse"
profile_labels = {
    "Local only": ProcessingProfile.LOCAL_ONLY,
    "Hybrid": ProcessingProfile.HYBRID,
    "Maximum accuracy": ProcessingProfile.MAXIMUM_ACCURACY,
}
document_profile_labels = {
    "Auto-detect": DocumentProfile.AUTO,
    "Generic": DocumentProfile.GENERIC,
    "Technical documentation": DocumentProfile.TECHNICAL_DOCUMENTATION,
    "Scientific paper": DocumentProfile.SCIENTIFIC_PAPER,
    "Invoice": DocumentProfile.INVOICE,
    "Insurance claim": DocumentProfile.INSURANCE_CLAIM,
    "Healthcare form": DocumentProfile.HEALTHCARE_FORM,
    "Purchase order": DocumentProfile.PURCHASE_ORDER,
    "Receipt": DocumentProfile.RECEIPT,
    "Contract": DocumentProfile.CONTRACT,
    "Correspondence": DocumentProfile.CORRESPONDENCE,
    "Generic form": DocumentProfile.GENERIC_FORM,
}

settings = st.container(border=True)
with settings:
    first, second, third = st.columns(3)
    profile_name = first.selectbox("Processing profile", list(profile_labels))
    document_profile_name = second.selectbox(
        "Document type", list(document_profile_labels)
    )
    segmentation = third.selectbox(
        "Segmentation",
        [SegmentationMode.AUTO, SegmentationMode.OFF],
        format_func=lambda value: "Automatic" if value == SegmentationMode.AUTO else "Off",
    )
    schema_mode = st.selectbox("Schema extraction", ["None", "Paste JSON", "Upload JSON"])
    schema_text = ""
    schema_upload = None
    if schema_mode == "Paste JSON":
        schema_text = st.text_area(
            "Extraction schema",
            value=(
                '{\n  "title": "Custom extraction",\n  "type": "object",\n'
                '  "properties": {},\n  "additionalProperties": false\n}'
            ),
            height=180,
        )
    elif schema_mode == "Upload JSON":
        schema_upload = st.file_uploader(
            "Extraction schema", type=["json"], key="extraction-schema"
        )

extraction_schema = None
schema_error = None
if schema_mode != "None":
    raw_schema = schema_text
    if schema_upload is not None:
        if schema_upload.size > 256 * 1024:
            schema_error = "schema exceeds 256 KB"
        else:
            try:
                raw_schema = schema_upload.getvalue().decode("utf-8")
            except UnicodeDecodeError:
                schema_error = "schema is not valid UTF-8"
    if raw_schema and schema_error is None:
        try:
            extraction_schema = json.loads(raw_schema)
            if not isinstance(extraction_schema, dict):
                raise TypeError
        except (json.JSONDecodeError, TypeError):
            schema_error = "schema root must be a valid JSON object"
if schema_error:
    st.error(f"Invalid extraction schema: {schema_error}")

uploaded = st.file_uploader(
    "Documents" if mode == "Parse" else "Document",
    type=SUPPORTED_TYPES,
    accept_multiple_files=mode == "Parse",
    max_upload_size=250,
    key="documents",
)
uploads = uploaded if isinstance(uploaded, list) else ([uploaded] if uploaded else [])
batch_error = None
if len(uploads) > MAX_BATCH_FILES:
    batch_error = f"A batch can contain at most {MAX_BATCH_FILES} files."
elif sum(item.size for item in uploads) > MAX_BATCH_BYTES:
    batch_error = "The combined batch size cannot exceed 1 GB."
if batch_error:
    st.error(batch_error)

gold_upload = None
if mode == "Evaluate":
    gold_upload = st.file_uploader(
        "Corrected gold document tree", type=["json"], key="gold-tree"
    )

if uploads:
    preview_upload = st.selectbox(
        "Uploaded file preview",
        uploads,
        format_func=lambda item: f"{item.name} · {item.size / (1024 * 1024):.1f} MB",
    )
    with st.expander("View uploaded file", expanded=len(uploads) == 1):
        _show_source(preview_upload.getvalue(), preview_upload.name)

profile = profile_labels[profile_name]
cloud_profile = profile != ProcessingProfile.LOCAL_ONLY
cloud_consent = False
if cloud_profile:
    cloud_consent = st.checkbox(
        "I consent to send document page images and OCR evidence to OpenAI for this batch"
    )
    if not os.getenv("OPENAI_API_KEY"):
        st.error("This processing profile requires OPENAI_API_KEY.")

disabled = not uploads or batch_error is not None or schema_error is not None
disabled = disabled or (schema_mode != "None" and extraction_schema is None)
disabled = disabled or (mode == "Evaluate" and gold_upload is None)
disabled = disabled or (cloud_profile and not cloud_consent)
disabled = disabled or (cloud_profile and not os.getenv("OPENAI_API_KEY"))

if st.button("Process", type="primary", disabled=disabled, icon=":material/play_arrow:"):
    progress = st.progress(0, text="Starting batch")
    completed: list[dict[str, object]] = []
    report = None
    with st.status("Processing documents", expanded=True) as status:
        for file_index, item in enumerate(uploads, start=1):
            status.write(f"{file_index}/{len(uploads)} · {item.name}")

            def update(
                event: ProgressEvent,
                index: int = file_index,
                source_name: str = item.name,
            ) -> None:
                within = 0 if event.total <= 0 else min(1, event.current / event.total)
                overall = ((index - 1) + within) / len(uploads)
                progress.progress(overall, text=f"{source_name}: {event.message}")

            try:
                result = DocumentParser(ParserConfig.from_env()).parse(
                    item.getvalue(),
                    item.name,
                    update,
                    profile=profile,
                    document_profile=document_profile_labels[document_profile_name],
                    segmentation=segmentation,
                    extraction_schema=extraction_schema,
                )
                if mode == "Evaluate":
                    assert gold_upload is not None
                    report = evaluate_tree(
                        result.tree, load_gold_tree(gold_upload.getvalue())
                    )
            except Exception as exc:  # noqa: BLE001 - safe per-file boundary
                completed.append(
                    {
                        "name": item.name,
                        "source": item.getvalue(),
                        "result": None,
                        "error": type(exc).__name__,
                    }
                )
                status.write(f"{item.name}: failed ({type(exc).__name__})")
            else:
                completed.append(
                    {
                        "name": item.name,
                        "source": item.getvalue(),
                        "result": result,
                        "error": None,
                    }
                )
        st.session_state["batch_results"] = completed
        st.session_state["evaluation_report"] = report
        st.session_state["batch_bundle"] = build_batch_bundle(
            [
                (str(item["name"]), item["result"], item["error"])
                for item in completed
            ]
        )
        status.update(label="Processing complete", state="complete", expanded=False)
        progress.progress(1.0, text="Complete")

batch_results = st.session_state.get("batch_results", [])
successful = [item for item in batch_results if item.get("result") is not None]
if batch_results:
    st.subheader("Batch status")
    st.dataframe(
        [
            {
                "document": item["name"],
                "status": "Complete" if item.get("result") else "Failed",
                "error": item.get("error") or "",
            }
            for item in batch_results
        ],
        hide_index=True,
    )
    st.download_button(
        "Download batch ZIP",
        st.session_state["batch_bundle"],
        file_name="document-batch.zip",
        mime="application/zip",
        icon=":material/folder_zip:",
    )

if successful:
    active = st.selectbox(
        "Review document",
        successful,
        format_func=lambda item: str(item["name"]),
        key="active-document",
    )
    result = active["result"]
    source = active["source"]
    filename = str(active["name"])
    stem = Path(filename).stem
    tree = result.tree
    tab_names = [
        "Review",
        "Source",
        "Annotated PDF",
        "Quality",
        "LLM-ready Markdown",
        "Structured data",
        "Sub-documents",
    ]
    if st.session_state.get("evaluation_report") is not None:
        tab_names.append("Evaluation")
    tabs = dict(zip(tab_names, st.tabs(tab_names), strict=True))

    with tabs["Review"]:
        controls = st.container(border=True)
        with controls:
            left, middle, right = st.columns(3)
            query = left.text_input("Search document tree", placeholder="Text, type, role, source…")
            page_filter = middle.selectbox("Page", ["All", *[page.number for page in tree.pages]])
            status_filter = right.selectbox(
                "Status", ["All", "disputed", "unreadable", "unresolved"]
            )
        nodes = [
            tree.nodes[node_id]
            for page in tree.pages
            for node_id in page.content_node_ids
        ]
        if page_filter != "All":
            nodes = [node for node in nodes if node.page_number == page_filter]
        if status_filter != "All":
            nodes = [node for node in nodes if node.verification_status == status_filter]
        if query.strip():
            needle = query.casefold().strip()
            nodes = [
                node
                for node in nodes
                if needle
                in " ".join(
                    [
                        node.id,
                        str(node.type),
                        node.semantic_role or "",
                        node.text or "",
                        *(candidate.source for candidate in node.recognition_candidates),
                    ]
                ).casefold()
            ]
        nodes.sort(key=lambda node: (node.page_number or 0, node.reading_order or 0))
        if not nodes:
            st.info("No regions match the current filters.")
        else:
            selected = st.selectbox(
                "Document tree node",
                nodes,
                format_func=lambda node: (
                    f"p{node.page_number} · #{(node.reading_order or 0) + 1} · "
                    f"{node.type} · {(node.text or '[UNREADABLE]')[:80]}"
                ),
                key=f"selected-node-{tree.document_id}",
            )
            preview_col, evidence_col = st.columns([1.45, 1])
            with preview_col:
                st.image(
                    _review_page(
                        source,
                        filename,
                        result.json,
                        selected.page_number or 1,
                        selected.id,
                    ),
                    caption=f"Page {selected.page_number} · selected region in blue",
                )
            with evidence_col:
                confidence = selected.confidence.score if selected.confidence else 0
                st.metric("Selected confidence", f"{confidence:.1%}")
                st.caption(
                    f"{selected.type} · {selected.semantic_role or 'unclassified'} · "
                    f"{selected.verification_status or 'unknown'}"
                )
                st.code(selected.markdown or selected.text or "[UNREADABLE]", language="markdown")
                st.subheader("Candidates")
                st.dataframe(
                    [
                        {
                            "selected": candidate.id == selected.selected_candidate_id,
                            "source": candidate.source,
                            "pass": candidate.pass_number,
                            "task": candidate.task,
                            "text": candidate.text,
                        }
                        for candidate in selected.recognition_candidates
                    ],
                    hide_index=True,
                )
                with st.expander("Citations and provenance"):
                    st.json(
                        {
                            "citations": [item.model_dump(mode="json") for item in selected.citations],
                            "provenance": [item.model_dump(mode="json") for item in selected.provenance],
                        },
                        expanded=False,
                    )
        st.subheader("Automatic retry decisions")
        st.dataframe(
            [item.model_dump(mode="json") for item in tree.adaptive_retries],
            hide_index=True,
        )

    with tabs["Source"]:
        _show_source(source, filename)
    with tabs["Annotated PDF"]:
        st.pdf(result.annotated_pdf, height=750, key="annotated-pdf-preview")
        st.download_button(
            "Download annotated PDF",
            result.annotated_pdf,
            file_name=f"{stem}.annotated.pdf",
            mime="application/pdf",
        )
    with tabs["Quality"]:
        quality = json.loads(result.quality_json)
        summary = quality["summary"]
        metrics = st.columns(4)
        metrics[0].metric("OCR coverage", f"{summary['ocr_coverage']:.1%}")
        metrics[1].metric("Disagreements", summary["disagreement_count"])
        metrics[2].metric("Unresolved", summary["unresolved_count"])
        metrics[3].metric("Warnings", summary["warning_count"])
        st.caption("Table metrics are structural and grounding quality proxies, not labeled accuracy.")
        st.json(summary["table_quality"], expanded=False)
        st.dataframe(quality["pages"], hide_index=True)
        if quality["warnings"]:
            st.warning("\n".join(quality["warnings"]))
        st.download_button(
            "Download quality report",
            result.quality_json,
            file_name=f"{stem}.quality.json",
            mime="application/json",
        )
    with tabs["LLM-ready Markdown"]:
        st.code(result.llm_markdown, language="markdown", line_numbers=True)
    with tabs["Structured data"]:
        data_tabs = st.tabs(["JSON", "Structured Markdown", "Audit", "Failures"])
        with data_tabs[0]:
            st.json(json.loads(result.json), expanded=False)
        with data_tabs[1]:
            st.code(result.markdown, language="markdown", line_numbers=True)
        with data_tabs[2]:
            st.json(json.loads(result.audit_json), expanded=False)
        with data_tabs[3]:
            st.code(result.failures_jsonl or "No failure cases", language="json")
        if result.extraction_json:
            with st.expander("Schema extraction"):
                st.json(json.loads(result.extraction_json), expanded=False)
    with tabs["Sub-documents"]:
        if not result.subdocuments:
            st.info("No document splits were produced.")
        else:
            st.dataframe(
                [
                    {
                        "part": item.descriptor.index,
                        "pages": f"{item.descriptor.start_page}-{item.descriptor.end_page}",
                        "type": item.descriptor.profile,
                        "confidence": item.descriptor.confidence,
                    }
                    for item in result.subdocuments
                ],
                hide_index=True,
            )
            selected_subdocument = st.selectbox(
                "Sub-document",
                result.subdocuments,
                format_func=lambda item: (
                    f"{item.descriptor.index:04d} · {item.descriptor.profile} · "
                    f"pages {item.descriptor.start_page}-{item.descriptor.end_page}"
                ),
            )
            sub_stem = Path(selected_subdocument.tree.source_name).stem
            st.download_button(
                "Download sub-document bundle",
                selected_subdocument.bundle,
                file_name=f"{sub_stem}.zip",
                mime="application/zip",
            )
    if "Evaluation" in tabs:
        with tabs["Evaluation"]:
            report = st.session_state["evaluation_report"]
            st.json(report.model_dump(mode="json"), expanded=False)

    with st.container(horizontal=True):
        st.download_button("LLM Markdown", result.llm_markdown, f"{stem}.llm.md", "text/markdown")
        st.download_button("JSON", result.json, f"{stem}.json", "application/json")
        st.download_button("Audit", result.audit_json, f"{stem}.audit.json", "application/json")
        st.download_button("Bundle", result.bundle, f"{stem}.zip", "application/zip")
