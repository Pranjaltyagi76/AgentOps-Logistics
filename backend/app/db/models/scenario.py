"""Scenario versions. One row per (scenario_key, version); a row used by a run is locked."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import CreatedAt, UUIDPrimaryKey


class Scenario(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        UniqueConstraint("scenario_key", "version", name="uq_scenarios_key_version"),
        Index("ix_scenarios_category", "category"),
        Index("ix_scenarios_status", "status"),
        Index("ix_scenarios_tags", "tags", postgresql_using="gin"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    scenario_key: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    scenario_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Set when a run uses this version (Phase 4); locked versions are never edited in place.
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
