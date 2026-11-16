import jwt
import pytest

from app.core.limits import SlidingWindowLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "s" * 40


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("a-long-password")
    assert hashed.startswith("$argon2id$")
    assert verify_password("a-long-password", hashed)
    assert not verify_password("wrong-password", hashed)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_token_roundtrip() -> None:
    token, _ = create_access_token(
        subject="u1", role="owner", email="o@example.com", secret=SECRET, expires_minutes=5
    )
    claims = decode_access_token(token, SECRET)
    assert (claims.sub, claims.role, claims.email) == ("u1", "owner", "o@example.com")


def test_expired_token_is_rejected() -> None:
    token, _ = create_access_token(
        subject="u1", role="viewer", email=None, secret=SECRET, expires_minutes=-1
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, SECRET)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token, _ = create_access_token(
        subject="u1", role="owner", email=None, secret="x" * 40, expires_minutes=5
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token, SECRET)


def test_sliding_window_limiter() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")


def test_client_ip_counts_trusted_proxies_from_the_right() -> None:
    from types import SimpleNamespace

    from app.core.limits import client_ip

    def request(forwarded: str | None) -> SimpleNamespace:
        headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
        return SimpleNamespace(headers=headers, client=SimpleNamespace(host="10.9.9.9"))

    assert client_ip(request("1.1.1.1, 2.2.2.2"), 0) == "10.9.9.9"  # local: ignore the header
    assert client_ip(request("1.1.1.1, 2.2.2.2"), 1) == "2.2.2.2"
    assert client_ip(request("1.1.1.1, 2.2.2.2, 3.3.3.3"), 2) == "2.2.2.2"
    assert client_ip(request(None), 1) == "10.9.9.9"  # no header: socket peer
    assert client_ip(request(" , "), 1) == "10.9.9.9"


def test_render_commit_is_the_version_sha(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import Settings

    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234")
    assert Settings(_env_file=None).git_sha == "abc1234"  # type: ignore[call-arg]
    monkeypatch.setenv("GIT_SHA", "fromci")
    assert Settings(_env_file=None).git_sha == "fromci"  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_database_urls_use_psycopg3(given: str, expected: str) -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None, database_url=given, migration_database_url=given)  # type: ignore[call-arg]
    assert settings.database_url == expected and settings.alembic_database_url == expected
    assert Settings(_env_file=None, migration_database_url="  ").migration_database_url is None  # type: ignore[call-arg]
