"""Gemini adapter for the agent graph (official `google-genai` SDK).

What it does:
- converts the graph's provider-neutral messages and JSON-schema tool specs to Gemini contents
  and function declarations;
- asks for as little thinking as the model allows and never for thought text
  (`include_thoughts=False`), and drops any part flagged as a thought anyway (decision D-11);
- keeps Gemini 3 "thought signatures" (opaque tokens that must be sent back with later turns)
  in memory for this run only: they never enter the messages, the trace or the database;
- throttles requests per minute, retries transient errors with backoff and maps failures to
  typed `ProviderError`s.

One `GeminiProvider` instance serves one run; the client and throttle are shared.
"""

import copy
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from google.genai import errors as genai_errors
from google.genai import types

from app.services.agent_graph.schemas import ModelTurn, ToolCallRequest, Usage
from app.services.providers.errors import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    ProviderQuotaError,
    ProviderUnavailableError,
)
from app.services.providers.throttle import RequestThrottle

logger = logging.getLogger(__name__)

BACKOFF_S = (1.0, 4.0)
MAX_RETRY_AFTER_S = 20.0
# Gemini rejects shorter per-request deadlines (400 "Minimum allowed deadline is 10s").
MIN_REQUEST_TIMEOUT_S = 10.0
MAX_OUTPUT_TOKENS = 4096
# Throttle waits are platform delay, not agent time; one wait never needs more than a window.
MAX_THROTTLE_WAIT_S = 65.0
NOT_EXECUTED = {"ok": False, "code": "not_executed", "message": "This call was not executed."}


# --- request building ------------------------------------------------------------------------


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replaces local `$ref`s with their `$defs` entries (Pydantic emits them for enums)."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = copy.deepcopy(defs[ref.removeprefix("#/$defs/")])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**target, **extra})
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    result: dict[str, Any] = resolve(schema)
    return result


def to_function_declarations(tools: list[dict[str, Any]]) -> list[types.FunctionDeclaration]:
    return [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool.get("description", ""),
            parameters_json_schema=inline_refs(tool.get("parameters") or {"type": "object"}),
        )
        for tool in tools
    ]


def thinking_config(model_id: str, level: str) -> types.ThinkingConfig:
    if model_id.startswith("gemini-2.5"):  # predates thinking levels
        return types.ThinkingConfig(thinking_budget=0, include_thoughts=False)
    return types.ThinkingConfig(thinking_level=level, include_thoughts=False)  # type: ignore[arg-type]


def _response_body(content: Any) -> dict[str, Any]:
    try:
        body = json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        body = content
    return body if isinstance(body, dict) else {"result": body}


def _rebuilt_model_parts(message: dict[str, Any]) -> list[types.Part]:
    parts: list[types.Part] = []
    if message.get("content"):
        parts.append(types.Part(text=message["content"]))
    for call in message.get("tool_calls") or []:
        args = call.get("arguments")
        parts.append(
            types.Part(
                function_call=types.FunctionCall(
                    name=call["name"], args=args if isinstance(args, dict) else {"value": args}
                )
            )
        )
    return parts


def _fill_missing_responses(contents: list[types.Content]) -> None:
    """Every function call needs a response in the next user turn; add placeholders if not."""
    for index, content in enumerate(contents):
        if content.role != "model" or index + 1 >= len(contents):
            continue
        calls = [p.function_call.name for p in content.parts or [] if p.function_call]
        following = contents[index + 1]
        if following.role != "user":
            following = types.Content(role="user", parts=[])
            contents.insert(index + 1, following)
        answered = [p.function_response.name for p in following.parts or [] if p.function_response]
        missing: list[types.Part] = []
        for name in calls:
            if name in answered:
                answered.remove(name)
            else:
                missing.append(types.Part.from_function_response(name=name, response=NOT_EXECUTED))
        if missing:
            following.parts = [*missing, *(following.parts or [])]


