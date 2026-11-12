"""Stores and reads failure reports (FR-07).

`store_diagnosis` is called by the evaluation service right after it scores a run, in the same
transaction, so a stored evaluation always has a matching diagnosis.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import EvaluationResult, FailureReport
from app.domain.diagnosis_rules import Diagnosis


@dataclass(frozen=True)
class StoredReport:
    evaluation: EvaluationResult
    status: str  # diagnosed | no_failures | not_diagnosed | pending
    items: list[FailureReport]


def store_diagnosis(db: Session, evaluation: EvaluationResult, diagnosis: Diagnosis) -> None:
    db.execute(
        delete(FailureReport).where(
            FailureReport.evaluation_id == evaluation.id,
            FailureReport.diagnoser_version == diagnosis.version,
        )
    )
    for position, item in enumerate(diagnosis.items):
        db.add(
            FailureReport(
                run_id=evaluation.run_id,
                evaluation_id=evaluation.id,
                diagnoser_version=diagnosis.version,
                evaluator_version=evaluation.evaluator_version,
                position=position,
                is_primary=item.primary,
                failure_type=item.failure_type.value,
                severity=item.severity,
                likely_stage=item.stage,
                confidence=item.confidence,
                assertion_ids=item.assertion_ids,
                trace_refs=item.trace_refs,
                summary=item.summary,
                diagnosis=item.diagnosis,
                debugging_recommendation=item.recommendation,
                evidence_json=item.evidence,
            )
        )
    evaluation.diagnoser_version = diagnosis.version


def report_for(db: Session, evaluation: EvaluationResult) -> StoredReport:
    if evaluation.diagnoser_version is None:
        return StoredReport(evaluation, "pending", [])
    items = list(
        db.scalars(
            select(FailureReport)
            .where(
                FailureReport.evaluation_id == evaluation.id,
                FailureReport.diagnoser_version == evaluation.diagnoser_version,
            )
            .order_by(FailureReport.position)
        )
    )
    if items:
        status = "diagnosed"
    elif evaluation.verdict == "ERROR":
        status = "not_diagnosed"
    else:
        status = "no_failures"
    return StoredReport(evaluation, status, items)
