import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.auth import current_user
from app.config import get_settings
from app.graph import run_agent
from app.memory import memory
from app.models import ActivityEvent, ChatRequest, ChatResponse, FeedbackRequest, User
from app.retrieval import retriever
from app.security import rate_limiter

structlog.configure(
    processors=[structlog.contextvars.merge_contextvars, structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
logger = structlog.get_logger()
AuthenticatedUser = Annotated[User, Depends(current_user)]
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await memory.initialize()
    await retriever.load()
    await logger.ainfo("application_started", documents=len(retriever.documents))
    yield
    await logger.ainfo("application_stopped")


app = FastAPI(
    title="Enterprise Knowledge AI",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
if settings.app_env == "production":
    app.add_middleware(HTTPSRedirectMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins, allow_credentials=False,
    allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_boundary(request: Request, call_next):
    """Enforce request-size limits and consistent browser-facing security headers."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:100]
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": "Request body too large"},
            headers={"X-Request-ID": request_id},
        )
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": (
                    "default-src 'self' https://cdn.jsdelivr.net; img-src 'self' data:; "
                    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                    "frame-ancestors 'none'"
                ),
                "Cache-Control": "no-store",
            }
        )
        return response
    finally:
        structlog.contextvars.clear_contextvars()


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "healthy", "documents": len(retriever.documents)}


@app.get("/v1/conversations")
async def conversations(user: AuthenticatedUser) -> list[dict[str, str]]:
    rate_limiter.consume(user.username, cost=0.25)
    return await memory.list_sessions(user.username)


@app.get("/v1/conversations/{session_id}")
async def conversation(session_id: str, user: AuthenticatedUser) -> dict[str, object]:
    rate_limiter.consume(user.username, cost=0.25)
    messages = await memory.messages(session_id, user.username)
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"session_id": session_id, "messages": messages}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: AuthenticatedUser) -> ChatResponse:
    rate_limiter.consume(user.username)
    try:
        result = await asyncio.wait_for(run_agent(request, user), timeout=45)
        return ChatResponse(
            answer=result["answer"], session_id=request.session_id,
            citations=result.get("evidence", []), trace_id=result["trace_id"],
            activities=result.get("activities", []),
        )
    except HTTPException:
        raise
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Agent execution timed out") from exc
    except Exception as exc:
        await logger.aexception("agent_failed", user=user.username, error=str(exc))
        raise HTTPException(status_code=503, detail="Assistant temporarily unavailable") from exc


@app.post("/v1/chat/stream")
async def chat_stream(request: ChatRequest, user: AuthenticatedUser) -> EventSourceResponse:
    rate_limiter.consume(user.username)
    queue: asyncio.Queue[ActivityEvent | None] = asyncio.Queue()

    async def sink(event: ActivityEvent) -> None:
        await queue.put(event)

    async def execute() -> None:
        try:
            result = await asyncio.wait_for(run_agent(request, user, sink), timeout=45)
            for token in result["answer"].split():
                await queue.put(ActivityEvent(type="token", node="response", message=token + " "))
                await asyncio.sleep(0.01)
            await queue.put(ActivityEvent(
                type="final", node="response", message=result["answer"],
                data={"citations": [item.model_dump() for item in result.get("evidence", [])],
                      "trace_id": result["trace_id"]},
            ))
        except HTTPException as exc:
            await queue.put(ActivityEvent(type="error", node="system", message=str(exc.detail)))
        except TimeoutError:
            await queue.put(ActivityEvent(type="error", node="system", message="Agent execution timed out"))
        except Exception as exc:  # noqa: BLE001 - sanitize failures at the SSE task boundary
            await logger.aexception("stream_agent_failed", user=user.username, error=str(exc))
            await queue.put(
                ActivityEvent(type="error", node="system", message="Assistant temporarily unavailable")
            )
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(execute())
        while (event := await queue.get()) is not None:
            yield {"event": event.type, "data": json.dumps(event.model_dump())}
        await task

    return EventSourceResponse(events())


@app.post("/v1/feedback", status_code=201)
async def feedback(request: FeedbackRequest, user: AuthenticatedUser) -> dict[str, str]:
    """Capture an auditable answer-quality signal without exposing other users' sessions."""
    rate_limiter.consume(user.username, cost=0.25)
    try:
        await memory.add_feedback(
            request.session_id, user.username, request.rating, request.comment.strip()
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    await logger.ainfo(
        "answer_feedback", user=user.username, session_id=request.session_id, rating=request.rating
    )
    return {"status": "recorded"}
