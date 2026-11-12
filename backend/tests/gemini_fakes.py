"""A scripted stand-in for the google-genai client, so no test ever calls the real API."""

from typing import Any

from google.genai import errors, types

THOUGHT_TEXT = "SECRET-REASONING: the customer is probably lying about the parcel"
SIGNATURE = b"opaque-signature-bytes"


def response(
    *parts: types.Part,
    input_tokens: int = 100,
    output_tokens: int = 20,
    thinking_tokens: int | None = 7,
    model: str = "gemini-3.5-flash",
) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
            thoughts_token_count=thinking_tokens,
        ),
        model_version=model,
    )


def thought() -> types.Part:
    return types.Part(text=THOUGHT_TEXT, thought=True)


def fcall(name: str, args: dict[str, Any] | None = None, *, signed: bool = False) -> types.Part:
    return types.Part(
        function_call=types.FunctionCall(name=name, args=args or {}),
        thought_signature=SIGNATURE if signed else None,
    )


def api_error(code: int, status: str, message: str = "error", retry_s: int | None = None):  # type: ignore[no-untyped-def]
    details = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": f"{retry_s}s"}]
    body = {
        "error": {
            "code": code,
            "status": status,
            "message": message,
            **({"details": details} if retry_s is not None else {}),
        }
    }
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, body)


class FakeModels:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.requests.append({"model": model, "contents": contents, "config": config})
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, BaseException):
            raise item
        return item


class FakeGeminiClient:
    def __init__(self, script: list[Any]) -> None:
        self.models = FakeModels(script)
