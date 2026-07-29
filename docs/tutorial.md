# Tutorial

1. Optionally set `OPENAI_API_KEY` for Luna recovery/refinement; set `OPENAI_BASE_URL` only for a compatible custom endpoint.
2. Run `uv sync --locked`, then `uv run streamlit run streamlit_app.py`.
3. Upload one PDF or image and select **Parse document**.
4. Review the classification, TOC, Markdown, token totals, and annotated PDF.
5. For extraction, enable **Schema extract**, open **Manage schemas**, create or import a schema, and save it.
6. Open **Extract**, select **Run extraction**, and use **Show source** to inspect the highlighted GLM box.
7. Leave the default **Fast** mode for classification-only analysis, choose **Full** for refinement plus classification and TOC, or adjust individual toggles for **Custom**.
8. After parsing, open **Extract**, define or load the desired field keys, and select **Run extraction**. Extraction is always on demand.
9. Enable **Document chat** to ask grounded questions. Chat is off by default, runs only when a question is submitted, and cited answers expose **Show source**.
10. Download Markdown, the annotated PDF, Extract JSON when available, or Full JSON.

Readable draft text remains when verification is inconclusive. Agentic JSON preserves its state and reason; only explicitly rejected content is suppressed.
