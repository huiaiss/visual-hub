"""Test API endpoints return expected status codes."""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_endpoint():
    """GET /api/health should return 200."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_factory_page_loads():
    """GET /factory should return 200 with HTML."""
    response = client.get("/factory")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_landing_page_loads():
    """GET / should return 200."""
    response = client.get("/")
    assert response.status_code == 200
