"""Owner login, passwordless demo-viewer login and the current-session endpoint."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import PrincipalDep, SettingsDep
from app.core.errors import AppError
from app.core.limits import SlidingWindowLimiter
from app.core.security import Role, create_access_token
from app.db.session import get_db
from app.services.auth.service import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])

DEMO_SUBJECT = "demo"


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: str
    role: Role
    email: str | None


class MeOut(BaseModel):
    role: Role
    email: str | None


def _limiter(request: Request) -> SlidingWindowLimiter:
    limiter: SlidingWindowLimiter | None = getattr(request.app.state, "login_limiter", None)
    if limiter is None:
        limiter = SlidingWindowLimiter(request.app.state.settings.login_rate_limit_per_minute)
        request.app.state.login_limiter = limiter
    return limiter


def _issue(settings: SettingsDep, subject: str, role: Role, email: str | None) -> TokenOut:
    token, expires_at = create_access_token(
        subject=subject,
        role=role,
        email=email,
        secret=settings.jwt_secret.get_secret_value(),
        expires_minutes=settings.jwt_expire_minutes,
    )
    return TokenOut(access_token=token, expires_at=expires_at.isoformat(), role=role, email=email)


@router.post("/login", response_model=TokenOut)
def login(
    body: LoginIn,
    request: Request,
    settings: SettingsDep,
    db: Annotated[Session, Depends(get_db)],
) -> TokenOut:
    client = request.client.host if request.client else "unknown"
    if not _limiter(request).allow(f"login:{client}"):
        raise AppError(
            "Too many sign-in attempts; wait a minute", code="rate_limited", status_code=429
        )
    user = authenticate(db, body.email, body.password)
    if user is None:
        raise AppError(
            "Email or password is incorrect", code="invalid_credentials", status_code=401
        )
    return _issue(settings, str(user.id), "owner", user.email)


@router.post("/demo", response_model=TokenOut)
def demo_login(settings: SettingsDep) -> TokenOut:
    if not settings.demo_login_enabled:
        raise AppError("Demo login is disabled", code="demo_disabled", status_code=403)
    return _issue(settings, DEMO_SUBJECT, "viewer", None)


@router.get("/me", response_model=MeOut)
def me(principal: PrincipalDep) -> MeOut:
    return MeOut(role=principal.role, email=principal.email)
