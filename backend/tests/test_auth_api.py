import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.auth.service import upsert_owner
from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD

pytestmark = pytest.mark.db


def test_owner_login_and_me(api: TestClient, db_session: Session) -> None:
    upsert_owner(db_session, OWNER_EMAIL, OWNER_PASSWORD)
    response = api.post(
        "/api/v1/auth/login", json={"email": "  Owner@Example.com ", "password": OWNER_PASSWORD}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "owner" and body["token_type"] == "bearer"

    me = api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json() == {"role": "owner", "email": OWNER_EMAIL}


def test_wrong_password_and_unknown_email_get_the_same_error(
    api: TestClient, db_session: Session
) -> None:
    upsert_owner(db_session, OWNER_EMAIL, OWNER_PASSWORD)
    wrong = api.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": "nope-nope-nope"}
    )
    unknown = api.post("/api/v1/auth/login", json={"email": "who@example.com", "password": "x"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "invalid_credentials"


def test_demo_login_issues_a_viewer_token(api: TestClient) -> None:
    body = api.post("/api/v1/auth/demo").json()
    me = api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json() == {"role": "viewer", "email": None}


def test_missing_and_invalid_tokens(api: TestClient) -> None:
    assert api.get("/api/v1/auth/me").json()["error"]["code"] == "not_authenticated"
    bad = api.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_token"


def test_login_is_rate_limited(api: TestClient) -> None:
    codes = [
        api.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "x"}).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert codes[-1] == 429


def test_owner_password_must_be_long_enough(db_session: Session) -> None:
    with pytest.raises(ValueError, match="at least"):
        upsert_owner(db_session, OWNER_EMAIL, "short")
