import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.mcp_server import app, get_enterprise_resource


def test_mcp_transport_requires_shared_secret():
    with TestClient(app) as client:
        assert client.get("/resources/service_catalog").status_code == 401
        headers = {"X-MCP-Key": get_settings().mcp_shared_secret.get_secret_value()}
        assert client.get("/mcp", headers=headers).status_code != 401


@pytest.mark.asyncio
async def test_mcp_tool_exposes_only_allowlisted_resources():
    response = await get_enterprise_resource("service_catalog")
    assert response["source"] == "enterprise-mcp"
    with pytest.raises(ValueError, match="Unsupported"):
        await get_enterprise_resource("not-real")
