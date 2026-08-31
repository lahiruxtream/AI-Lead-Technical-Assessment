"""API boundary tests for health, authentication, validation, and request limits."""

from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"


def test_chat_requires_authentication():
    with TestClient(app) as client:
        response = client.post("/v1/chat", json={"message": "hello", "session_id": "test"})
        assert response.status_code == 401


def test_unsupported_filter_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            auth=("viewer", "viewer123"),
            json={"message": "policy", "session_id": "secure-test", "filters": {"owner": "x"}},
        )
        assert response.status_code == 422


def test_oversized_request_is_rejected_before_parsing():
    with TestClient(app) as client:
        response = client.post(
            "/v1/chat",
            content=b"x" * 20_000,
            headers={"Content-Type": "application/json", "Authorization": "Basic invalid"},
        )
        assert response.status_code == 413
