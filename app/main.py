import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.auth import current_user
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    await memory.initialize()
    await retriever.load()
    await logger.ainfo("application_started", documents=len(retriever.documents))
    yield
    await logger.ainfo("application_stopped")


app = FastAPI(title="Enterprise Knowledge AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"], allow_credentials=True,
    allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "healthy", "documents": len(retriever.documents)}


@app.get("/v1/conversations")
async def conversations(user: AuthenticatedUser) -> list[dict[str, str]]:
    return await memory.list_sessions(user.username)


@app.get("/v1/conversations/{session_id}")
async def conversation(session_id: str, user: AuthenticatedUser) -> dict[str, object]:
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
