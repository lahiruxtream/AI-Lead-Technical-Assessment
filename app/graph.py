"""LangGraph orchestration for guarded retrieval, recursive research, and response flow."""

import asyncio
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import traceable

from app.llm import generate_answer
from app.memory import memory
from app.models import ActivityEvent, Evidence, Role, User
from app.security import validate_citations, validate_prompt, validate_sensitive_output
from app.tools import enterprise_mcp, knowledge_search, python_analysis

EventSink = Callable[[ActivityEvent], Awaitable[None]]


class AgentState(TypedDict, total=False):
    """Shared typed state passed between specialized graph nodes."""

    question: str
    session_id: str
    user: User
    filters: dict[str, str]
    intent: str
    search_plan: dict[str, Any]
    evidence: list[Evidence]
    context: str
    analysis: str
    answer: str
    citations_valid: bool
    activities: list[ActivityEvent]
    event_sink: EventSink
    trace_id: str


async def emit(state: AgentState, event_type: str, node: str, message: str, **data: Any) -> None:
    """Record an activity and immediately forward it to an optional SSE event sink."""

    event = ActivityEvent(type=event_type, node=node, message=message, data=data)
    state.setdefault("activities", []).append(event)
    sink = state.get("event_sink")
    if sink:
        await sink(event)


async def guardrail_node(state: AgentState) -> dict[str, Any]:
    """Reject malicious input before memory, retrieval, models, or tools are invoked."""

    await emit(state, "state", "guardrail", "Validating user request")
    validate_prompt(state["question"])
    await emit(state, "validation", "guardrail", "Input validation passed")
    return {}


async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """Classify intent and load bounded, user-isolated conversational context."""

    await emit(state, "state", "supervisor", "Understanding intent and routing task")
    text = state["question"].lower()
    # Deterministic routing keeps the POC explainable and avoids an extra classification LLM call.
    if any(word in text for word in ("who owns", "employee", "service catalog", "on call")):
        intent = "mcp"
    elif any(word in text for word in ("summarize all", "recurring", "compare", "trend", "root cause")):
        intent = "research"
    else:
        intent = "search"
    # Ownership is checked inside memory.context; cross-user history can never enter the prompt.
    turns = await memory.context(state["session_id"], state["user"].username)
    context = "\n".join(f"User: {turn.question}\nAssistant: {turn.answer}" for turn in turns)
    await emit(state, "memory", "supervisor", f"Loaded {len(turns)} previous turns")
    return {"intent": intent, "context": context}


async def retrieval_node(state: AgentState) -> dict[str, Any]:
    """Invoke authorized hybrid retrieval and expose provenance through activity events."""

    await emit(state, "tool", "retrieval", "Executing hybrid knowledge search", tool="knowledge_search")
    evidence = await knowledge_search(state["question"], state["user"], state.get("filters", {}))
    await emit(
        state, "retrieval", "retrieval", f"Retrieved {len(evidence)} authorized documents",
        documents=[{"id": item.document_id, "score": item.score} for item in evidence],
    )
    return {"evidence": evidence}


async def research_node(state: AgentState) -> dict[str, Any]:
    """Execute MCP routing or a bounded RLM-style map-reduce investigation."""

    intent = state["intent"]
    evidence = state.get("evidence", [])
    if intent == "mcp":
        # Authorization is repeated inside the MCP tool, not trusted to this routing decision.
        await emit(state, "tool", "research", "Calling enterprise MCP service", tool="enterprise_mcp")
        result = await enterprise_mcp("service_catalog", state["user"])
        return {"analysis": f"Enterprise service catalog result: {result}"}
    if intent != "research":
        return {"analysis": ""}

    # Convert the natural-language request into a visible, bounded Python execution plan.
    year_match = re.search(r"\b(20\d{2})\b", state["question"])
    plan = {
        "strategy": "python-bounded-map-reduce",
        "operations": ["filter", "partition", "analyze_subagents", "aggregate"],
        "document_type": "incident" if "outage" in state["question"].lower() else None,
        "year": year_match.group(1) if year_match else None,
        "batch_size": 2,
        "max_depth": 1,
    }
    # Targeting happens before partitioning so irrelevant evidence does not consume sub-agent work.
    if plan["document_type"]:
        evidence = [
            item for item in evidence if item.metadata.get("document_type") == plan["document_type"]
        ]
    if plan["year"]:
        evidence = [
            item for item in evidence if str(item.metadata.get("created_date", "")).startswith(plan["year"])
        ]
    await emit(
        state,
        "state",
        "research",
        "Created bounded Python search and map-reduce plan",
        plan=plan,
    )
    # Fixed-size partitions cap context growth and reduce one bad document's blast radius.
    batches = [evidence[index : index + 2] for index in range(0, len(evidence), 2)]

    @traceable(name="rlm-batch-subagent", run_type="chain")
    async def analyze_batch(index: int, batch: list[Evidence]) -> str:
        """Act as one bounded sub-agent over an isolated evidence partition."""

        await emit(
            state, "tool", "research", f"Analyzing recursive batch {index + 1}/{len(batches)}",
            documents=[item.document_id for item in batch], depth=1,
        )
        causes: list[str] = []
        for item in batch:
            match = re.search(r"root cause:\s*([^\n.]+)", item.text, re.IGNORECASE)
            causes.append(match.group(1).strip() if match else item.metadata.get("category", "unspecified"))
        return f"Batch {index + 1}: " + ", ".join(causes)

    # Independent partitions run concurrently; aggregation waits until every bounded task finishes.
    findings = await asyncio.gather(*(analyze_batch(i, batch) for i, batch in enumerate(batches)))
    analysis = "; ".join(findings)
    if state["user"].role in {Role.ANALYST, Role.ADMIN}:
        analytics = await python_analysis(evidence, state["user"])
        await emit(
            state, "tool", "research", "Aggregating recursive findings", tool="python_analysis"
        )
        analysis += f". Structured metrics: {analytics}"
    else:
        await emit(
            state,
            "validation",
            "research",
            "Viewer-safe evidence synthesis used; analytics tool was not authorized",
        )
    return {"analysis": analysis, "search_plan": plan, "evidence": evidence}


