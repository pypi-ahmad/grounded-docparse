from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import streamlit as st

from grounded_docparse import DocumentParser

SUPPORTED_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff"]
TERMINAL = {"completed", "needs_review", "failed", "cancelled"}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, url: str, token: str, **kwargs: object) -> httpx.Response:
    response = httpx.request(method, url, headers=_headers(token), timeout=60, **kwargs)
    response.raise_for_status()
    return response


def _show_source(data: bytes, filename: str) -> None:
    if Path(filename).suffix.casefold() == ".pdf":
        st.pdf(data, height=650, key="source-pdf-preview")
    else:
        st.image(data, caption=filename)


st.set_page_config(page_title="Grounded document parser", layout="wide")
st.session_state.setdefault("jobs", [])
st.session_state.setdefault("local_results", [])
st.title("Grounded document parser")
st.caption("Visually grounded document extraction with auditable citations.")

has_openai_environment = bool(
    os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_BASE_URL")
)
with st.sidebar:
    backend = st.segmented_control(
        "Backend",
        ["Local", "API"],
        default="Local" if has_openai_environment else "API",
    )
    if backend == "API":
        api_url = st.text_input(
            "API URL", value=os.getenv("DOCPARSE_API_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        api_token = st.text_input(
            "API token", value=os.getenv("DOCPARSE_API_TOKEN", ""), type="password"
        )
    else:
        api_url = ""
        api_token = ""
        if has_openai_environment:
            st.caption("Using OPENAI_BASE_URL and OPENAI_API_KEY from the environment.")
        else:
            st.error("Local mode requires OPENAI_BASE_URL and OPENAI_API_KEY.")

mode = st.segmented_control("Mode", ["Parse", "Evaluate"], default="Parse") or "Parse"
first, second, third = st.columns(3)
profile = first.selectbox("Processing profile", ["fast", "balanced", "maximum"], index=1)
execution = second.selectbox(
    "Execution", ["local"] if backend == "Local" else ["realtime", "batch"]
)
segmentation = third.selectbox("Segmentation", ["auto", "off"])

with st.expander("Classification and extraction"):
    taxonomy_text = st.text_area(
        "Declared taxonomy (JSON, optional)",
        placeholder='["invoice", "purchase_order", "contract"]',
    )
    schema_text = st.text_area(
        "Extraction JSON Schema (optional)",
        placeholder='{"type":"object","properties":{},"additionalProperties":false}',
    )

uploads = st.file_uploader(
    "Documents", type=SUPPORTED_TYPES, accept_multiple_files=True, max_upload_size=250
)
if uploads:
    selected = st.selectbox("Preview", uploads, format_func=lambda item: item.name)
    with st.expander("Source preview"):
        _show_source(selected.getvalue(), selected.name)

configuration_error = ""
try:
    taxonomy = json.loads(taxonomy_text) if taxonomy_text.strip() else None
    schema = json.loads(schema_text) if schema_text.strip() else None
except json.JSONDecodeError as exc:
    configuration_error = f"Invalid JSON: {exc.msg}"
    st.error(configuration_error)

if st.button(
    "Submit",
    type="primary",
    icon=":material/upload:",
    disabled=(
        not uploads
        or bool(configuration_error)
        or (backend == "API" and not api_token)
        or (backend == "Local" and not has_openai_environment)
    ),
):
    for upload in uploads:
        try:
            if backend == "Local":
                with st.spinner(f"Parsing {upload.name}"):
                    result = DocumentParser().parse(
                        upload.getvalue(),
                        upload.name,
                        profile=profile,
                        segmentation=segmentation,
                        taxonomy=taxonomy,
                        extraction_schema=schema,
                    )
                st.session_state.local_results.append(
                    {"name": upload.name, "bundle": result.bundle}
                )
            else:
                response = _request(
                    "POST",
                    f"{api_url}/api/v1/jobs",
                    api_token,
                    data={
                        "profile": profile,
                        "execution": execution,
                        "segmentation": segmentation,
                        "taxonomy": json.dumps(taxonomy) if taxonomy is not None else "",
                        "extraction_schema": json.dumps(schema) if schema is not None else "",
                    },
                    files={"file": (upload.name, upload.getvalue(), upload.type)},
                )
                job = response.json()
                if not any(item["id"] == job["id"] for item in st.session_state.jobs):
                    st.session_state.jobs.append(job)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            st.error(f"Could not submit {upload.name}: {exc}")
    st.rerun()

if backend == "Local" and st.session_state.local_results:
    st.subheader("Local results")
    for index, result in enumerate(st.session_state.local_results):
        st.download_button(
            f"Download {result['name']}",
            result["bundle"],
            file_name=f"{Path(result['name']).stem}.zip",
            key=f"local-result-{index}",
        )


@st.fragment(run_every=2)
def job_monitor() -> None:
    if not st.session_state.jobs:
        return
    refreshed = []
    for previous in st.session_state.jobs:
        try:
            job = _request(
                "GET", f"{api_url}/api/v1/jobs/{previous['id']}", api_token
            ).json()
        except (httpx.HTTPError, ValueError):
            job = previous
        refreshed.append(job)
    st.session_state.jobs = refreshed
    st.subheader("Jobs")
    st.dataframe(
        [
            {
                "document": job["source_name"],
                "profile": job["profile"],
                "execution": job["execution"],
                "status": job["status"],
                "error": job.get("error") or "",
            }
            for job in refreshed
        ],
        hide_index=True,
    )
    completed = [job for job in refreshed if job["status"] in {"completed", "needs_review"}]
    if completed:
        chosen = st.selectbox("Result", completed, format_func=lambda item: item["source_name"])
        artifacts = _request(
            "GET", f"{api_url}/api/v1/jobs/{chosen['id']}/artifacts", api_token
        ).json()
        names = artifacts.get("artifacts", artifacts)
        for key in names:
            if key.endswith(".zip"):
                content = _request(
                    "GET",
                    f"{api_url}/api/v1/jobs/{chosen['id']}/artifacts/{key.split('/')[-1]}",
                    api_token,
                ).content
                st.download_button("Download result bundle", content, file_name=Path(key).name)
                break


if backend == "API":
    job_monitor()

if mode == "Evaluate":
    st.info("Evaluation reports are submitted against completed jobs through the API.")
