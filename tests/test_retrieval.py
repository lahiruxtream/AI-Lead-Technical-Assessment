"""Hybrid relevance, access control, and metadata filtering tests."""

import pytest

from app.models import Role, User
from app.retrieval import HybridRetriever


@pytest.mark.asyncio
async def test_hybrid_search_returns_relevant_authorized_document():
    retriever = HybridRetriever()
    user = User(username="viewer", role=Role.VIEWER)
    results = await retriever.search("payment recovery circuit breaker", user)
    assert results
    assert any(item.document_id == "RUN-PAY-001" for item in results)
    assert all(item.metadata["access_level"] != "confidential" for item in results)


@pytest.mark.asyncio
async def test_metadata_filter_is_applied():
    retriever = HybridRetriever()
    user = User(username="viewer", role=Role.VIEWER)
    results = await retriever.search("policy", user, {"department": "security"})
    assert results
    assert all(item.metadata["department"] == "security" for item in results)
