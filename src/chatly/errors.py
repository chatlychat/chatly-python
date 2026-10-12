"""Typed errors.

Contract §3: a typed error, never a bare string. Every HTTP failure carries
``status``, ``code``, ``message``, ``request_id`` and ``body``, and a caller
branches on the *class*, never on a substring of the message.

Two things here were learned from the server rather than guessed:

* **The error envelope is nested.** The API's exception filter sends
  ``{"error": {"code", "message", "details"?}}`` (``wireError`` in
  ``packages/shared/src/errors``). A client that reads ``body["code"]`` gets
  ``None`` for every real response — that exact bug shipped in the widget and
  killed its session-recovery path. We read the nested shape first and fall
  back to the flat one, so a response from a proxy or a framework-level
  handler that did not go through the filter still yields something useful.

* **Validation arrives as either 400 or 422.** A ``ZodError`` is turned into
  ``400`` with ``code: "validation_failed"``; application-level validation
  uses ``422``. Both raise :class:`ValidationError` so a caller does not have
  to know which layer rejected them. Any other 400 raises
  :class:`BadRequestError`. Neither is ever retried (contract §4).
"""

from __future__ import annotations

import json
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Mapping, Optional


class ChatlyError(Exception):
    """Base class for every error this SDK raises."""


class InvalidArgumentError(ChatlyError, ValueError):
    """A caller passed something this SDK refuses before any I/O happens.

    Subclasses :class:`ValueError` as well, so ``except ValueError`` in
    ordinary Python code catches it and ``except ChatlyError`` catches it too.
    """


class PaginationError(ChatlyError):
    """The server returned a cursor sequence that cannot be walked.

    Raised when a cursor repeats, which would otherwise be an infinite loop
    (contract §5). It is raised rather than quietly ending the iteration
    because silently truncating a list of contacts is the worse failure: the
    caller believes they saw everything.
    """


class TransportError(ChatlyError):
    """The request never produced an HTTP status: DNS, connect, TLS, socket.

    Distinct from any :class:`APIError` — contract §3. Retryable (§4).
    """

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause


class ChatlyTimeoutError(TransportError):
    """The request exceeded the client's timeout.

    Named with the ``Chatly`` prefix only because ``TimeoutError`` is a Python
    builtin and shadowing it in the package barrel would be hostile.
    """


