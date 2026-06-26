"""Tests for the health and system endpoints (verifies the app boots and routes)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_ok(client: TestClient) -> None:
    """The liveness probe returns 200 and a status payload."""

    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_components(client: TestClient) -> None:
    """The readiness probe returns an aggregate report with component statuses."""

    response = client.get("/api/v1/health/ready")
    # 200 (healthy/degraded) or 503 (unhealthy) - both are valid shapes here.
    assert response.status_code in (200, 503)
    body = response.json()
    assert "status" in body
    assert isinstance(body["components"], list)
    names = {c["name"] for c in body["components"]}
    assert {"database", "storage"} <= names


def test_system_info(client: TestClient) -> None:
    """The system info endpoint reports version and active adapters."""

    response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Project Olympus API"
    assert "adapters" in body
    assert body["adapters"]["storage"] == "local"


def test_request_id_header_echoed(client: TestClient) -> None:
    """Every response carries a correlation id header."""

    response = client.get("/api/v1/health/live")
    assert response.headers.get("X-Request-ID")
