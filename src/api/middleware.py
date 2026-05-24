"""API middleware components."""

import base64
import contextvars
import json
import re
import time
import uuid
import logging
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request-scoped context variable (issue #3601)
# ---------------------------------------------------------------------------

#: Stores the current request ID so background tasks spawned from the request
#: context (via asyncio.create_task) automatically inherit the same value.
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_request_id_ctx", default=""
)


def get_current_request_id() -> str:
    """Return the request ID bound to the current async context."""
    return _request_id_ctx.get()


# Public paths that do not require authentication
_PUBLIC_PATHS = {"/api/v2/auth/token"}


def _normalize_path(path: str) -> str:
    """Collapse consecutive slashes in a URL path to a single slash.

    Prevents auth bypass via paths like ``//api/v2/secure`` that would not
    match a naive ``startswith('/api/v2')`` check (issue #3537).
    """
    return re.sub(r"/+", "/", path)


def _decode_jwt_payload(token: str) -> Optional[dict]:
    """Decode JWT payload without signature verification (claims reading only)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _check_token_nbf(token: str) -> bool:
    """Return True when the token's not-before (nbf) claim is satisfied.

    Rejects tokens whose ``nbf`` is in the future (issue #3596).
    """
    payload = _decode_jwt_payload(token)
    if payload is None:
        return True  # Malformed token — let downstream handle it
    nbf = payload.get("nbf")
    if nbf is None:
        return True  # nbf is optional per RFC 7519 §4.1.5
    return time.time() >= float(nbf)


# ---------------------------------------------------------------------------
# Policy engine availability (issue #3592)
# ---------------------------------------------------------------------------

class PolicyEngineUnavailableError(RuntimeError):
    """Raised when the policy engine cannot be contacted."""


def check_policy_engine_available(policy_client=None) -> None:
    """Fail closed when the policy engine is unavailable.

    If *policy_client* is provided, it must expose a ``is_available()``
    method.  When the engine cannot be reached, this function raises
    :class:`PolicyEngineUnavailableError` so that the caller can deny
    the request rather than silently allowing it through.
    """
    if policy_client is None:
        return  # No policy engine configured — nothing to check
    try:
        available = policy_client.is_available()
    except Exception as exc:
        raise PolicyEngineUnavailableError(
            "Policy engine check failed; denying request (fail-closed)"
        ) from exc
    if not available:
        raise PolicyEngineUnavailableError(
            "Policy engine is unavailable; denying request (fail-closed)"
        )


# ---------------------------------------------------------------------------
# Middleware classes
# ---------------------------------------------------------------------------

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign and propagate a unique request ID to every request.

    The ID is:
    * Read from the ``X-Request-ID`` header if provided by the caller.
    * Otherwise generated as a new UUID4.
    * Stored in a ``contextvars.ContextVar`` so that background tasks
      spawned with :func:`asyncio.create_task` inherit the **same** ID —
      this ensures background task logs are correlated to the originating
      request (issue #3601).
    * Echoed back in the ``X-Request-ID`` response header for client-side
      tracing.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Honour a caller-supplied ID or mint a fresh one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Bind to the async context so all downstream code (including
        # background tasks) sees the same ID without passing it explicitly.
        token = _request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            # Always reset — prevent ID leaking to unrelated requests sharing
            # the same thread/coroutine in error paths.
            _request_id_ctx.reset(token)

        response.headers["X-Request-ID"] = request_id
        logger.debug("Request %s completed with status %s", request_id, response.status_code)
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for the Agent Orchestrator API.

    Fixes applied:
    * **Path normalisation** (issue #3537): collapses ``//api/v2/…`` before
      prefix checks to prevent auth bypass via duplicate slashes.
    * **JWT nbf enforcement** (issue #3596): rejects tokens whose ``nbf``
      claim lies in the future.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        normalized_path = _normalize_path(request.url.path)

        if normalized_path.startswith("/api/v2") and normalized_path not in _PUBLIC_PATHS:
            token_header = request.headers.get("Authorization", "")
            if not token_header.startswith("Bearer "):
                logger.warning(
                    "Rejected unauthenticated request: method=%s path=%s",
                    request.method,
                    normalized_path,
                )
                return Response(status_code=401, content="Unauthorized")

            bearer_token = token_header[len("Bearer "):]

            if not _check_token_nbf(bearer_token):
                logger.warning(
                    "Rejected token with future nbf claim: method=%s path=%s",
                    request.method,
                    normalized_path,
                )
                return Response(
                    status_code=401,
                    content="Token not yet valid (nbf claim is in the future)",
                )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < self.window]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content="Too many requests")

        self._requests[client_ip].append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        rid = get_current_request_id()
        logger.info(
            "%s %s %s %.3fs%s",
            request.method,
            request.url.path,
            response.status_code,
            duration,
            f" request_id={rid}" if rid else "",
        )
        return response


# 2019-03-01T18:35:19 update

# 2019-04-03T13:22:05 update

# 2019-04-30T17:18:49 update

# 2019-08-20T09:29:03 update

# 2019-08-30T15:52:06 update

# 2019-11-23T16:58:42 update

# 2020-02-18T10:04:07 update

# 2020-04-21T17:35:30 update

# 2020-05-22T11:10:34 update

# 2020-07-02T12:31:26 update

# 2020-07-05T13:52:59 update

# 2020-08-21T20:36:45 update

# 2021-01-19T09:17:15 update

# 2021-01-29T11:34:24 update

# 2021-02-04T15:21:21 update

# 2021-04-19T19:23:15 update

# 2021-05-20T16:50:15 update

# 2021-06-22T19:23:44 update

# 2021-09-09T13:44:55 update

# 2021-09-16T09:30:20 update

# 2021-10-14T20:42:33 update

# 2021-12-28T16:39:14 update

# 2022-01-26T19:07:27 update

# 2022-01-28T08:03:41 update

# 2022-03-23T12:17:02 update

# 2022-04-06T12:12:27 update

# 2022-04-21T14:53:01 update

# 2022-06-30T08:37:32 update

# 2022-07-06T10:44:45 update

# 2022-11-02T11:12:47 update

# 2022-11-15T20:54:21 update

# 2022-11-23T14:13:34 update

# 2023-01-26T10:03:44 update

# 2023-02-09T17:08:10 update

# 2023-02-16T10:04:00 update

# 2023-03-14T11:52:03 update

# 2023-04-10T12:42:07 update

# 2023-04-26T10:43:39 update

# 2023-06-27T08:18:07 update

# 2023-08-30T15:30:40 update

# 2023-08-30T14:10:05 update

# 2023-10-09T18:32:46 update

# 2023-11-21T20:35:55 update

# 2024-03-07T19:17:39 update

# 2024-04-01T18:06:19 update

# 2024-07-18T15:37:34 update

# 2024-07-25T09:21:53 update

# 2024-08-12T14:24:22 update

# 2024-11-18T08:50:54 update

# 2025-04-08T12:43:05 update

# 2025-06-03T08:10:47 update

# 2025-06-12T08:37:52 update

# 2025-06-17T08:36:56 update

# 2025-07-02T18:09:42 update

# 2025-07-22T12:39:21 update

# 2025-10-13T12:13:46 update

# 2025-12-05T09:44:22 update

# 2025-12-22T18:34:47 update

# 2026-01-26T15:36:23 update

# 2026-02-13T12:36:40 update

# 2026-02-26T11:07:15 update

# 2026-03-19T11:00:17 update

# 2026-03-27T12:58:53 update

# 2026-05-12T17:19:36 update
