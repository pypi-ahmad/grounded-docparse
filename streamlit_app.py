from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import streamlit as st

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
st.title("Grounded document parser")
st.caption("Asynchronous, visually grounded document extraction with auditable citations.")

with st.sidebar:
    api_url = st.text_input(
        "API URL", value=os.getenv("DOCPARSE_API_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    api_token = st.text_input(
        "API token", value=os.getenv("DOCPARSE_API_TOKEN", ""), type="password"
    )

mode = st.segmented_control("Mode", ["Parse", "Evaluate"], default="Parse") or "Parse"
first, second, third = st.columns(3)
profile = first.selectbox("Processing profile", ["fast", "balanced", "maximum"], index=1)
execution = second.selectbox("Execution", ["realtime", "batch"])
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
    disabled=not uploads or not api_token or bool(configuration_error),
):
    for upload in uploads:
        try:
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
        except (httpx.HTTPError, ValueError) as exc:
            st.error(f"Could not submit {upload.name}: {exc}")
    st.rerun()


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


job_monitor()

if mode == "Evaluate":
    st.info("Evaluation reports are submitted against completed jobs through the API.")
