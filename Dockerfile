FROM python:3.11-slim
WORKDIR /workspace
# Allow dependency downloads to survive slow or briefly unstable PyPI connections.
ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# Copy dependency metadata before application code to maximize Docker layer reuse.
COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY ui ./ui
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --prefer-binary --upgrade "pip>=26.2" \
    && python -m pip install --prefer-binary .
# Drop root privileges; only the mounted runtime database directory remains writable.
RUN groupadd --system app && useradd --system --gid app --home-dir /nonexistent app \
    && mkdir -p /workspace/data/runtime \
    && chown -R app:app /workspace/data/runtime
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
