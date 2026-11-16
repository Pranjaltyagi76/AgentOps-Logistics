"""In-memory rate limiting and a request body size limit (single instance, decision D-01)."""

import json
import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any

from app.core.errors import error_body

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


class BodySizeLimitMiddleware:
    """Rejects requests whose body is larger than `max_bytes` with 413 (NFR-03).

    Checks Content-Length up front and also counts streamed bytes, so a missing or false
    Content-Length cannot bypass the limit.
    """

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        started = False

        async def tracking_send(message: Any) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        async def limited_receive() -> Any:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Any) -> None:
        body = json.dumps(
            error_body("payload_too_large", f"Request body exceeds {self.max_bytes} bytes")
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(BaseException):
    """BaseException so the app's catch-all `Exception` handler cannot turn it into a 500."""


_logged_proxy_shape = False


def _forwarded(request: Any) -> list[str]:
    raw = request.headers.get("x-forwarded-for", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def describe_proxy_headers(request: Any) -> dict[str, Any]:
    """The shape of the forwarding headers, without any address (for choosing the settings).

    `<header>_at` lists the X-Forwarded-For positions (counted from the right, 1 = last)
    holding the same value as that header, so the client's position can be read off safely.
    """
    forwarded = _forwarded(request)
    shape: dict[str, Any] = {"xff_entries": len(forwarded)}
    for name in ("cf-connecting-ip", "true-client-ip", "x-real-ip"):
        value = request.headers.get(name)
        shape[name] = value is not None
        if value is not None:
            shape[f"{name}_at"] = [
                len(forwarded) - i for i, part in enumerate(forwarded) if part == value.strip()
            ]
    return shape


def client_ip(request: Any, trusted_proxy_hops: int, header: str | None = None) -> str:
    """The caller's IP, as far as the deployment's proxies can be trusted.

    1. `header` (e.g. cf-connecting-ip), when set and present: a header the edge proxy
       overwrites, so clients cannot forge it.
    2. Else, with `trusted_proxy_hops` > 0, the X-Forwarded-For entry that many places from
       the right; entries left of it were supplied by the client and are ignored.
    3. Else (local), the socket peer address.
    """
    global _logged_proxy_shape
    if not _logged_proxy_shape and (header or trusted_proxy_hops):
        _logged_proxy_shape = True
        logger.info("Proxy header shape (first request): %s", describe_proxy_headers(request))
    if header:
        value = request.headers.get(header)
        if value and value.strip():
            return value.strip()
    if trusted_proxy_hops > 0:
        forwarded = _forwarded(request)
        if len(forwarded) >= trusted_proxy_hops:
            return forwarded[-trusted_proxy_hops]
    return request.client.host if request.client else "unknown"
