# Tutorial

1. Set `OPENAI_API_KEY`; set `OPENAI_BASE_URL` only for a compatible custom endpoint.
2. Run `uv sync --locked`, then `uv run streamlit run streamlit_app.py`.
3. Upload one PDF or image and select **Parse document**.
4. Review actual token totals, Markdown, agentic or legacy JSON, the agent trace, and the annotated PDF.
5. To extract fields, open **Extract**, describe the desired fields, and select **Generate schema**.
6. Review or edit the JSON Schema, then select **Run extraction**.
7. Inspect extracted data and its evidence before downloading the extraction JSON.

Readable draft text remains when verification is inconclusive. Agentic JSON preserves its state and reason; only explicitly rejected content is suppressed.
