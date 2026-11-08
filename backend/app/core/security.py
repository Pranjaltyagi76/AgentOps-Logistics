"""Password hashing (Argon2id) and JWT bearer tokens (decision D-14)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel

Role = Literal["owner", "viewer"]

_JWT_ALGORITHM = "HS256"
_JWT_ISSUER = "agentops-logistics"
_hasher = PasswordHasher()

# Verified against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return _hasher.verify(hashed or _DUMMY_HASH, password) and hashed is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


class TokenClaims(BaseModel):
    sub: str  # user id for owners, "demo" for viewers
    role: Role
    email: str | None = None
    exp: datetime
    jti: str


def create_access_token(
    *, subject: str, role: Role, email: str | None, secret: str, expires_minutes: int
) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "email": email,
        "exp": expires_at,
        "iat": datetime.now(UTC),
        "iss": _JWT_ISSUER,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM), expires_at


def decode_access_token(token: str, secret: str) -> TokenClaims:
    """Raises jwt.PyJWTError (expired, bad signature, malformed) or ValueError (bad claims)."""
    payload = jwt.decode(
        token,
        secret,
        algorithms=[_JWT_ALGORITHM],
        issuer=_JWT_ISSUER,
        options={"require": ["exp", "sub", "iss"]},
    )
    payload["exp"] = datetime.fromtimestamp(payload["exp"], tz=UTC)
    return TokenClaims.model_validate(payload)
