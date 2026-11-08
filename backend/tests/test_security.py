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
