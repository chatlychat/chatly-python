"""Cursor pagination, and the generator that walks it. Contract §5.

Ten routes on the typed surface are paged — the ten the manifest marks
``shape: "page"`` — and every one of them returns ``{"items": [...],
"nextCursor": ...}`` with ``nextCursor`` ``null`` on the last page. Some add
a field beside those two, and which field depends on the route:

* ``hasMore`` on ``/v1/tickets``, ``/v1/kb/articles``,
  ``/v1/webhooks/deliveries`` and ``/v1/cdp/events`` — the four that build
  their envelope with the API's shared ``buildPaginatedResponse``.
* ``total`` on ``/v1/conversations/unattended``, and nowhere else.
* ``facets`` and ``tier`` on ``/v1/search``, which is why
  :meth:`chatly.resources.search.Search.query` hands back the raw envelope
  instead of a :class:`Page`.
* Nothing extra on ``/v1/contacts``, ``/v1/contacts/{id}/journey``,
  ``/v1/conversations`` and ``/v1/conversations/{id}/messages``.

:class:`Page` surfaces ``total`` and ``has_more`` when they are there and
``None`` when they are not — ``None`` means "not reported", never "zero" or
"false" — and keeps the whole decoded body in :attr:`Page.raw`, so a field
this SDK has not heard of is never lost.

Nothing else is accepted. A body that is not an ``items`` envelope raises
:class:`~chatly.errors.ResponseDecodeError` rather than becoming an empty
page; see :func:`page_from_payload`.

**Never page on ``id``.** Ids in this product are a mix of UUID v4 and v7, so
id order is not time order — 18 lists in the dashboard were in effectively
random order while claiming to be newest-first. The cursor is the only
correct sequence, and it is opaque: do not parse it, store it as a timestamp,
or construct one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Iterator, List, Mapping, Optional, TypeVar

from .errors import PaginationError, ResponseDecodeError

T = TypeVar("T")

#: How many pages the walker will fetch before it concludes the server is
#: feeding it an endless sequence. 10,000 pages at the maximum limit of 100
#: is a million rows — far past any legitimate workspace, and still a bound.
MAX_PAGES = 10_000


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page, exactly as the API returned it.

    Attributes:
        items: the rows. Plain decoded JSON objects — this SDK does not
            invent model classes for them, because the API adds response
            fields without a major version and a strict model would start
            dropping them.
        next_cursor: pass to the next call as ``cursor``. ``None`` means this
            was the last page.
        total: present only where the endpoint sends ``total``
            (``/v1/conversations/unattended``). ``None`` elsewhere, which
            means "not reported", not "zero".
        has_more: present only where the endpoint sends ``hasMore``
            (``/v1/tickets``, ``/v1/kb/articles``,
            ``/v1/webhooks/deliveries``, ``/v1/cdp/events``). ``None``
            elsewhere, which means "not reported", not "false". When you only
            want to know whether to keep going, test ``next_cursor``; it is
            on every paged route.
        raw: the full decoded body.
    """

    items: List[T] = field(default_factory=list)
    next_cursor: Optional[str] = None
    total: Optional[int] = None
    has_more: Optional[bool] = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator[T]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


def _not_a_page(payload: Any) -> ResponseDecodeError:
    """The error for a body that is not a cursor page. Names what did arrive."""
    kind = "null" if payload is None else type(payload).__name__
    extra = f" of {len(payload)}" if isinstance(payload, (list, str, dict)) else ""
    return ResponseDecodeError(
        "expected a cursor page from this endpoint — an object with an `items` "
        f"array — got {kind}{extra}",
        status=200,
        body=repr(payload)[:512],
    )


