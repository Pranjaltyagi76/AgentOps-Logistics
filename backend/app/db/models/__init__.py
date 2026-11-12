"""Import every model so Base.metadata is complete (Alembic autogenerate relies on it)."""

from app.db.models.agent_config import AgentConfig
from app.db.models.document import Document, DocumentChunk
from app.db.models.evaluation import EvaluationResult
from app.db.models.failure_report import FailureReport
from app.db.models.run import Run, TraceEvent, UsageCounter
from app.db.models.scenario import Scenario
from app.db.models.suite import BenchmarkSuite, SuiteMembership, SuiteRun
from app.db.models.user import User, Workspace

__all__ = [
    "AgentConfig",
    "BenchmarkSuite",
    "Document",
    "DocumentChunk",
    "EvaluationResult",
    "FailureReport",
    "Run",
    "Scenario",
    "SuiteMembership",
    "SuiteRun",
    "TraceEvent",
    "UsageCounter",
    "User",
    "Workspace",
]
