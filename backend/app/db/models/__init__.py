"""Import every model so Base.metadata is complete (Alembic autogenerate relies on it)."""

from app.db.models.scenario import Scenario
from app.db.models.user import User, Workspace

__all__ = ["Scenario", "User", "Workspace"]
