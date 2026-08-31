"""RBAC-protected knowledge, analytics, and enterprise MCP tool implementations."""

import asyncio
from collections import Counter
from typing import Any

import httpx
from langsmith import traceable
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.config import get_settings
from app.models import Evidence, User
from app.retrieval import retriever
from app.security import authorize_tool, sanitize_retrieved_text


@traceable(name="knowledge-search-tool", run_type="tool")
async def knowledge_search(query: str, user: User, filters: dict[str, str]) -> list[Evidence]:
    """Run bounded retrieval and sanitize untrusted document instructions."""

    # Tool-local authorization prevents a compromised/incorrect agent route from bypassing RBAC.
    authorize_tool(user, "knowledge_search")
    evidence = await asyncio.wait_for(retriever.search(query, user, filters), timeout=8)
    # Copy rather than mutate retriever state shared by concurrent requests.
    return [item.model_copy(update={"text": sanitize_retrieved_text(item.text)}) for item in evidence]


@traceable(name="python-analysis-tool", run_type="tool")
async def python_analysis(evidence: list[Evidence], user: User) -> dict[str, Any]:
    """Safe predefined analytics; intentionally does not eval model-generated code."""
    authorize_tool(user, "python_analysis")
    await asyncio.sleep(0)
    # Only predefined aggregation runs here; model-generated code is never evaluated.
    return {
        "documents": len(evidence),
        "by_type": dict(Counter(item.metadata.get("document_type", "unknown") for item in evidence)),
        "by_department": dict(Counter(item.metadata.get("department", "unknown") for item in evidence)),
        "average_relevance": round(sum(item.score for item in evidence) / max(len(evidence), 1), 3),
    }


@traceable(name="enterprise-mcp-tool", run_type="tool")
async def enterprise_mcp(resource: str, user: User) -> dict[str, Any]:
    """Call the authenticated MCP server or return an explicitly labelled fallback."""

    authorize_tool(user, "enterprise_mcp")
    # The allowlist blocks arbitrary MCP resource discovery and server-side URL construction.
    if resource not in {"employee_directory", "service_catalog", "incident_records"}:
        raise ValueError("Unsupported MCP resource")
    settings = get_settings()
    try:
        # Initialize a standards-compliant MCP session over authenticated Streamable HTTP.
        async with (
            httpx.AsyncClient(
                timeout=4,
                headers={"X-MCP-Key": settings.mcp_shared_secret.get_secret_value()},
            ) as client,
            streamable_http_client(
                f"{settings.mcp_url.rstrip('/')}/mcp", http_client=client
            ) as (read_stream, write_stream, _),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "get_enterprise_resource", {"resource": resource}
            )
            if result.isError:
                raise RuntimeError("MCP tool returned an error")
            if result.structuredContent:
                return result.structuredContent
            raise RuntimeError("MCP tool returned no structured content")
    except Exception:  # noqa: BLE001 - SDK/transport failures degrade to labelled local data
        # The fallback is synthetic and explicitly labelled so it cannot be mistaken for live data.
        fallback = {
            "employee_directory": {"payments_on_call": "Nimal Perera", "extension": "4421"},
            "service_catalog": {
                "payments-api": {
                    "owner": "Payments Platform",
                    "tier": 1,
                    "channel": "#pay-ops",
                }
            },
            "incident_records": {"open_sev1": 0, "open_sev2": 1},
        }
        return {"source": "graceful-fallback", "data": fallback[resource]}
