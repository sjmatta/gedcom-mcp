FROM ghcr.io/astral-sh/uv:0.12.17 AS uv
FROM python:3.13-slim
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY gedcom_server ./gedcom_server
RUN uv sync --locked --no-dev && mkdir -p /data /cache && chown 1000:1000 /data /cache
ENV PATH="/app/.venv/bin:$PATH" HF_HOME=/cache/huggingface
USER 1000:1000
CMD ["python", "-m", "gedcom_server.http"]
