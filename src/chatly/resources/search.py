"""``client.search`` — full-text search across five entity kinds."""

from __future__ import annotations

from typing import Any, Iterator, List, Optional, Sequence, Union

from ..errors import InvalidArgumentError
from ..pagination import Page, iter_items, page_from_payload
from ._base import JsonDict, Resource

#: The entities search can return. Omitting ``kinds`` searches all five.
SEARCH_KINDS = ("contact", "conversation", "message", "ticket", "kb")


def _wire_kinds(kinds: Union[None, str, Sequence[str]]) -> Optional[List[str]]:
    """Render ``kinds`` the way this one route actually reads it.

    The route's schema is ``z.array(z.enum(...)).min(1)`` parsed straight off
    the raw query object, with no preprocessing and no single-to-array
    coercion. Three of the four plausible spellings are wrong, and two of
    them are wrong *silently*:

    ===========================  ==========================================
    ``kinds[]=kb``               200, and the filter is **dropped** — the
                                 bracketed key is not ``kinds``, and an
                                 unknown query key is stripped, so all five
                                 kinds are searched and nothing says so.
    ``kinds=kb,ticket``          400 — a comma string is not an array.
    ``kinds=kb`` (once)          400 — one value parses as a string.
    ``kinds=kb&kinds=ticket``    correct.
    ===========================  ==========================================

    So a *single* kind has to be sent twice to arrive as a one-element-ish
    array. That is deliberate here, and ugly: duplicating the value is the
    only spelling that both parses and filters, the duplicate is harmless to
    the query the server builds, and the alternative is a method that 400s
    whenever you ask for exactly one kind.

    The bracketed form is what ``packages/sdk-node``, the MCP server, the
    dashboard's inbox search and ``CONTRACT.md`` §2's own example all send —
    every one of them is silently searching everything. Fixing those is
    outside this package; this note is here so the next port does not copy
    the bug.
    """
    if kinds is None:
        return None
    values = [kinds] if isinstance(kinds, str) else list(kinds)
    if not values:
        return None
    for kind in values:
        if kind not in SEARCH_KINDS:
            raise InvalidArgumentError(
                f"unknown search kind {kind!r}; expected one of {', '.join(SEARCH_KINDS)}"
            )
    if len(values) == 1:
        return [values[0], values[0]]
    return values


class Search(Resource):
    """One route, ``GET /v1/search``, with its own response envelope."""

    def query(
        self,
        q: str,
        *,
        kinds: Union[None, str, Sequence[str]] = None,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        channel_id: Optional[str] = None,
        assignee_user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        **params: Any,
    ) -> JsonDict:
        """Search contacts, conversations, messages, tickets and articles.

        Args:
            q: required, 1–256 characters.
            kinds: one kind or several of ``contact``, ``conversation``,
                ``message``, ``ticket``, ``kb``. Omitted searches all five.
            from_: ISO-8601 lower bound (inclusive) on creation. **Must end
                in ``Z``** — the route's validator rejects a ``+00:00``
                offset. Named with a trailing underscore because ``from`` is
                a Python keyword; it is sent as ``from``.
            to: ISO-8601 upper bound, **exclusive**, same ``Z`` requirement.
            channel_id: narrows to one channel. Applies to conversations
                only, and **drops contacts, messages and articles from the
                results entirely** — the kinds it cannot filter are removed
                rather than passed through unfiltered.
            assignee_user_id: narrows to one assignee. Applies to
                conversations and tickets, and drops the other three kinds.
            status: a free-form 1–32 character status, not an enum. Applies
                to conversations and tickets, and drops the other three.
            limit: 1–100, default 25.
            cursor: from the previous response's ``nextCursor``.

        Returns the route's own four-key envelope — ``{"items",
        "nextCursor", "facets", "tier"}``, with no ``hasMore`` and no
        ``total``:

            * ``items``: ``{"kind", "id", "title", "snippet", "rank",
              "createdAt", "conversationId"}``. ``title`` and ``snippet`` are
              never null (empty string instead); ``conversationId`` is null
              for kinds that have no thread.
            * ``facets``: a count per kind, always all five keys,
              zero-filled. It counts **before** the kind-dropping described
              above, so it is the right number for a "N in messages" tab.
            * ``tier``: ``"postgres"`` or ``"opensearch"``. The two tiers
              score on unrelated scales, so ``rank`` is only comparable
              within one response, and their cursors are **not
              interchangeable** — a cursor minted by the other tier is
              treated as absent and you silently get page one again.
        """
        if not isinstance(q, str) or q.strip() == "":
            raise InvalidArgumentError("search query 'q' is required and must be non-empty")
        return self._get_obj(
            "/v1/search",
            {
                "q": q,
                "kinds": _wire_kinds(kinds),
                "from": from_,
                "to": to,
                "channelId": channel_id,
                "assigneeUserId": assignee_user_id,
                "status": status,
                "limit": limit,
                "cursor": cursor,
                **params,
            },
        )

    def kb(self, q: str, **params: Any) -> JsonDict:
        """Search help-centre articles only. ``query(q, kinds="kb")``.

        Worth its own method because "find the article that answers this" is
        the common case, and because getting there otherwise means knowing
        both that ``kinds`` exists and that a single value has to be sent
        twice.
        """
        params.pop("kinds", None)
        return self.query(q, kinds="kb", **params)

    def iter_query(self, q: str, **params: Any) -> Iterator[JsonDict]:
        """Walk every page of hits, as a generator.

        Yields hits, not pages, so ``facets`` and ``tier`` are not visible —
        call :meth:`query` when you need them. Stops on a null cursor and
        raises :class:`~chatly.errors.PaginationError` if the server repeats
        one, which matters more here than elsewhere: a cursor from the other
        search tier is treated as absent and re-serves page one, which would
        otherwise loop forever.
        """
        params.pop("cursor", None)

        def fetch(cursor: Optional[str]) -> Page[JsonDict]:
            return page_from_payload(self.query(q, cursor=cursor, **params))

        return iter_items(fetch)


__all__ = ["SEARCH_KINDS", "Search"]
