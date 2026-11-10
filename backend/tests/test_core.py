from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import redact


def test_settings_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db.example:5432/x")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example ,")
    settings = Settings(_env_file=None)
    assert settings.is_production
    assert settings.database_url.endswith("db.example:5432/x")
    assert settings.cors_origin_list == ["https://a.example", "https://b.example"]
    assert settings.alembic_database_url == settings.database_url


def test_production_requires_a_real_jwt_secret(monkeypatch) -> None:
    import pytest
    from pydantic import ValidationError

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)


def test_migration_url_overrides_database_url() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@pooled/x",
        migration_database_url="postgresql+psycopg://u:p@direct/x",
    )
    assert settings.alembic_database_url.endswith("@direct/x")


def test_request_id_is_echoed_when_valid(client: TestClient) -> None:
    response = client.get("/api/v1/version", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_request_id_is_replaced_when_malformed(client: TestClient) -> None:
    response = client.get("/api/v1/version", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(response.headers["X-Request-ID"]) == 32


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    allowed = client.get("/api/v1/version", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    blocked = client.get("/api/v1/version", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


def test_redact_masks_secrets() -> None:
    line = (
        "key=AIza" + "A" * 35 + " auth=Bearer eyJhbGciOi.payload.sig "
        "url=postgresql+psycopg://agentops:s3cret@host/db password=hunter2"
    )
    masked = redact(line)
    assert "AIza" not in masked
    assert "eyJhbGciOi" not in masked
    assert "s3cret" not in masked
    assert "hunter2" not in masked
    assert "postgresql+psycopg://agentops:***@host/db" in masked


def test_blank_jwt_secret_falls_back_to_dev_default_outside_production(monkeypatch) -> None:
    from app.core.config import DEV_JWT_SECRET

    monkeypatch.setenv("JWT_SECRET", "")
    assert Settings(_env_file=None).jwt_secret.get_secret_value() == DEV_JWT_SECRET


def test_oversized_request_bodies_are_rejected(test_settings) -> None:
    from app.main import create_app

    app = create_app(test_settings.model_copy(update={"max_request_bytes": 1_000}))
    with TestClient(app) as small:
        response = small.post("/api/v1/auth/login", content=b"x" * 5_000)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"
        assert response.headers["X-Request-ID"]

        def chunks():
            yield b"{" + b" " * 3_000  # no Content-Length: counted while streaming
            yield b"}"

        streamed = small.post("/api/v1/auth/login", content=chunks())
        assert streamed.status_code == 413
        normal = small.post("/api/v1/auth/demo")
        assert normal.status_code == 200
