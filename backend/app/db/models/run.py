"""Runs, their trace events, and daily usage counters (Phase 4).

A run executes one agent config version against one scenario version. `status` is the
execution state; `verdict`, `score` and `policy_failed` are filled by the evaluator (Phase 5).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
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

RUN_STATUSES = ("queued", "running", "completed", "timed_out", "cancelled", "errored")
ACTIVE_STATUSES = ("queued", "running")


class Run(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_status_created_at", "status", "created_at"),
        Index("ix_runs_created_at", "created_at"),
        Index("ix_runs_suite_run_id", "suite_run_id"),
        Index("ix_runs_agent_config_id", "agent_config_id"),
        Index("ix_runs_scenario_id", "scenario_id"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    agent_config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="RESTRICT"), nullable=False
    )
    suite_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suite_runs.id", ondelete="SET NULL"), nullable=True
    )
    repeat_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Time spent waiting for the LLM request throttle: platform delay, not agent time (Phase 8).
    throttle_wait_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Denormalised for listing; the rows above are immutable once a run uses them.
    scenario_key: Mapped[str] = mapped_column(String(80), nullable=False)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)

    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    stop_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)  # agent | infra
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    final_outcome_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actions_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # Evaluation (Phase 5)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    score: Mapped[float | None] = mapped_column(nullable=True)
    policy_failed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Reproducibility (NFR-08): exact config used and component versions.
    config_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    versions_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    triggered_by_role: Mapped[str] = mapped_column(String(10), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


class TraceEvent(UUIDPrimaryKey, Base):
    __tablename__ = "trace_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_trace_events_run_seq"),
        Index("ix_trace_events_run_id", "run_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # referenced as "te:<seq>"
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    node_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    input_json: Mapped[Any] = mapped_column(JSONB, nullable=True)
    output_json: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evidence_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UsageCounter(UUIDPrimaryKey, Base):
    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("day", "key", name="uq_usage_counters_day_key"),)

    day: Mapped[date] = mapped_column(Date, nullable=False)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
