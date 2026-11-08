"""Shared FastAPI dependencies: settings, current principal and role checks."""

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import Role, decode_access_token


def get_app_settings(request: Request) -> Settings:
    """Settings the running app was created with (lets tests inject their own)."""
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]

_bearer = HTTPBearer(auto_error=False)


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


@dataclass(frozen=True)
class Principal:
    subject: str
    role: Role
    email: str | None

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


def get_principal(
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise NotAuthenticatedError("Sign in to access this resource")
    try:
        claims = decode_access_token(
            credentials.credentials, settings.jwt_secret.get_secret_value()
        )
    except jwt.ExpiredSignatureError as exc:
        raise NotAuthenticatedError("Session expired; sign in again", code="token_expired") from exc
    except (jwt.PyJWTError, ValueError) as exc:
        raise NotAuthenticatedError("Invalid access token", code="invalid_token") from exc
    return Principal(subject=claims.sub, role=claims.role, email=claims.email)


def require_owner(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if not principal.is_owner:
        raise ForbiddenError("This action requires the owner account")
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]
OwnerDep = Annotated[Principal, Depends(require_owner)]
