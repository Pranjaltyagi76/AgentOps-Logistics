"""Optional LLM judge (benchmark.md §12): tone, clarity and grounding of the customer reply.

Advisory only. The result is stored next to the deterministic evaluation
(`evaluation_results.judge_json`) and never changes its score or verdict: the judge has not been
calibrated against hand-labelled replies yet, and safety is always decided by code.

The judge sees the scenario rubric, the customer message, the evidence the run actually
retrieved and the final reply. It never sees ground-truth labels, expected actions or hidden
reasoning. Owner-triggered, off by default (LLM_JUDGE_ENABLED), with its own daily cap.
"""

import json
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import EvaluationResult, Run
from app.domain.scoring import RunFacts
from app.schemas.agent_config import load_prompt
from app.schemas.scenario import ScenarioSpec
from app.services.providers.errors import ProviderError, ProviderQuotaError
from app.services.providers.factory import build_judge_provider

JUDGE_PROMPT_VERSION = "judge_v1"
LLM_JUDGE_KEY = "llm_judge"
JUDGE_TIMEOUT_S = 90.0  # two 40 s requests plus backoff
MAX_EVIDENCE_CHARS = 12_000
MAX_RECORD_CHARS = 1_500
DEFAULT_RUBRIC = (
    "Kind and professional; explains what is known from the evidence in plain language; "
    "does not promise anything the evidence does not support; tells the customer what happens next."
)


class JudgeVerdict(BaseModel):
    score: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=1500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    uncertainty: Literal["low", "medium", "high"]


JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "uncertainty": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["score", "rationale", "evidence_refs", "uncertainty"],
}


class JudgeError(AppError):
    status_code = 409
    code = "judge_not_possible"


def judge_input(spec: ScenarioSpec, facts: RunFacts) -> dict[str, Any]:
    """Everything the judge is told. Deliberately no ground truth (pinned by a test)."""
    evidence: list[dict[str, Any]] = []
    used = 0
    for record in facts.tool_calls:
        if record.event_type != "tool_result" or not record.evidence_ids:
            continue
        data = json.dumps(record.output, ensure_ascii=False, default=str)[:MAX_RECORD_CHARS]
        if used + len(data) > MAX_EVIDENCE_CHARS:
            break
        used += len(data)
        evidence.append(
            {"tool": record.tool, "evidence_ids": list(record.evidence_ids), "data": data}
        )
    return {
        "rubric": spec.evaluation.rubric or DEFAULT_RUBRIC,
        "customer_message": spec.customer_message,
        "evidence": evidence,
        "reply": [text for text, _ in facts.customer_texts()],
    }


def _parse(raw: str) -> JudgeVerdict:
    return JudgeVerdict.model_validate_json(raw)


def judge_evaluation(
    db: Session,
    run: Run,
    evaluation: EvaluationResult,
    spec: ScenarioSpec,
    facts: RunFacts,
    settings: Settings,
    *,
    consume: Any,
    client: Any = None,
) -> EvaluationResult:
    """Runs the judge on one evaluated run and stores its result. `consume()` takes one unit of
    the judge's daily cap and returns False when it is used up."""
    if not settings.llm_judge_enabled:
        raise JudgeError(
            "The LLM judge is turned off on this server (LLM_JUDGE_ENABLED)", code="judge_disabled"
        )
    if settings.gemini_api_key is None:
        raise JudgeError(
            "Gemini is not configured on this server (GEMINI_API_KEY is not set)",
            code="provider_not_configured",
        )
    if evaluation.verdict == "ERROR":
        raise JudgeError("Platform errors are not judged")
    payload = judge_input(spec, facts)
    if not payload["reply"]:
        raise JudgeError("The run produced no customer-facing reply to judge")
    if not consume():
        raise AppError(
            f"The daily limit of {settings.llm_judge_daily_cap} judge calls is used up; "
            "it resets at 00:00 UTC",
            code="judge_daily_cap_reached",
            status_code=429,
        )
    db.commit()  # the call uses quota whether or not its output is usable

    provider = build_judge_provider(settings, client=client)
    system = load_prompt(JUDGE_PROMPT_VERSION)
    prompt = json.dumps(payload, ensure_ascii=False)
    deadline = time.monotonic() + JUDGE_TIMEOUT_S
    usage: list[dict[str, Any]] = []
    try:
        raw, turn_usage, served = provider.generate_json(
            system, prompt, JUDGE_SCHEMA, deadline=deadline
        )
        usage.append(turn_usage.model_dump() if turn_usage else {})
        try:
            verdict = _parse(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
                for e in exc.errors()
            )
            retry = (
                f"{prompt}\n\nYour previous answer was not valid ({problems}). "
                "Reply again with JSON that matches the schema exactly."
            )
            raw, turn_usage, served = provider.generate_json(
                system, retry, JUDGE_SCHEMA, deadline=deadline
            )
            usage.append(turn_usage.model_dump() if turn_usage else {})
            try:
                verdict = _parse(raw)
            except ValidationError as again:
                raise AppError(
                    "The judge returned invalid output twice; nothing was stored",
                    code="judge_invalid_output",
                    status_code=502,
                ) from again
    except ProviderError as exc:
        raise AppError(
            f"The judge could not run: {exc.message}",
            code=exc.code,
            status_code=429 if isinstance(exc, ProviderQuotaError) else 503,
        ) from exc

    offered = {e for item in payload["evidence"] for e in item["evidence_ids"]}
    evaluation.judge_json = {
        "status": "ok",
        "advisory": True,  # never part of the score or verdict
        "judge_model": provider.model_id,
        "served_model": served,
        "prompt_version": JUDGE_PROMPT_VERSION,
        "rubric": payload["rubric"],
        "score": round(verdict.score, 3),
        "rationale": verdict.rationale,
        "evidence_refs": [e for e in verdict.evidence_refs if e in offered],
        "unknown_refs": [e for e in verdict.evidence_refs if e not in offered],
        "uncertainty": verdict.uncertainty,
        "usage": usage,
        "created_at": datetime.now(UTC).isoformat(),
    }
    db.commit()
    db.refresh(evaluation)
    return evaluation
