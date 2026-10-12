"""Cursor pagination, and the generator that walks it. Contract §5.

Every paged list endpoint returns ``{"items": [...], "nextCursor": "..." }``
with ``nextCursor`` ``null`` on the last page. Two of them add a field:
``GET /v1/conversations/unattended`` adds ``total`` and ``GET /v1/tickets``
adds ``hasMore``. :class:`Page` surfaces both when they are there and
``None`` when they are not, and keeps the whole decoded body in
:attr:`Page.raw`, so a field this SDK has not heard of is never lost.

**Never page on ``id``.** Ids in this product are a mix of UUID v4 and v7, so
id order is not time order — 18 lists in the dashboard were in effectively
random order while claiming to be newest-first. The cursor is the only
correct sequence, and it is opaque: do not parse it, store it as a timestamp,
or construct one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Iterator, List, Mapping, Optional, TypeVar

from .errors import PaginationError

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
            (``/v1/tickets``). ``None`` elsewhere. When you only want to know
            whether to keep going, test ``next_cursor``; it is on every paged
            route.
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


def page_from_payload(payload: Any) -> Page[Any]:
    """Wrap a decoded list response in a :class:`Page`.

    Tolerant on purpose, in one direction only: a bare JSON array becomes a
    single page with no cursor (several key-accessible routes are
    ``@PaginationExempt`` and answer with an array), and a missing
    ``nextCursor`` is treated as the last page. It does not *invent* a shape
    — anything unrecognised comes back as an empty page with the body intact
    in :attr:`Page.raw`, so a caller can see what arrived.
    """
    if isinstance(payload, list):
        return Page(items=list(payload), next_cursor=None, raw={"items": payload})
    if not isinstance(payload, dict):
        return Page(items=[], next_cursor=None, raw={})

    items = payload.get("items")
    if not isinstance(items, list):
        items = []

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


__all__ = ["MAX_PAGES", "Page", "iter_items", "iter_pages", "page_from_payload"]