def page_from_payload(payload: Any) -> Page[Any]:
    """Wrap a decoded page envelope in a :class:`Page`.

    Strict: the body must be a JSON object carrying an ``items`` array.
    A missing or null ``nextCursor`` is the only tolerance, and it means
    "last page" — every paged route sends the key, and treating its absence
    as the end is what stops a walker looping on a truncated body.

    **This used to be tolerant, and the tolerance was a bug.** It accepted a
    bare JSON array as a single cursorless page, and turned anything else
    into an *empty* page with the body in :attr:`Page.raw`. Both readings
    answer a wrong shape with a plausible result:

    * A bare array reaching a walker means the route is not paged at all —
      ``macros.list`` is ``@PaginationExempt`` — and the honest answer is an
      error, not one page that looks complete. Bare-array routes come back
      through :func:`chatly.resources._base.as_list` instead, which is where
      that tolerance belongs.
    * An empty page for an unrecognised body is the worse half: the caller
      is told the list is empty. The Rust SDK shipped exactly this and
      returned an empty page with a 200 for a bare-array route — a wrong
      answer rather than a missing one, which no suite notices because
      nothing raises.

    Raises:
        ResponseDecodeError: if the body is not an object, or its ``items``
            is absent or not an array.
    """
    if not isinstance(payload, dict):
        raise _not_a_page(payload)

    items = payload.get("items")
    if not isinstance(items, list):
        raise _not_a_page(payload)

    cursor = payload.get("nextCursor", payload.get("next_cursor"))
    next_cursor = cursor if isinstance(cursor, str) and cursor != "" else None

    total = payload.get("total")
    has_more = payload.get("hasMore", payload.get("has_more"))

    return Page(
        items=list(items),
        next_cursor=next_cursor,
        total=total if isinstance(total, int) and not isinstance(total, bool) else None,
        has_more=has_more if isinstance(has_more, bool) else None,
        raw=payload,
    )


def page_from_untyped_payload(payload: Any) -> Page[Any]:
    """:func:`page_from_payload` with the one tolerance the escape hatch needs.

    ``ChatlyClient.paginate`` is pointed at routes this SDK has no method
    for, and a fair number of those are ``@PaginationExempt`` and answer
    with a bare array. There is no manifest entry to consult, so folding an
    array into one cursor-less page is the useful reading *there* — and only
    there. A typed method knows which shape its route sends, so it goes
    through the strict function and a wrong shape is an error.
    """
    if isinstance(payload, list):
        return Page(items=list(payload), next_cursor=None, raw={"items": payload})
    return page_from_payload(payload)


def iter_pages(fetch: Callable[[Optional[str]], Page[T]]) -> Iterator[Page[T]]:
    """Walk every page, starting from no cursor. A generator — lazy.

    ``fetch`` takes a cursor (``None`` for the first page) and returns a
    :class:`Page`. Stops when ``next_cursor`` is ``None``.

    Raises:
        PaginationError: if a cursor repeats, or if :data:`MAX_PAGES` is
            exceeded. Contract §5 requires that a server repeating a cursor
            must not spin forever. This raises rather than stopping quietly,
            because a truncated list that looks complete is the worse
            failure: the caller believes they saw every row.
    """
    seen: Dict[str, None] = {}
    cursor: Optional[str] = None
    pages = 0
    while True:
        page = fetch(cursor)
        yield page
        nxt = page.next_cursor
        if nxt is None:
            return
        if nxt in seen:
            raise PaginationError(
                f"the API repeated pagination cursor {nxt!r} after {pages + 1} page(s); "
                "refusing to loop forever"
            )
        seen[nxt] = None
        cursor = nxt
        pages += 1
        if pages >= MAX_PAGES:
            raise PaginationError(
                f"stopped after {MAX_PAGES} pages without reaching the end of the list"
            )


def iter_items(fetch: Callable[[Optional[str]], Page[T]]) -> Iterator[T]:
    """Walk every page and yield each row. The generator callers want.

    Flattening is deliberately separate from :func:`iter_pages` so a caller
    who needs the envelope (``total``, ``raw``) is not forced to re-implement
    the walk.
    """
    for page in iter_pages(fetch):
        for item in page.items:
            yield item


__all__ = [
    "MAX_PAGES",
    "Page",
    "iter_items",
    "iter_pages",
    "page_from_payload",
    "page_from_untyped_payload",
]
