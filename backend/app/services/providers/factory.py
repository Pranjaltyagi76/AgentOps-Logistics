"""Builds LLM providers from agent configs.

`build_provider` is the only place a provider is constructed. API keys come from settings
(env vars) and are never part of a config, run, trace or response.
"""

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.schemas.agent_config import AgentConfigSpec
from app.services.providers.errors import ProviderNotConfiguredError
from app.services.providers.throttle import RequestThrottle

if TYPE_CHECKING:
    from app.services.providers.gemini import GeminiProvider

DEFAULT_MODEL = "default"
JUDGE_REQUEST_TIMEOUT_S = 40.0

_lock = threading.Lock()
_clients: dict[str, Any] = {}
_throttles: dict[int, RequestThrottle] = {}


def resolve_model_id(config: AgentConfigSpec, settings: Settings) -> str:
    """`model_id: "default"` means "the server's GEMINI_MODEL"; anything else is used as is."""
    if config.provider == "gemini" and config.model_id == DEFAULT_MODEL:
        return settings.gemini_model
    return config.model_id


def provider_problem(config: AgentConfigSpec, settings: Settings) -> str | None:
    """Why this config cannot run on this server, or None if it can."""
    if config.provider == "gemini" and settings.gemini_api_key is None:
        return "Gemini is not configured on this server (GEMINI_API_KEY is not set)"
    if config.provider == "openai":
        return "The OpenAI adapter is not available yet"
    return None


def gemini_throttle(rpm: int) -> RequestThrottle:
    """One throttle per process (per RPM value), shared by every run."""
    with _lock:
        if rpm not in _throttles:
            _throttles[rpm] = RequestThrottle(rpm)
        return _throttles[rpm]


def _gemini_client(api_key: str) -> Any:
    from google import genai  # imported lazily: rule-based-only servers never load the SDK

    with _lock:
        client = _clients.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            _clients[api_key] = client
        return client


def build_provider(
    config: AgentConfigSpec,
    settings: Settings,
    *,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
    client: Any = None,
) -> "GeminiProvider":
    from app.services.providers.gemini import GeminiProvider

    problem = provider_problem(config, settings)
    if problem is not None:
        raise ProviderNotConfiguredError(problem)
    if config.provider != "gemini":
        raise ProviderNotConfiguredError(f"Provider '{config.provider}' has no adapter")
    assert settings.gemini_api_key is not None
    return GeminiProvider(
        client or _gemini_client(settings.gemini_api_key.get_secret_value()),
        resolve_model_id(config, settings),
        throttle=gemini_throttle(settings.gemini_rpm_limit),
        thinking_level=settings.gemini_thinking_level,
        max_retries=config.max_retries,
        request_timeout_s=settings.gemini_request_timeout_s,
        sleep=sleep,
        should_stop=should_stop,
    )


def judge_model_id(settings: Settings) -> str:
    return settings.llm_judge_model or settings.gemini_model


def build_judge_provider(
    settings: Settings,
    *,
    sleep: Callable[[float], None] = time.sleep,
    client: Any = None,
) -> "GeminiProvider":
    """Gemini provider for the advisory LLM judge (one retry; shares the request throttle)."""
    from app.services.providers.gemini import GeminiProvider

    if settings.gemini_api_key is None:
        raise ProviderNotConfiguredError(
            "Gemini is not configured on this server (GEMINI_API_KEY is not set)"
        )
    return GeminiProvider(
        client or _gemini_client(settings.gemini_api_key.get_secret_value()),
        judge_model_id(settings),
        throttle=gemini_throttle(settings.gemini_rpm_limit),
        thinking_level=settings.gemini_thinking_level,
        max_retries=1,
        # Not bound by an agent run's deadline, so it can wait out a slow Gemini longer.
        request_timeout_s=max(settings.gemini_request_timeout_s, JUDGE_REQUEST_TIMEOUT_S),
        sleep=sleep,
    )
