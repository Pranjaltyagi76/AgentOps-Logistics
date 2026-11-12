"""Real Gemini smoke test: one scenario, end to end, scored in memory.

Opt-in only: needs GEMINI_API_KEY and RUN_LLM_TESTS=1. Never runs in CI (NFR-11). It uses one
run's worth of free-tier quota (a handful of requests).

    RUN_LLM_TESTS=1 uv run pytest tests/smoke -m llm -s
"""

import json
import os

import pytest

from app.core.config import DEFAULT_DATA_DIR, get_settings
from app.domain.scoring import evaluate
from app.domain.sop_corpus import load_corpus
from app.domain.taxonomy import sop_evidence_id
from app.schemas.agent_config import AgentConfigSpec
from app.schemas.scenario import ScenarioSpec
from app.services.agent_graph.runner import run_scenario
from app.services.evaluation.service import facts_from_result
from app.services.sops.service import SopHit, query_terms

pytestmark = pytest.mark.llm

SCENARIO = "delay_hub_congestion_001.v1.json"


class InMemorySops:
    """Word-overlap search over the SOP files, so the smoke test needs no database."""

    def __init__(self) -> None:
        self.corpus = load_corpus(DEFAULT_DATA_DIR / "sops")

    def search(self, query: str, allowed_slugs: frozenset[str], top_k: int = 3) -> list[SopHit]:
        terms = set(query_terms(query))
        hits = []
        for doc in self.corpus:
            if doc.slug not in allowed_slugs:
                continue
            for section in doc.sections:
                words = set(f"{section.title} {section.text}".lower().split())
                score = len(terms & words)
                if score:
                    hits.append(
                        SopHit(
                            evidence_id=sop_evidence_id(doc.slug, section.id),
                            document_slug=doc.slug,
                            document_title=doc.title,
                            section_id=section.id,
                            section_title=section.title,
                            text=section.text,
                            score=float(score),
                        )
                    )
        return sorted(hits, key=lambda h: -h.score)[:top_k]


@pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1" or get_settings().gemini_api_key is None,
    reason="real Gemini call: set GEMINI_API_KEY and RUN_LLM_TESTS=1 (never in CI)",
)
def test_gemini_completes_one_scenario_end_to_end() -> None:
    settings = get_settings()
    config = AgentConfigSpec.model_validate(
        json.loads((DEFAULT_DATA_DIR / "agents" / "gemini-flash-v1.v1.json").read_text())
    )
    spec = ScenarioSpec.model_validate(
        json.loads((DEFAULT_DATA_DIR / "scenarios" / SCENARIO).read_text(encoding="utf-8"))
    )
    result = run_scenario(spec, config, InMemorySops(), settings=settings)
    evaluation = evaluate(spec, facts_from_result(result))

    print(f"\nmodel={settings.gemini_model} stop={result.stop_reason} steps={result.steps}")
    print(f"tools={[c.tool for c in result.tool_calls]}")
    print(f"usage={result.usage}")
    print(f"outcome={result.outcome.model_dump() if result.outcome else None}")
    print(f"verdict={evaluation.verdict} score={evaluation.score}")
    for error in result.errors:
        print(f"error={error}")

    assert result.stop_reason == "completed", result.errors
    assert result.outcome is not None
    assert result.usage and all(u["input_tokens"] for u in result.usage)
    assert evaluation.verdict != "ERROR"


@pytest.mark.skipif(
    os.environ.get("RUN_LLM_TESTS") != "1" or get_settings().gemini_api_key is None,
    reason="real Gemini call: set GEMINI_API_KEY and RUN_LLM_TESTS=1 (never in CI)",
)
def test_gemini_judge_returns_a_valid_advisory_verdict() -> None:
    """Judges the rule-based-v1 reply (no agent LLM call): one or two Gemini requests."""
    import time

    from app.schemas.agent_config import load_prompt
    from app.services.evaluation.judge import (
        JUDGE_PROMPT_VERSION,
        JUDGE_SCHEMA,
        JudgeVerdict,
        judge_input,
    )
    from app.services.providers.factory import build_judge_provider

    settings = get_settings()
    config = AgentConfigSpec.model_validate(
        json.loads((DEFAULT_DATA_DIR / "agents" / "rule-based-v1.v1.json").read_text())
    )
    spec = ScenarioSpec.model_validate(
        json.loads((DEFAULT_DATA_DIR / "scenarios" / SCENARIO).read_text(encoding="utf-8"))
    )
    facts = facts_from_result(run_scenario(spec, config, InMemorySops(), settings=settings))
    payload = judge_input(spec, facts)
    provider = build_judge_provider(settings)
    raw, usage, served = provider.generate_json(
        load_prompt(JUDGE_PROMPT_VERSION),
        json.dumps(payload),
        JUDGE_SCHEMA,
        deadline=time.monotonic() + 90,
    )
    verdict = JudgeVerdict.model_validate_json(raw)
    print(f"\njudge={served} usage={usage} verdict={verdict.model_dump()}")
    assert 0 <= verdict.score <= 1
