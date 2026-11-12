"""Typed LLM provider failures.

A provider failure is the platform's problem, not the agent's: the graph stops with
`provider_error` and the run ends `errored` with error kind `infra`, so it is scored `ERROR`
and kept out of agent metrics (context/system_design.md §9).
"""


class ProviderError(RuntimeError):
    code = "provider_error"
    retryable = False

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message[:500], "status": self.status}


class ProviderNotConfiguredError(ProviderError):
    """The config needs a provider that has no API key on this server."""

    code = "provider_not_configured"


class ProviderQuotaError(ProviderError):
    """429 / RESOURCE_EXHAUSTED, or the local throttle could not fit the call in the deadline."""

    code = "provider_quota"
    retryable = True


class ProviderDailyQuotaError(ProviderQuotaError):
    """The provider's per-day quota is used up: retrying today cannot help."""

    retryable = False


class ProviderUnavailableError(ProviderError):
    """5xx, overload, network failure or request timeout."""

    code = "provider_unavailable"
    retryable = True


class ProviderAuthError(ProviderError):
    """The API key is missing, invalid or not allowed to use the model."""

    code = "provider_auth"


class ProviderBadRequestError(ProviderError):
    """The provider rejected the request (unknown model, unsupported setting, bad schema)."""

    code = "provider_bad_request"
