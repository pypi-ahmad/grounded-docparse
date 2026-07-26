FROM ghcr.io/astral-sh/uv:0.8.15 AS uv
FROM python:3.13.7-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY streamlit_app.py ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app
CMD ["uvicorn", "grounded_docparse.server:app", "--host", "0.0.0.0", "--port", "8000"]
