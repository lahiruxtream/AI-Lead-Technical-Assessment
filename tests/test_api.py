from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


def test_chat_requires_authentication():
    with TestClient(app) as client:
        response = client.post("/v1/chat", json={"message": "hello", "session_id": "test"})
        assert response.status_code == 401
