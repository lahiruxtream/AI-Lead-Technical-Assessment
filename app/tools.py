import asyncio
from collections import Counter
from typing import Any

import httpx

from app.config import get_settings
from app.models import Evidence, User
from app.retrieval import retriever
from app.security import authorize_tool


async def knowledge_search(query: str, user: User, filters: dict[str, str]) -> list[Evidence]:
    authorize_tool(user, "knowledge_search")
    return await asyncio.wait_for(retriever.search(query, user, filters), timeout=8)


async def python_analysis(evidence: list[Evidence], user: User) -> dict[str, Any]:
    """Safe predefined analytics; intentionally does not eval model-generated code."""
    authorize_tool(user, "python_analysis")
    await asyncio.sleep(0)
    return {
        "documents": len(evidence),
        "by_type": dict(Counter(item.metadata.get("document_type", "unknown") for item in evidence)),
        "by_department": dict(Counter(item.metadata.get("department", "unknown") for item in evidence)),
        "average_relevance": round(sum(item.score for item in evidence) / max(len(evidence), 1), 3),
    }


async def enterprise_mcp(resource: str, user: User) -> dict[str, Any]:
    authorize_tool(user, "enterprise_mcp")
    if resource not in {"employee_directory", "service_catalog", "incident_records"}:
        raise ValueError("Unsupported MCP resource")
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(f"{get_settings().mcp_url}/resources/{resource}")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, asyncio.TimeoutError):
        fallback = {
            "employee_directory": {"payments_on_call": "Nimal Perera", "extension": "4421"},
            "service_catalog": {"payments-api": {"owner": "Payments Platform", "tier": 1}},
            "incident_records": {"open_sev1": 0, "open_sev2": 1},
        }
        return {"source": "graceful-fallback", "data": fallback[resource]}
