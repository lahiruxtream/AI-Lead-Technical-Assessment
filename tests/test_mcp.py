from fastapi.testclient import TestClient

from app.config import get_settings
from app.mcp_server import app


def test_mcp_rejects_missing_credential():
    with TestClient(app) as client:
        assert client.get("/resources/service_catalog").status_code == 401


def test_mcp_accepts_shared_secret_and_rejects_unknown_resource():
    headers = {"X-MCP-Key": get_settings().mcp_shared_secret.get_secret_value()}
    with TestClient(app) as client:
        response = client.get("/resources/service_catalog", headers=headers)
        assert response.status_code == 200
        assert response.json()["source"] == "enterprise-mcp"
        assert client.get("/resources/not-real", headers=headers).status_code == 404