def to_contents(
    messages: list[dict[str, Any]],
    model_turns: list[list[types.Part]],
    native_ids: set[str],
) -> tuple[str | None, list[types.Content]]:
    """Graph messages -> (system instruction, Gemini contents).

    The n-th assistant message is replayed from `model_turns[n]` when available, so the
    model's thought signatures go back to it exactly as it sent them.
    """
    system: list[str] = []
    contents: list[types.Content] = []
    assistant_index = 0

    def add_user_part(part: types.Part) -> None:
        if contents and contents[-1].role == "user":
            contents[-1].parts = [*(contents[-1].parts or []), part]
        else:
            contents.append(types.Content(role="user", parts=[part]))

    for message in messages:
        role = message.get("role")
        if role == "system":
            if message.get("content"):
                system.append(message["content"])
        elif role == "user":
            add_user_part(types.Part(text=message.get("content") or ""))
        elif role == "assistant":
            if assistant_index < len(model_turns):
                parts = model_turns[assistant_index]
            else:
                parts = _rebuilt_model_parts(message)
            assistant_index += 1
            contents.append(types.Content(role="model", parts=list(parts) or [types.Part(text="")]))
        elif role == "tool":
            call_id = message.get("tool_call_id")
            add_user_part(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=call_id if call_id in native_ids else None,
                        name=message.get("name") or "",
                        response=_response_body(message.get("content")),
                    )
                )
            )
    _fill_missing_responses(contents)
    return ("\n\n".join(system) or None), contents


# --- response parsing ------------------------------------------------------------------------


def parse_response(
    response: types.GenerateContentResponse, turn_number: int, fallback_model: str
) -> tuple[ModelTurn, list[types.Part], set[str]]:
    """Returns the visible turn, the parts to replay next time, and Gemini-issued call IDs.

    Thought parts are dropped here and never leave this function.
    """
    candidate = response.candidates[0] if response.candidates else None
    raw_parts = (candidate.content.parts if candidate and candidate.content else None) or []
    texts: list[str] = []
    calls: list[ToolCallRequest] = []
    replay: list[types.Part] = []
    native: set[str] = set()
    for index, part in enumerate(raw_parts):
        if part.thought:
            continue
        signature = part.thought_signature
        if part.function_call is not None:
            fc = part.function_call
            call_id = fc.id or f"call_{turn_number}_{index}"
            if fc.id:
                native.add(fc.id)
            calls.append(ToolCallRequest(id=call_id, name=fc.name or "", arguments=fc.args or {}))
            replay.append(
                types.Part(
                    function_call=types.FunctionCall(id=fc.id, name=fc.name, args=fc.args or {}),
                    thought_signature=signature,
                )
            )
        elif part.text is not None or signature is not None:
            if part.text:
                texts.append(part.text)
            replay.append(types.Part(text=part.text or "", thought_signature=signature))
    meta = response.usage_metadata
    usage = (
        Usage(
            input_tokens=meta.prompt_token_count,
            output_tokens=meta.candidates_token_count,
            thinking_tokens=meta.thoughts_token_count,
        )
        if meta is not None
        else None
    )
    turn = ModelTurn(
        text="".join(texts).strip() or None,
        tool_calls=calls,
        usage=usage,
        model_id=response.model_version or fallback_model,
    )
    return turn, replay, native


# --- errors ----------------------------------------------------------------------------------

_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s")


def classify_error(exc: BaseException) -> ProviderError | None:
    """Maps SDK/network exceptions to typed provider errors; None means "not a provider error"."""
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, genai_errors.APIError):
        code = exc.code
        message = f"Gemini {code} {exc.status or ''}: {exc.message or ''}".strip()
        if code == 429:
            return ProviderQuotaError(message, status=code)
        if code in (401, 403) or (code == 400 and "api key" in (exc.message or "").lower()):
            return ProviderAuthError(message, status=code)
        if code in (408, 499) or code >= 500:
            return ProviderUnavailableError(message, status=code)
        return ProviderBadRequestError(message, status=code)
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return ProviderUnavailableError(f"Gemini request timed out: {exc}")
    if isinstance(exc, httpx.TransportError | ConnectionError):
        return ProviderUnavailableError(f"Gemini network error: {exc}")
    return None


def retry_after_s(exc: BaseException) -> float | None:
    details = getattr(exc, "details", None)
    match = _RETRY_DELAY.search(str(details)) if details is not None else None
    return float(match.group(1)) if match else None


