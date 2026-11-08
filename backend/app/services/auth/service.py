"""Owner account management and authentication."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.db.models import User, Workspace

DEFAULT_WORKSPACE_NAME = "Default workspace"
MIN_PASSWORD_LENGTH = 10


def normalize_email(email: str) -> str:
    return email.strip().lower()


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    hashed = user.hashed_password if user is not None and user.is_active else None
    return user if verify_password(password, hashed) else None


def upsert_owner(db: Session, email: str, password: str) -> tuple[User, bool]:
    """Creates the owner (and default workspace) or resets its password. Returns (user, created)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    email = normalize_email(email)
    if "@" not in email:
        raise ValueError("email looks invalid")

    user = db.scalar(select(User).where(User.email == email))
    created = user is None
    if user is None:
        user = User(email=email, hashed_password=hash_password(password), role="owner")
        db.add(user)
        db.flush()
    else:
        user.hashed_password = hash_password(password)
        user.is_active = True

    if db.scalar(select(Workspace).limit(1)) is None:
        db.add(Workspace(name=DEFAULT_WORKSPACE_NAME, owner_user_id=user.id))
    db.commit()
    return user, created
