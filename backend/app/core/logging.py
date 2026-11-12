"""Structured JSON logging with request correlation and secret redaction."""

import json
import logging
import re
from datetime import UTC, datetime

from app.core.request_context import get_request_id

# (pattern, replacement) pairs for values that must never reach log output.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "***"),  # Google API keys
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), "Bearer ***"),  # bearer tokens / JWTs
    (re.compile(r"(?i)\b(password|secret|api_key|token)=\S+"), r"\1=***"),
    (re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s@]+:)[^@\s]+@"), r"\1***@"),  # DB passwords
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": get_request_id(),
        }
        for key in ("run_id", "suite_run_id", "event"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Route uvicorn's loggers through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
    # One INFO line per Gemini request is noise; failures still surface as warnings.
    for name in ("httpx", "httpx2", "google_genai"):
        logging.getLogger(name).setLevel(logging.WARNING)
