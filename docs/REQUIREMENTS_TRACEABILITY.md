# Assessment requirements traceability

This matrix makes the proof-of-concept scope and evidence explicit. The demo video is intentionally not produced in this repository.

| Requirement | Implementation evidence | Status / limitation |
|---|---|---|
| Streamlit chat, multi-turn, streaming, activity panel | `ui/streamlit_app.py`, `/v1/chat/stream` | Implemented with live LLM token streaming plus SSE lifecycle events |
| Async FastAPI, retrieval, tools, errors, JSON logging | `app/main.py`, `app/retrieval.py`, `app/tools.py` | Implemented; external failures degrade or return sanitized errors |
| LangGraph specialized agents | `app/graph.py` | Guardrail, supervisor, retrieval, research, response, validation, memory nodes |
| RLM / recursive exploration | `research_node` in `app/graph.py` | Visible Python plan, targeted filtering, bounded partitioning, traced concurrent batch sub-agents, aggregation |
| Dense + BM25 hybrid search and ranking | `app/retrieval.py` | OpenAI semantic embeddings with Pinecone plus deterministic offline dense fallback; weighted fusion |
| Pinecone namespaces and metadata filtering | `app/retrieval.py`, `scripts/ingest.py` | Enabled when credentials/index are supplied |
| Document attribution | `Evidence` model, response prompt, citation validator | Implemented and surfaced in UI |
| Conversation memory | `app/memory.py` | User-isolated SQLite history survives restarts; bounded context loading |
| Knowledge, MCP, Python tools | `app/tools.py`, `app/mcp_server.py` | Implemented with authenticated MCP Streamable HTTP transport and read-only allowlisted data |
| LLM and rationale | `app/llm.py`, `docs/ARCHITECTURE.md` | OpenAI when configured; grounded extractive fallback otherwise |
| LangSmith observability | LangGraph run config, `@traceable` tool/retriever/sub-agent spans, `.env.example` | Conversation, transitions, model, tool, retrieval, and RLM batch traces when credentials are set |
| Prompt injection and exfiltration defense | `app/security.py`, system prompt | Layered pattern checks, untrusted-context instruction, output validation |
| Input/tool/content validation and guardrails | Pydantic models, tool allowlists, retrieval ACL, citation validation | Implemented at deterministic boundaries |
| Authentication and RBAC | `app/auth.py`, `authorize_tool` | Assignment Option A hardcoded demo users; production caveat documented |
| Token-bucket rate limits | `TokenBucketLimiter` | Per-user and configurable |
| Graceful LLM/vector/MCP/timeout failures | `app/main.py`, `app/retrieval.py`, `app/tools.py` | Sanitized 503/504, local vector and labelled MCP fallbacks |
| Sample documents | `data/documents/` | Policies, incidents, architecture, runbook, product, confidential fixture |
| Architecture diagram | `docs/ARCHITECTURE.md` | Mermaid source renders on GitHub |
| Multi-agent failure containment | `docs/ARCHITECTURE.md`, bounded concurrent batches | Implemented |
| Long-term memory and quality feedback | SQLite conversations and `/v1/feedback` | Implemented for POC/offline evaluation |
| Container deployment | `Dockerfile`, `docker-compose.yml` | API, UI, and enterprise data service |
| Public repository | Git remote/publishing instructions | Must be published through the candidate's GitHub account |
| Demo video and public URL | `docs/DEMO.md` | Recording script only; video intentionally excluded by request |

## Assumptions and trade-offs

- The solution prioritizes transparent orchestration, access control, grounding, and runnable local behavior over a polished UI.
- External credentials are not committed. Pinecone, OpenAI, and LangSmith activate through environment variables.
- Pinecone uses the configured OpenAI embedding model; its index dimension must match that model. The local feature-hash vector is only a deterministic availability fallback.
- All current tools are read-only, so a human approval node would add ceremony without risk reduction. Add approval before any future mutating tool.
- The feedback signal is stored for offline evaluation; production should add moderation, deduplication, dashboards, and a reviewed prompt/retrieval improvement workflow.
