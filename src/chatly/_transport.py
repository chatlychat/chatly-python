"""HTTP plumbing: the wire, the query string, and the one retry loop.

Zero runtime dependencies (contract §9) — ``urllib.request`` from the standard
library does the work, so installing this SDK installs nothing else.

Responsibilities, in order:

1. :func:`build_query` — query serialisation, including repeated keys.
2. :class:`HTTPRequest` / :class:`HTTPResponse` / :class:`Transport` — the
   seam. Tests inject a transport and need no network, no key and no running
   API (contract §9).
3. :class:`UrllibTransport` — the real one.
4. :class:`Requester` — auth, idempotency, retry and error mapping, in one
   place so every typed method and the escape hatch share them (contract §8).
"""

from __future__ import annotations

import datetime as _dt
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ._version import USER_AGENT
from .errors import (
    ChatlyTimeoutError,
    InvalidArgumentError,
    ResponseDecodeError,
    TransportError,
    error_from_response,
)
from .retry import RetryPolicy

#: Contract §1. Production, and never a development or example host: four
#: SDKs shipped defaulting to `api.livechat.local` / `api.chatly.example`,
#: which resolve nowhere, so every call failed for anyone who followed the
#: docs and did not override it. No test caught it because every test passes
#: an explicit URL — which is why `test_contract.py` asserts on this constant.
DEFAULT_API_URL = "https://api.chatlychat.com"

#: Methods that get an `Idempotency-Key`. Contract §2.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

QueryValue = Union[None, str, int, float, bool, _dt.date, _dt.datetime, Sequence[Any]]
QueryParams = Mapping[str, QueryValue]
JSONBody = Any


def _scalar(value: Any) -> str:
    """One query value as the wire sees it."""
    if isinstance(value, bool):
        # Before the int branch: bool is a subclass of int, and `True` must
        # be `true`, not `1`.
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise InvalidArgumentError(
        f"query values must be scalars, dates or sequences of them, got {type(value).__name__}"
    )


