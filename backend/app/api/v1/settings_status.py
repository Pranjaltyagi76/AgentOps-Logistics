"""Read-only settings status: providers, limits, today's usage and component versions.

Never reveals secrets: provider keys are reported only as configured / not configured.
Today's usage is owner-only (viewers cannot launch LLM runs anyway).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import PrincipalDep, SettingsDep
from app.db.session import get_db
from app.domain.comparison import COMPARISON_VERSION
from app.domain.diagnosis_rules import DIAGNOSER_VERSION
from app.domain.metrics import METRICS_VERSION
from app.domain.policy import POLICY_VERSION
from app.domain.scoring import EVALUATOR_VERSION
from app.domain.taxonomy import TAXONOMY_VERSION
from app.services.evaluation.judge import JUDGE_PROMPT_VERSION, LLM_JUDGE_KEY
from app.services.execution.service import LLM_RUNS_KEY, usage_today
from app.services.providers.factory import judge_model_id
from app.services.tools.registry import TOOL_REGISTRY_VERSION

router = APIRouter(prefix="/settings", tags=["settings"])


class GeminiStatus(BaseModel):
    configured: bool
    model: str
    thinking_level: str
    requests_per_minute: int
    request_timeout_s: float


class JudgeStatus(BaseModel):
    enabled: bool
    model: str
    prompt_version: str
    advisory: bool


class Limits(BaseModel):
    llm_runs_per_day: int
    judge_calls_per_day: int
    concurrent_runs: int
    concurrent_llm_runs: int
    queued_runs: int
    run_launches_per_minute: int
    request_body_bytes: int


class UsageToday(BaseModel):
    llm_runs: int
    judge_calls: int


class SettingsStatusOut(BaseModel):
    app_version: str
    environment: str
    gemini: GeminiStatus
    judge: JudgeStatus
    limits: Limits
    usage_today: UsageToday | None  # owner only
    versions: dict[str, str]


@router.get("/status", response_model=SettingsStatusOut)
def settings_status(
    settings: SettingsDep, principal: PrincipalDep, db: Annotated[Session, Depends(get_db)]
) -> SettingsStatusOut:
    gemini_ready = settings.gemini_api_key is not None
    return SettingsStatusOut(
        app_version=__version__,
        environment=settings.app_env,
        gemini=GeminiStatus(
            configured=gemini_ready,
            model=settings.gemini_model,
            thinking_level=settings.gemini_thinking_level,
            requests_per_minute=settings.gemini_rpm_limit,
            request_timeout_s=settings.gemini_request_timeout_s,
        ),
        judge=JudgeStatus(
            enabled=settings.llm_judge_enabled and gemini_ready,
            model=judge_model_id(settings),
            prompt_version=JUDGE_PROMPT_VERSION,
            advisory=True,
        ),
        limits=Limits(
            llm_runs_per_day=settings.llm_daily_run_cap,
            judge_calls_per_day=settings.llm_judge_daily_cap,
            concurrent_runs=settings.max_concurrent_runs,
            concurrent_llm_runs=settings.max_concurrent_llm_runs,
            queued_runs=settings.max_queued_runs,
            run_launches_per_minute=settings.run_rate_limit_per_minute,
            request_body_bytes=settings.max_request_bytes,
        ),
        usage_today=(
            UsageToday(
                llm_runs=usage_today(db, LLM_RUNS_KEY),
                judge_calls=usage_today(db, LLM_JUDGE_KEY),
            )
            if principal.is_owner
            else None
        ),
        versions={
            "evaluator": EVALUATOR_VERSION,
            "diagnoser": DIAGNOSER_VERSION,
            "metrics": METRICS_VERSION,
            "comparison": COMPARISON_VERSION,
            "policy": POLICY_VERSION,
            "taxonomy": TAXONOMY_VERSION,
            "tool_registry": TOOL_REGISTRY_VERSION,
            "judge_prompt": JUDGE_PROMPT_VERSION,
        },
    )
