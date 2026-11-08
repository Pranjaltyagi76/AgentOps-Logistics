"""Shared fixtures. Unit tests never need a real database; `db`-marked tests do."""

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.db.session import get_db
from app.main import create_app


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_DB_TESTS") == "1":
        return
    skip_db = pytest.mark.skip(reason="needs PostgreSQL; set RUN_DB_TESTS=1 (runs in CI)")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)


class FakeSession:
    """Minimal stand-in for a SQLAlchemy Session used by the health check."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def execute(self, *_: Any, **__: Any) -> None:
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def close(self) -> None:
        pass


@pytest.fixture
def test_settings() -> Settings:
    return Settings(app_env="test", git_sha="test-sha", cors_origins="http://localhost:5173")


def _client(settings: Settings, session: FakeSession | None) -> Iterator[TestClient]:
    app = create_app(settings)
    if session is not None:

        def override_db() -> Iterator[FakeSession]:
            yield session

        app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """App whose database is a healthy fake."""
    yield from _client(test_settings, FakeSession())


@pytest.fixture
def client_db_down(test_settings: Settings) -> Iterator[TestClient]:
    """App whose database is unreachable."""
    yield from _client(test_settings, FakeSession(fail=True))


@pytest.fixture
def client_real_db(test_settings: Settings) -> Iterator[TestClient]:
    """App wired to the real DATABASE_URL (use only in `db`-marked tests)."""
    yield from _client(test_settings, None)
