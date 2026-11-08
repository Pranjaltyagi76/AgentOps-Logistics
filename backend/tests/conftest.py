"""Shared fixtures.

Unit tests never need a real database. `db`-marked tests run only with RUN_DB_TESTS=1 and use
TEST_DATABASE_URL (environment or backend/.env), falling back to an explicit DATABASE_URL in the
environment (CI). They never fall back to the default development database. Each test runs
inside a transaction that is rolled back, so the database is left unchanged.
"""

import copy
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_DATA_DIR, Settings, get_settings
from app.db.session import get_db
from app.domain.sop_catalog import SopCatalog, get_catalog
from app.main import create_app
from app.services.auth.service import upsert_owner

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCENARIO_DIR = DEFAULT_DATA_DIR / "scenarios"
OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "correct-horse-battery"


def _test_database_url() -> str | None:
    """A separate test DB (TEST_DATABASE_URL), else an explicit DATABASE_URL env var (CI)."""
    return (
        os.environ.get("TEST_DATABASE_URL")
        or dotenv_values(BACKEND_DIR / ".env").get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("RUN_DB_TESTS") == "1":
        return
    skip_db = pytest.mark.skip(reason="needs PostgreSQL; set RUN_DB_TESTS=1 (runs in CI)")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip_db)


# --- Fakes for unit tests ------------------------------------------------------------------


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
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        git_sha="test-sha",
        cors_origins="http://localhost:5173",
        database_url=_test_database_url() or Settings(_env_file=None).database_url,  # type: ignore[call-arg]
    )


def _client(settings: Settings, session: Any | None) -> Iterator[TestClient]:
    app = create_app(settings)
    if session is not None:

        def override_db() -> Iterator[Any]:
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


# --- Scenario fixtures ---------------------------------------------------------------------


@pytest.fixture(scope="session")
def catalog() -> SopCatalog:
    return get_catalog(DEFAULT_DATA_DIR)


@pytest.fixture(scope="session")
def scenario_files() -> dict[str, dict[str, Any]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SCENARIO_DIR.glob("*.json"))
    }


@pytest.fixture
def make_scenario(scenario_files: dict[str, dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Deep copy of a real scenario file, optionally renamed: make_scenario(key="x_001")."""

    def factory(name: str = "delay_hub_congestion_001.v1.json", **overrides: Any) -> dict[str, Any]:
        data = copy.deepcopy(scenario_files[name])
        if "key" in overrides:
            data["scenario_id"] = overrides.pop("key")
        data.update(overrides)
        return data

    return factory


# --- Real database ------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = _test_database_url()
    if url is None:
        pytest.skip("set TEST_DATABASE_URL (an empty test database) to run db tests locally")
    # Alembic's env.py reads app settings; point it at the test DB just for the upgrade.
    previous = os.environ.get("MIGRATION_DATABASE_URL")
    os.environ["MIGRATION_DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "app/db/migrations"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = previous
        get_settings.cache_clear()
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def api(test_settings: Settings, db_session: Session) -> Iterator[TestClient]:
    """App bound to the rolled-back test transaction."""
    yield from _client(test_settings, db_session)


@pytest.fixture
def owner_headers(api: TestClient, db_session: Session) -> dict[str, str]:
    upsert_owner(db_session, OWNER_EMAIL, OWNER_PASSWORD)
    response = api.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def viewer_headers(api: TestClient) -> dict[str, str]:
    response = api.post("/api/v1/auth/demo")
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
