"""Evaluation results (FR-06). One row per (run, evaluator version): re-scoring a run with a
new evaluator version adds a row and never rewrites the old one (benchmark.md §11)."""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import CreatedAt, UUIDPrimaryKey


class EvaluationResult(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "evaluator_version", name="uq_evaluation_results_run_version"),
        Index("ix_evaluation_results_run_id", "run_id"),
        Index("ix_evaluation_results_verdict", "verdict"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    evaluator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float | None] = mapped_column(nullable=True)
    task_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pass_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    score_breakdown_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    assertions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    policy_violations_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # Optional LLM judge output (Phase 7); stored separately from deterministic results.
    judge_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Set once failure_reports rows exist for this evaluation (also when there were no failures).
    diagnoser_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
