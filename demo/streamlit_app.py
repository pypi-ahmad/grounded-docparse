"""Read-only public showcase for Grounded Document Parser."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "native_text_showcase.json"
SHOWCASE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
DOCUMENT = SHOWCASE["document"]
EXTRACTION = SHOWCASE["extraction"]

st.set_page_config(
    page_title="Grounded Document Parser showcase",
    page_icon=":material/document_scanner:",
    layout="wide",
)

st.title("Grounded Document Parser")
st.caption(
    "Explicit document routing with immutable source text, exact spans, and "
    "evidence-backed extraction."
)
st.info(
    "Synthetic read-only demonstration. It accepts no uploads and performs no OCR, "
    "provider calls, network requests, or persistence.",
    icon=":material/shield:",
)

overview_tab, markdown_tab, extraction_tab, structure_tab, json_tab = st.tabs(
    ["Overview", "Markdown", "Extract", "Source structure", "JSON"]
)

with overview_tab:
    st.subheader("Explicit native ingestion")
    source, route, calls = st.columns(3)
    source.metric("Synthetic source", DOCUMENT["source_name"])
    route.metric("Requested route", "Native PDF")
    calls.metric("Provider calls", "0")
    with st.container(border=True):
        st.markdown("**Signature and container:** compatible PDF")
        st.markdown("**Effective route:** native")
        st.markdown("**Parser:** pdf-inspector")
        st.markdown("**OCR fallback:** disabled")
    st.button(
        "Process document",
        icon=":material/play_arrow:",
        type="primary",
        disabled=True,
        help="Execution is disabled in the public showcase.",
    )

with markdown_tab:
    st.subheader("Grounded Markdown")
    st.caption("Rendered from immutable native text in the synthetic fixture.")
    with st.container(border=True):
        st.markdown(SHOWCASE["markdown"])

with extraction_tab:
    st.subheader("Exact evidence-backed extraction")
    st.dataframe(
        [
            {
                "Field": item["pointer"],
                "Value": item["value"],
                "Source text": item["evidence"]["source_text"],
                "Character interval": (
                    f"{item['evidence']['char_interval']['start']}:"
                    f"{item['evidence']['char_interval']['end']}"
                ),
                "Page": item["evidence"]["source_spans"][0]["anchor"]["page"],
            }
            for item in EXTRACTION["values"]
        ],
        hide_index=True,
    )
    st.caption(
        "Each value is an exact substring of base_text and resolves through a "
        "source span to a page anchor."
    )

with structure_tab:
    st.subheader("Source-owned structure")
    st.dataframe(
        [
            {
                "Element": element["id"],
                "Type": element["type"],
                "Reading order": element["reading_order"],
                "Span": f"{element['source']['start']}:{element['source']['end']}",
                "Anchor": element["source"]["anchor"]["kind"],
                "Page": element["source"]["anchor"]["page"],
            }
            for element in DOCUMENT["elements"]
        ],
        hide_index=True,
    )
    st.code(DOCUMENT["base_text"], language="text")

with json_tab:
    st.subheader("Validated result fixture")
    st.json({"document": DOCUMENT, "extraction": EXTRACTION})

with st.container(horizontal=True):
    st.link_button(
        "Code",
        "https://github.com/pypi-ahmad/grounded-docparse/tree/native-document-ingestion",
        icon=":material/code:",
    )
    st.link_button(
        "Setup",
        "https://github.com/pypi-ahmad/grounded-docparse/blob/native-document-ingestion/SETUP.md",
        icon=":material/build:",
    )
    st.link_button(
        "Architecture",
        "https://github.com/pypi-ahmad/grounded-docparse/blob/native-document-ingestion/docs/architecture.md",
        icon=":material/account_tree:",
    )