# --- provider --------------------------------------------------------------------------------


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        client: Any,
        model_id: str,
        *,
        throttle: RequestThrottle,
        thinking_level: str = "minimal",
        max_retries: int = 2,
        request_timeout_s: float = 30.0,
        function_calling_mode: str = "ANY",
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        should_stop: Callable[[], bool] = lambda: False,
        on_pause: Callable[[float], None] = lambda seconds: None,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.throttle = throttle
        self.thinking_level = thinking_level
        self.max_retries = max_retries
        self.request_timeout_s = request_timeout_s
        self.function_calling_mode = function_calling_mode
        self._sleep = sleep
        self._clock = clock
        self._should_stop = should_stop
        self._on_pause = on_pause
        self.throttle_wait_s = 0.0  # excluded from the agent's time limit
        # Per-run memory, never persisted: replay parts (with thought signatures) per model turn.
        self._model_turns: list[list[types.Part]] = []
        self._native_ids: set[str] = set()
        self.request_count = 0

    def _config(
        self, system: str | None, tools: list[dict[str, Any]], temperature: float, timeout_s: float
    ) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=to_function_declarations(tools))],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=self.function_calling_mode  # type: ignore[arg-type]
                )
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=temperature,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=thinking_config(self.model_id, self.thinking_level),
            http_options=types.HttpOptions(timeout=round(timeout_s * 1000)),
        )

    def _request(self, call: Callable[[float], Any], deadline: float | None) -> Any:
        """Throttle, per-request timeout, retries with backoff and error mapping for one call.

        `call(timeout_s)` performs the SDK request.
        """
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            waited = self.throttle.acquire(
                sleep=self._sleep, should_stop=self._should_stop, max_wait_s=MAX_THROTTLE_WAIT_S
            )
            if waited:
                self.throttle_wait_s += waited
                self._on_pause(waited)
                if deadline is not None:
                    deadline += waited
            timeout_s = self.request_timeout_s
            if deadline is not None:
                timeout_s = max(MIN_REQUEST_TIMEOUT_S, min(timeout_s, deadline - self._clock()))
            self.request_count += 1
            try:
                return call(timeout_s)
            except Exception as exc:
                error = classify_error(exc)
                if error is None:
                    raise
                if not error.retryable or attempt == attempts - 1:
                    raise error from exc
                delay = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
                hinted = retry_after_s(exc)
                if hinted is not None:
                    if hinted > MAX_RETRY_AFTER_S:
                        raise error from exc
                    delay = max(delay, hinted)
                if (
                    deadline is not None
                    and self._clock() + delay + MIN_REQUEST_TIMEOUT_S > deadline
                ):
                    raise error from exc  # no time left for a retry that could finish
                logger.warning(
                    "Gemini %s (%s); retry %d/%d in %.1f s",
                    error.code,
                    error.status or type(exc).__name__,
                    attempt + 1,
                    attempts - 1,
                    delay,
                )
                self._sleep(delay)
                if self._should_stop():
                    raise error from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float,
        deadline: float | None = None,
    ) -> ModelTurn:
        system, contents = to_contents(messages, self._model_turns, self._native_ids)
        response = self._request(
            lambda timeout_s: self.client.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=self._config(system, tools, temperature, timeout_s),
            ),
            deadline,
        )
        turn, replay, native = parse_response(response, len(self._model_turns) + 1, self.model_id)
        self._model_turns.append(replay)
        self._native_ids |= native
        return turn

    def generate_json(
        self,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        *,
        temperature: float = 0.0,
        deadline: float | None = None,
    ) -> tuple[str, Usage | None, str]:
        """One structured-output request (used by the LLM judge). No tools, no thoughts.

        Returns (raw JSON text, usage, model that answered); the caller validates it.
        """

        def call(timeout_s: float) -> Any:
            return self.client.models.generate_content(
                model=self.model_id,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    temperature=temperature,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    thinking_config=thinking_config(self.model_id, self.thinking_level),
                    http_options=types.HttpOptions(timeout=round(timeout_s * 1000)),
                ),
            )

        response = self._request(call, deadline)
        turn, _, _ = parse_response(response, 0, self.model_id)  # drops thought parts
        return turn.text or "", turn.usage, turn.model_id or self.model_id
