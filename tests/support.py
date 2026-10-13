"""Test helpers. No network, no API key, no running API — contract §9.

Importing this module puts ``src/`` on ``sys.path``, so the suite runs
straight from a checkout with nothing installed:

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Deque, List, Mapping, Optional, Sequence, Union

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from chatly import ChatlyClient, HTTPRequest, HTTPResponse, Transport  # noqa: E402
from chatly.retry import RetryPolicy  # noqa: E402

#: A retry policy with no jitter, so a test can assert on the exact waits.
DETERMINISTIC_RETRIES = RetryPolicy(jitter=False, initial_backoff=0.5)


def json_response(
    payload: Any,
    *,
    status: int = 200,
    headers: Optional[Mapping[str, str]] = None,
) -> HTTPResponse:
    """A 2xx JSON response."""
    merged = {"content-type": "application/json"}
    if headers:
        merged.update({k.lower(): v for k, v in headers.items()})
    return HTTPResponse(
        status=status, headers=merged, body=json.dumps(payload).encode("utf-8")
    )


def error_response(
    status: int,
    code: str,
    message: str,
    *,
    details: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> HTTPResponse:
    """An error response in **the envelope the API really sends**.

    Nested under ``error`` — ``wireError`` in ``packages/shared/src/errors``.
    Built here rather than hand-written per test on purpose: a fixture that
    invents the server's shape makes the whole suite agree with a bug instead
    of with the server, which is how the widget shipped a client reading
    ``body.code`` at the top level where it is always ``undefined``.
    """
    body: dict = {"code": code, "message": message}
    if details is not None:
        body["details"] = dict(details)
    return HTTPResponse(
        status=status,
        headers={"content-type": "application/json", **{k.lower(): v for k, v in (headers or {}).items()}},
        body=json.dumps({"error": body}).encode("utf-8"),
    )


#: The fallback body, for tests that assert on the *request* and do not care
#: what comes back.
#:
#: A cursor envelope, because it is the one body every decoder on this surface
#: accepts: ``as_object`` takes the dict, ``as_list`` unwraps ``items``, and
#: ``page_from_payload`` is satisfied. That is exactly what makes it a USELESS
#: shape fixture and a convenient request fixture, and the distinction is the
#: whole reason ``tests/test_surface_lock.py`` declares a shape per route and
#: feeds each method its own body instead of reusing this. A fake that answers
#: every route with a page envelope is how two other SDKs shipped a paginator
#: over the bare-array ``GET /v1/macros`` with a green suite.
ANY_SHAPE_BODY = {"items": [], "nextCursor": None}


class FakeTransport(Transport):
    """Records every request and replays a scripted list of responses.

    An entry may be an :class:`Exception`, which is raised instead of
    returned — that is how a connection failure is simulated without a
    network. Once the script is exhausted it serves :data:`ANY_SHAPE_BODY`
    with a 200, so a test that only cares about the *request* does not have
    to script a reply.
    """

    def __init__(
        self, responses: Optional[Sequence[Union[HTTPResponse, Exception]]] = None
    ) -> None:
        self.requests: List[HTTPRequest] = []
        self._script: Deque[Union[HTTPResponse, Exception]] = deque(responses or ())
        self.fallback = json_response(ANY_SHAPE_BODY)

    def send(self, request: HTTPRequest) -> HTTPResponse:
        self.requests.append(request)
        if not self._script:
            return self.fallback
        nxt = self._script.popleft()
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    # ---- assertions a test wants -------------------------------------

    @property
    def last(self) -> HTTPRequest:
        return self.requests[-1]

    @property
    def count(self) -> int:
        return len(self.requests)

    def idempotency_keys(self) -> List[Optional[str]]:
        return [r.headers.get("idempotency-key") for r in self.requests]


class SleepRecorder:
    """Stands in for ``time.sleep`` so retry tests are instant."""

    def __init__(self) -> None:
        self.waits: List[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def build_client(
    responses: Optional[Sequence[Union[HTTPResponse, Exception]]] = None,
    **kwargs: Any,
) -> "tuple[ChatlyClient, FakeTransport, SleepRecorder]":
    """A client wired to a fake transport and a fake clock."""
    transport = FakeTransport(responses)
    sleeper = SleepRecorder()
    kwargs.setdefault("retry", DETERMINISTIC_RETRIES)
    client = ChatlyClient(
        kwargs.pop("api_key", "ck_test_key"),
        transport=transport,
        sleep=sleeper,
        **kwargs,
    )
    return client, transport, sleeper
