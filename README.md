# Enterprise Knowledge AI Assistant

An enterprise-grade proof of concept built for the Lead AI technical assessment. It combines a transparent LangGraph workflow, hybrid retrieval, recursive analysis, role-based tool access, prompt-injection defenses, session memory, LangSmith observability, and graceful local fallbacks.

## What is included

- **FastAPI backend** with async APIs and Server-Sent Events (SSE)
- **Streamlit chat UI** with a live agent activity panel
- **LangGraph orchestration**: guardrail, supervisor, retrieval, research/RLM, response, validation, and memory nodes
- **Hybrid RAG**: BM25-style sparse scoring + dense embeddings, reciprocal weighted fusion, metadata filters, document attribution, and optional Pinecone
- **Recursive Language Model pattern**: plan, partition evidence, analyze batches, and aggregate results
- **Security**: hardcoded demo authentication, RBAC at the tool boundary, prompt-injection checks, tool parameter validation, citation validation, and token-bucket rate limiting
- **Tools**: knowledge search, safe structured analysis, and a dummy enterprise MCP server
- **Observability**: structured JSON logs, per-request event stream, and LangSmith tracing through LangChain/LangGraph environment configuration
- **Deployment**: Docker Compose, health checks, sample documents, tests, and an architecture diagram
- **Quality loop**: user-isolated positive/negative feedback persisted for offline evaluation

## Quick start

### Docker (recommended)

```bash
copy .env.example .env
docker compose up --build
```

Open Streamlit at <http://localhost:8501>. The API is at <http://localhost:8000/docs>.

### Local Python

Python 3.11+ is required.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
python scripts/ingest.py
uvicorn app.main:app --reload --env-file .env
```

In another terminal:

```bash
streamlit run ui/streamlit_app.py
```

## Demo users

| Username | Password | Role | Access |
|---|---|---|---|
| `viewer` | `viewer123` | Viewer | chat and search |
| `analyst` | `analyst123` | Analyst | search, analysis, MCP |
| `admin` | `admin123` | Administrator | all tools |

These environment-configurable credentials have development defaults for the assessment POC. Replace them with an identity provider for production.

For production set `APP_ENV=production` and replace every demo password plus `MCP_SHARED_SECRET`. Startup fails if known development/placeholder secrets remain. Terminate TLS at a trusted reverse proxy and configure `ALLOWED_HOSTS` and `ALLOWED_ORIGINS` exactly.

## Configuration

The app runs without cloud credentials using deterministic local embeddings and an extractive answer fallback. For full operation set:

- `OPENAI_API_KEY` — LLM answers and embeddings
- `PINECONE_API_KEY`, `PINECONE_INDEX` — managed vector retrieval
- `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_TRACING_V2=true` — LangSmith traces

See [.env.example](.env.example) for every setting.

## Example questions

- `What is the payment service recovery procedure?`
- `Summarize payment outages in 2025 and identify recurring root causes.`
- `Who owns the payments service?` (Analyst/Admin; invokes MCP)
- `Compare incident severity and calculate counts by root cause.` (Analyst/Admin)

## API

Authenticate with HTTP Basic auth.

```bash
curl -u viewer:viewer123 http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What caused payment outages?","session_id":"demo"}'
```

Streaming endpoint: `POST /v1/chat/stream`. Event types include `state`, `tool`, `retrieval`, `memory`, `validation`, `token`, `final`, and `error`.

Feedback endpoint: `POST /v1/feedback` with `session_id`, a `rating` of `1` or `-1`, and an optional comment.

## Design decisions and trade-offs

- Pinecone is the production vector store; the in-memory store is deliberate so evaluators can run the POC immediately.
- Sparse and dense ranks are normalized before weighted fusion (`0.55 dense / 0.45 sparse`). A production deployment should add a hosted cross-encoder reranker.
- Memory and chat history are user-isolated and persisted in SQLite for the POC. Redis/Postgres plus encrypted retention policies are the production path.
- RLM recursion is bounded by batch size and depth, preventing unbounded cost or butterfly-effect failures.
- Retrieved documents are treated as untrusted data. They never become system instructions, and citations are checked against retrieved document IDs.
- Authentication is Basic + hardcoded users solely because Option A is explicitly permitted. Password hashes, OAuth/OIDC, TLS, and a secrets manager are required in production.

More detail is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/SECURITY.md](docs/SECURITY.md), and [docs/DEMO.md](docs/DEMO.md).
The complete assessment-to-implementation mapping is in [docs/REQUIREMENTS_TRACEABILITY.md](docs/REQUIREMENTS_TRACEABILITY.md).

## Tests

```bash
pytest
```

## Submission notes

The source and architecture deliverables are included. Publishing the repository and recording/uploading the 45-minute demo require the candidate's own GitHub/video accounts; use `docs/DEMO.md` as the recording script.
