"""Shared machinery for every resource namespace.

A namespace holds no transport state of its own: it borrows the client's
single :class:`~chatly._transport.Requester`, so auth, idempotency, retry and
error mapping cannot be wired correctly on one namespace and wrongly on
another. The Node SDK derived a client by rebinding its namespaces one at a
time and forgot ``search``, which went on calling the parent's requester; one
shared object makes that class of bug unrepresentable.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Union

from .._transport import QueryValue, Requester
from ..errors import ResponseDecodeError
from ..pagination import Page, iter_items, page_from_payload

#: A decoded JSON object. The SDK returns these rather than modelled classes:
#: the API adds response fields without a major version, and a strict model
#: would silently drop them. The field names are documented per method.
JsonDict = Dict[str, Any]

#: A parameter the API wants comma-joined in ONE query key, not repeated.
CsvValue = Union[None, str, Sequence[str]]


def csv(value: CsvValue) -> Optional[str]:
    """Join a list into one comma-separated query value.

    Some list filters on this API are CSV inside a single parameter
    (``?status=open,pending``) rather than a repeated key. Passing them as
    repeated keys does not error — it narrows to whichever value the server
    reads last, or to none — so the join has to happen here, where the
    endpoint's convention is known.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def flag(value: Optional[bool]) -> Optional[str]:
    """Render a boolean filter the way these routes read one.

    The conversations list treats ``unread``/``mentioned``/``unattended``/
    ``sla`` as on for the literal ``"true"`` (or an empty value) and off for
    anything else — so ``False`` must be *omitted*, not sent as ``false``,
    or it reads as "off" by accident rather than by request. Omitting it is
    the same thing here and keeps the URL honest.
    """
    if value is None or value is False:
        return None
    return "true"


def as_list(payload: Any) -> List[JsonDict]:
    """Normalise a bare-array response.

    Nine key-accessible routes answer with a top-level JSON array rather than
    a ``{"items": ...}`` envelope — they are ``@PaginationExempt`` and take no
    cursor at all. This keeps a caller's ``for`` loop correct if one of them
    ever grows an envelope, and returns ``[]`` rather than ``None`` for an
    empty body, because ``for row in None`` is a crash in the caller's code
    rather than an empty result.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return list(items)
        return [payload]
    return []


def as_object(payload: Any) -> JsonDict:
    """Assert a response is a JSON object, and say so loudly when it is not.

    The transport hands back decoded JSON as ``Any``, because that is what it
    is. Every method that promises a single object funnels through here
    instead of casting: a cast would make the type checker agree with a wrong
    assumption, and the assumption is wrong on this API often enough to
    matter — nine key-accessible routes answer with a top-level array, and
    confusing one of those for an object is a ``TypeError`` three frames away
    from the cause.

    Raises:
        ResponseDecodeError: if the body was not a JSON object. The message
            names what did arrive, because "expected an object, got a list of
            4" is the whole diagnosis.
    """
    if isinstance(payload, dict):
        return payload
    kind = "null" if payload is None else type(payload).__name__
    extra = f" of {len(payload)}" if isinstance(payload, (list, str)) else ""
    raise ResponseDecodeError(
        f"expected a JSON object from this endpoint, got {kind}{extra}",
        status=200,
        body=repr(payload)[:512],
    )


class Resource:
    """Base for a namespace exposed as an attribute on the client."""

    __slots__ = ("_requester",)

    def __init__(self, requester: Requester) -> None:
        self._requester = requester

    # ---- call helpers ---------------------------------------------------

    def _get(self, path: str, query: Optional[Mapping[str, QueryValue]] = None) -> Any:
        return self._requester.request("GET", path, query=_clean(query))

    # The `_obj` variants promise a JSON object and verify it. The raw ones
    # above stay for the list and page paths, where the payload is an array
    # or an envelope.

    def _get_obj(
        self, path: str, query: Optional[Mapping[str, QueryValue]] = None
    ) -> JsonDict:
        return as_object(self._get(path, query))

    def _post_obj(
        self,
        path: str,
        body: Any = None,
        query: Optional[Mapping[str, QueryValue]] = None,
    ) -> JsonDict:
        return as_object(self._post(path, body, query))

    def _put_obj(self, path: str, body: Any = None) -> JsonDict:
        return as_object(self._put(path, body))

    def _patch_obj(self, path: str, body: Any = None) -> JsonDict:
        return as_object(self._patch(path, body))

    def _delete_obj(self, path: str, body: Any = None) -> JsonDict:
        return as_object(self._delete(path, body))

    def _post(
        self,
        path: str,
        body: Any = None,
        query: Optional[Mapping[str, QueryValue]] = None,
    ) -> Any:
        return self._requester.request("POST", path, query=_clean(query), body=body)

    def _put(self, path: str, body: Any = None) -> Any:
        return self._requester.request("PUT", path, body=body)

    def _patch(self, path: str, body: Any = None) -> Any:
        return self._requester.request("PATCH", path, body=body)

    def _delete(self, path: str, body: Any = None) -> Any:
        return self._requester.request("DELETE", path, body=body)

    # ---- pagination helpers ---------------------------------------------

    def _page(
        self, path: str, query: Optional[Mapping[str, QueryValue]] = None
    ) -> Page[JsonDict]:
        return page_from_payload(self._get(path, query))

    def _walk(
        self, path: str, query: Optional[Mapping[str, QueryValue]] = None
    ) -> Iterator[JsonDict]:
        """Auto-paginate ``path``, yielding one row at a time.

        The caller's ``cursor`` (if any) is the starting point; after that the
        server's ``nextCursor`` takes over.
        """
        base: Dict[str, QueryValue] = dict(_clean(query) or {})
        start = base.pop("cursor", None)
        first = True

        def fetch(cursor: Optional[str]) -> Page[JsonDict]:
            nonlocal first
            params = dict(base)
            use = cursor if cursor is not None else (start if first else None)
            first = False
            if use is not None:
                params["cursor"] = use
            return self._page(path, params)

        return iter_items(fetch)


def _clean(
    query: Optional[Mapping[str, QueryValue]],
) -> Optional[Dict[str, QueryValue]]:
    """Drop ``None`` values so an omitted argument is an absent parameter."""
    if query is None:
        return None
    return {k: v for k, v in query.items() if v is not None}


__all__ = ["CsvValue", "JsonDict", "Resource", "as_list", "as_object", "csv", "flag"]