class APIError(ChatlyError):
    """A non-2xx HTTP response.

    Attributes:
        status: the HTTP status.
        code: the API's ``code`` field, or a synthesised one if the body
            carried none (``"http_<status>"``).
        message: the API's ``message`` field, or the reason phrase.
        request_id: the ``x-request-id`` response header.

            **Expect ``None`` today.** Nothing in the platform currently
            emits that header; it is read because the contract specifies it
            and because a proxy in front of a self-hosted install may add
            one. Do not build an alerting path that assumes it is populated.
        body: the raw response text, verbatim, for anything the fields above
            lose.
        details: the ``details`` object from the error envelope, when present.
    """

    def __init__(
        self,
        *,
        status: int,
        code: str,
        message: str,
        request_id: Optional[str] = None,
        body: str = "",
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(f"chatly {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.body = body
        self.details: Mapping[str, Any] = details if details is not None else {}

    def __str__(self) -> str:
        suffix = f" (request id {self.request_id})" if self.request_id else ""
        return f"chatly {self.status} {self.code}: {self.message}{suffix}"


class AuthenticationError(APIError):
    """401 — the key is missing, malformed, revoked or expired."""


class PermissionDeniedError(APIError):
    """403 — the key is valid but lacks the scope, or the route needs a person.

    140 of the API's routes accept a ``ck_`` key; the rest answer one with
    this, because they record *who* acted and a key is not a person. Telling
    this apart from :class:`AuthenticationError` without parsing a message is
    the whole point of the split (contract §3).
    """


class NotFoundError(APIError):
    """404 — no such resource in this workspace, or no such route."""


class ConflictError(APIError):
    """409 — the write conflicts with the current state, or replays badly."""

    @property
    def is_idempotency_conflict(self) -> bool:
        """True when the same ``Idempotency-Key`` was reused with a new body.

        The API's code for this is ``idempotency_conflict``
        (``IdempotencyConflictError`` in ``packages/shared/src/errors``). A
        plain in-flight collision uses ``conflict`` and is safe to retry
        after a pause; this one is not — the body differs, so retrying it
        unchanged will fail identically forever.
        """
        return self.code == "idempotency_conflict"


class BadRequestError(APIError):
    """400 that is not a validation failure."""


class ValidationError(APIError):
    """The request was understood and rejected: 422, or 400 ``validation_failed``.

    ``details["issues"]`` carries the zod issue list when the rejection came
    from schema validation.
    """


class RateLimitError(APIError):
    """429. ``retry_after`` is seconds, or ``None`` if the API gave no hint."""

    def __init__(self, *, retry_after: Optional[float] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.retry_after = retry_after


class ServerError(APIError):
    """5xx. Retryable (contract §4)."""


_BY_STATUS: Dict[int, Callable[..., APIError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}

_VALIDATION_CODES = frozenset({"validation_failed", "validation_error"})


def _decode_envelope(text: str) -> Dict[str, Any]:
    """Pull ``code``/``message``/``details`` out of an error body.

    Nested (``{"error": {...}}``) first, flat second. A body that is not JSON,
    or is JSON but not an object, yields an empty dict rather than raising —
    an error path that raises while building an error is a lost diagnosis.
    """
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    inner = parsed.get("error")
    if isinstance(inner, dict):
        return inner
    return parsed


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header: delta-seconds or an HTTP-date.

    RFC 9110 allows both. Returns ``None`` for anything unparseable, and never
    a negative number — an HTTP-date already in the past means "retry now".
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(int(raw)))
    except ValueError:
        pass
    try:
        # Raises on anything unparseable rather than returning None, which is
        # why there is no None check after it.
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    import datetime as _dt

    now = _dt.datetime.now(tz=when.tzinfo) if when.tzinfo else _dt.datetime.now()
    return max(0.0, (when - now).total_seconds())


def error_from_response(
    *,
    status: int,
    headers: Mapping[str, str],
    body: str,
) -> APIError:
    """Build the right :class:`APIError` subclass from a raw response.

    ``headers`` must be keyed in lowercase; :class:`chatly._transport.HTTPResponse`
    guarantees that.
    """
    envelope = _decode_envelope(body)
    code = envelope.get("code")
    message = envelope.get("message")
    details = envelope.get("details")

    kwargs: Dict[str, Any] = {
        "status": status,
        "code": str(code) if isinstance(code, (str, int)) else f"http_{status}",
        "message": str(message) if isinstance(message, (str, int)) else f"HTTP {status}",
        "request_id": headers.get("x-request-id"),
        "body": body,
        "details": details if isinstance(details, dict) else None,
    }

    if status == 429:
        retry_after = parse_retry_after(headers.get("retry-after"))
        if retry_after is None and isinstance(details, dict):
            # The API puts it in the body as `details.retryAfterSeconds`
            # (`RateLimitedError`); the header is what a proxy or the
            # throttler guard adds. Header wins when both are present.
            hint = details.get("retryAfterSeconds", details.get("retry_after_seconds"))
            if isinstance(hint, (int, float)) and not isinstance(hint, bool):
                retry_after = max(0.0, float(hint))
        return RateLimitError(retry_after=retry_after, **kwargs)

    if status == 400 and kwargs["code"] in _VALIDATION_CODES:
        return ValidationError(**kwargs)
    if status == 400:
        return BadRequestError(**kwargs)

    cls = _BY_STATUS.get(status)
    if cls is not None:
        return cls(**kwargs)
    if status >= 500:
        return ServerError(**kwargs)
    return APIError(**kwargs)


class ResponseDecodeError(ChatlyError):
    """A 2xx response body was not the JSON this SDK was promised.

    Deliberately an error rather than a silent ``None``: a success status with
    an unreadable body means something between the caller and the API (a
    captive portal, a proxy error page, a wrong base URL that happens to
    answer 200) is answering instead of the platform, and returning ``None``
    for it sends a caller looking for a bug in their own code.
    """

    def __init__(self, message: str, *, status: int, body: str) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body
