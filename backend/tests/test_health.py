import pytest
from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_db_down_returns_503_envelope(client_db_down: TestClient) -> None:
    response = client_db_down.get("/api/v1/health")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "db_unavailable"
    assert error["details"] == {"db": "unavailable"}
    assert error["request_id"] == response.headers["X-Request-ID"]
    # The underlying driver error must not leak to clients.
    assert "connection refused" not in response.text


def test_version(client: TestClient) -> None:
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    assert response.json() == {
        "name": "AgentOps Logistics API",
        "version": "0.1.0",
        "git_sha": "test-sha",
        "environment": "test",
    }


@pytest.mark.db
def test_health_against_real_database(client_real_db: TestClient) -> None:
    response = client_real_db.get("/api/v1/health")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "db": "ok"}
