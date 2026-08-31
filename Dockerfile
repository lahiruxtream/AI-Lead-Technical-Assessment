FROM python:3.11-slim
WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY ui ./ui
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2" \
    && python -m pip install --no-cache-dir .
RUN groupadd --system app && useradd --system --gid app --home-dir /nonexistent app \
    && mkdir -p /workspace/data/runtime \
    && chown -R app:app /workspace/data/runtime
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
