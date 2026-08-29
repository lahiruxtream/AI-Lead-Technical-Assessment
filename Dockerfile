FROM python:3.11-slim
WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY ui ./ui
RUN pip install --no-cache-dir .
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
