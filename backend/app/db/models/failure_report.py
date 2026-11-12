"""Failure reports (FR-07): one row per diagnosed failure item of an evaluation.

Rows belong to one evaluation result (so to one evaluator version) and one diagnoser version.
Re-diagnosing replaces the rows for that pair. Whether an evaluation has been diagnosed at all
(including "no failures") is recorded on `evaluation_results.diagnoser_version`.
"""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import CreatedAt, UUIDPrimaryKey


class FailureReport(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "failure_reports"
    __table_args__ = (
        Index("ix_failure_reports_run_id", "run_id"),
        Index("ix_failure_reports_failure_type", "failure_type"),
        Index("ix_failure_reports_evaluation_id", "evaluation_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_results.id", ondelete="CASCADE"), nullable=False
    )
    diagnoser_version: Mapped[str] = mapped_column(String(20), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    likely_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    assertion_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    trace_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)  # viewer-safe
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)  # owner only
    debugging_recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # owner only