def build_query(params: Optional[QueryParams]) -> str:
    """Serialise query parameters. Returns ``""`` for nothing to send.

    ``None`` values are dropped — that is what makes
    ``list(cursor=None, limit=50)`` mean "no cursor" instead of
    "``cursor=None``".

    **Repeated keys stay repeated** (contract §2): ``{"kinds[]": ["kb",
    "article"]}`` becomes ``kinds[]=kb&kinds[]=article``, two parameters, not
    one comma-joined value. Comma-joining is the failure mode worth naming:
    the server reads it as a single kind literally called ``kb,article``,
    matches nothing, and returns an empty list rather than an error.
    """
    if not params:
        return ""
    pairs: List[Tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                if item is None:
                    continue
                pairs.append((key, _scalar(item)))
            continue
        pairs.append((key, _scalar(value)))
    if not pairs:
        return ""
    return urllib.parse.urlencode(pairs)


def encode_path(*segments: Any) -> str:
    """Percent-encode path segments so a slug or a tag cannot escape the path.

    A tag is user-supplied and reaches the URL in
    ``DELETE /v1/contacts/{id}/tags/{tag}``; a tag containing ``/`` or ``?``
    would otherwise rewrite the route being called.
    """
    out: List[str] = []
    for segment in segments:
        text = segment if isinstance(segment, str) else str(segment)
        if text == "":
            raise InvalidArgumentError("path segment must not be empty")
        out.append(urllib.parse.quote(text, safe=""))
    return "/".join(out)


@dataclass(frozen=True)
class HTTPRequest:
    """One outbound request, fully resolved. What a transport receives."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: Optional[bytes] = None
    timeout: float = 15.0


@dataclass(frozen=True)
class HTTPResponse:
    """One inbound response.

    ``headers`` keys are **lowercased** — every lookup in this package
    (``x-request-id``, ``retry-after``, ``content-type``) assumes it, and HTTP
    header names are case-insensitive anyway.
    """

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class Transport:
    """The injectable HTTP seam (contract §1).

    Subclass it, or pass any object with a compatible ``send``; it is a plain
    class rather than a ``typing.Protocol`` so that ``isinstance`` works and
    so a test double can inherit the docstring.
    """

    def send(self, request: HTTPRequest) -> HTTPResponse:  # pragma: no cover - interface
        raise NotImplementedError


class UrllibTransport(Transport):
    """The real transport, on ``urllib.request``.

    Proxy environment variables (``HTTPS_PROXY`` and friends) are honoured,
    because ``build_opener`` installs urllib's ``ProxyHandler`` by default.
    """

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener()

    def send(self, request: HTTPRequest) -> HTTPResponse:
        req = urllib.request.Request(url=request.url, data=request.body, method=request.method)
        for name, value in request.headers.items():
            # `add_header` capitalises, which is irrelevant on the wire and
            # keeps urllib from adding its own duplicate `User-Agent`.
            req.add_header(name, value)
        try:
            with self._opener.open(req, timeout=request.timeout) as resp:
                return HTTPResponse(
                    status=int(resp.status),
                    headers=_lower_headers(resp.headers.items()),
                    body=resp.read(),
                )
        except urllib.error.HTTPError as exc:
            # An HTTP status is not a transport failure: hand it back as a
            # response so one place decides what a status means.
            #
            # `close()` is not optional. An `HTTPError` IS an open response
            # object, and leaving it to the garbage collector leaks the
            # connection and emits a `ResourceWarning` — which is how this
            # was found, in the loopback test's own output. A process that
            # retries a failing endpoint leaks one socket per attempt.
            try:
                body = exc.read()
            except Exception:  # noqa: BLE001 - a body we cannot read is not fatal
                body = b""
            finally:
                try:
                    exc.close()
                except Exception:  # noqa: BLE001 - already failing; do not mask it
                    pass
            headers = _lower_headers(exc.headers.items()) if exc.headers else {}
            return HTTPResponse(status=int(exc.code), headers=headers, body=body)
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise ChatlyTimeoutError(
                    f"request to {request.url} timed out after {request.timeout}s", cause=exc
                ) from exc
            raise TransportError(f"request to {request.url} failed: {reason}", cause=exc) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ChatlyTimeoutError(
                f"request to {request.url} timed out after {request.timeout}s", cause=exc
            ) from exc
        except (http.client.HTTPException, OSError) as exc:
            raise TransportError(f"request to {request.url} failed: {exc}", cause=exc) from exc


def _lower_headers(items: Any) -> Dict[str, str]:
    return {str(k).lower(): str(v) for k, v in items}


class Requester:
    """Auth, idempotency, retry, error mapping — shared by every call path.

    A single instance is shared by every resource namespace on a client, so
    there is no way for one namespace to miss a cross-cutting concern. The
    Node SDK learned this the hard way: it rebound namespaces one by one onto
    a derived client and forgot ``search``, which went on calling the parent.
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 15.0,
        retry: Optional[RetryPolicy] = None,
        transport: Optional[Transport] = None,
        sleep: Callable[[float], None] = time.sleep,
        idempotency_key: Optional[str] = None,
    ) -> None:
        if not isinstance(api_key, str) or api_key.strip() == "":
            # Contract §1: reject an empty key at construction, not at the
            # first call, so the stack trace points at the misconfiguration
            # instead of at an unrelated request hours later.
            raise InvalidArgumentError("api_key must be a non-empty string")
        if not isinstance(api_url, str) or api_url.strip() == "":
            raise InvalidArgumentError("api_url must be a non-empty string")
        if timeout <= 0:
            raise InvalidArgumentError("timeout must be greater than 0 seconds")
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.timeout = float(timeout)
        self.retry = retry if retry is not None else RetryPolicy()
        self.transport: Transport = transport if transport is not None else UrllibTransport()
        self.sleep = sleep
        self.pinned_idempotency_key = idempotency_key

    def pinned(self, key: str) -> "Requester":
        """A copy of this requester that pins one ``Idempotency-Key``."""
        if not isinstance(key, str) or key == "":
            raise InvalidArgumentError("idempotency key must be a non-empty string")
        clone = object.__new__(Requester)
        clone.__dict__.update(self.__dict__)
        clone.pinned_idempotency_key = key
        return clone

    # ---- the one request path -------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[QueryParams] = None,
        body: JSONBody = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        """Send one request, retrying what is safe, and return decoded JSON.

        Returns ``None`` for ``204 No Content`` and for an empty 2xx body.
        """
        verb = method.upper()
        if not path.startswith("/"):
            raise InvalidArgumentError(f"path must start with '/', got {path!r}")

        qs = build_query(query)
        url = f"{self.api_url}{path}"
        if qs:
            url = f"{url}?{qs}"

        headers: Dict[str, str] = {
            "authorization": f"Bearer {self.api_key}",
            "accept": "application/json",
            "user-agent": USER_AGENT,
        }

        payload: Optional[bytes] = None
        if verb in WRITE_METHODS and verb != "DELETE" and body is None:
            # A write with nothing to say still sends `{}`: several routes
            # (`unsubscribe`, `redeliver`) take no fields but are parsed as
            # JSON objects, and an absent body is not an empty one.
            body = {}
        if body is not None:
            payload = json.dumps(body, separators=(",", ":"), default=_json_default).encode("utf-8")
            headers["content-type"] = "application/json"

        if verb in WRITE_METHODS:
            # Minted ONCE per call, outside the retry loop. Contract §4: a
            # retried write must reuse the key of the attempt that failed,
            # or the retry double-writes — which is the whole reason the
            # header exists.
            headers["idempotency-key"] = (
                idempotency_key or self.pinned_idempotency_key or str(uuid.uuid4())
            )

        request = HTTPRequest(
            method=verb, url=url, headers=headers, body=payload, timeout=self.timeout
        )
        response = self._send_with_retries(request)
        return _decode_success(response)

    def _send_with_retries(self, request: HTTPRequest) -> HTTPResponse:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.transport.send(request)
            except TransportError as exc:
                if not self.retry.should_retry(exc, attempt):
                    raise
                self.sleep(self.retry.backoff(attempt))
                continue

            if 200 <= response.status < 300:
                return response

            error = error_from_response(
                status=response.status, headers=response.headers, body=response.text
            )
            if not self.retry.should_retry(error, attempt):
                raise error
            self.sleep(
                self.retry.backoff(attempt, retry_after=getattr(error, "retry_after", None))
            )


def _json_default(value: Any) -> Any:
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    raise TypeError(f"object of type {type(value).__name__} is not JSON serialisable")


def _decode_success(response: HTTPResponse) -> Any:
    if response.status == 204 or not response.body.strip():
        return None
    try:
        return json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ResponseDecodeError(
            f"expected JSON from the API, got {len(response.body)} bytes that would not parse",
            status=response.status,
            body=response.text,
        ) from exc


__all__ = [
    "DEFAULT_API_URL",
    "WRITE_METHODS",
    "HTTPRequest",
    "HTTPResponse",
    "Requester",
    "Transport",
    "UrllibTransport",
    "build_query",
    "encode_path",
]