async def response_node(state: AgentState) -> dict[str, Any]:
    """Generate a grounded answer while forwarding model tokens to streaming clients."""

    await emit(state, "state", "response", "Generating grounded final response")

    async def stream_token(token: str) -> None:
        """Forward tokens without retaining every token in persistent activity history."""

        sink = state.get("event_sink")
        if sink:
            await sink(ActivityEvent(type="token", node="response", message=token))

    answer = await generate_answer(
        state["question"],
        state.get("evidence", []),
        state.get("context", ""),
        state.get("analysis", ""),
        stream_token if state.get("event_sink") else None,
    )
    return {"answer": answer}


async def validation_node(state: AgentState) -> dict[str, Any]:
    """Block sensitive output and remove citations that lack retrieved provenance."""

    # Validation is deterministic and runs after generation but before persistence or final delivery.
    valid, invalid = validate_citations(state["answer"], state.get("evidence", []))
    output_safe = validate_sensitive_output(state["answer"])
    if not output_safe:
        answer = "I cannot return this response because the output security policy rejected it."
    elif not valid:
        answer = re.sub(r"\[(?:" + "|".join(map(re.escape, invalid)) + r")\]", "", state["answer"])
    else:
        answer = state["answer"]
    await emit(
        state, "validation", "validation", "Citation and response validation completed",
        valid=valid and output_safe, invalid_citations=invalid, output_safe=output_safe,
    )
    return {"answer": answer, "citations_valid": valid and output_safe}


async def memory_node(state: AgentState) -> dict[str, Any]:
    """Persist the completed, validated turn only after all safety checks pass."""

    citations = [item.model_dump() for item in state.get("evidence", [])]
    await memory.add(
        state["session_id"], state["user"].username, state["question"], state["answer"],
        json.dumps(citations),
    )
    await emit(state, "memory", "memory", "Conversation memory updated")
    return {}


def build_graph():
    """Compile the deterministic specialized-agent topology used by every request."""

    graph = StateGraph(AgentState)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("research", research_node)
    graph.add_node("response", response_node)
    graph.add_node("validation", validation_node)
    graph.add_node("memory", memory_node)
    # A fixed edge sequence guarantees guardrails precede every data/model/tool interaction.
    graph.add_edge(START, "guardrail")
    graph.add_edge("guardrail", "supervisor")
    graph.add_edge("supervisor", "retrieval")
    graph.add_edge("retrieval", "research")
    graph.add_edge("research", "response")
    graph.add_edge("response", "validation")
    graph.add_edge("validation", "memory")
    graph.add_edge("memory", END)
    return graph.compile()


agent_graph = build_graph()


async def run_agent(request: Any, user: User, sink: EventSink | None = None) -> AgentState:
    """Create isolated request state and asynchronously execute one traced graph run."""

    state: AgentState = {
        "question": request.message,
        "session_id": request.session_id,
        "filters": request.filters,
        "user": user,
        "activities": [],
        "event_sink": sink,
        "trace_id": str(uuid.uuid4()),
    }
    return await agent_graph.ainvoke(
        state,
        config={"run_name": "enterprise-assistant", "tags": [user.role.value, user.username]},
    )
