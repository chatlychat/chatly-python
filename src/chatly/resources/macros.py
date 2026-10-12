"""``client.macros`` — saved replies and the actions attached to them."""

from __future__ import annotations

from typing import Any, Iterator, Mapping, Optional, Sequence

from .._transport import encode_path
from ..pagination import Page
from ._base import JsonDict, Resource


class Macros(Resource):
    """Full CRUD on macros — the only namespace in this SDK with all four.

    A macro is ``{"id", "workspaceId", "name", "body", "actions",
    "shortCode", "scope", "teamId", "userId", "language", "tags",
    "usageCount", "createdByUserId", "createdAt", "updatedAt"}``.
    """

    def list(
        self,
        *,
        scope: Optional[str] = None,
        team: Optional[str] = None,
        query: Optional[str] = None,
        language: Optional[str] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """Macros, ranked by language match, then use count, then recency.

        Args:
            scope: ``workspace``, ``team`` or ``personal``.
            team: a team id. **The wire name is ``team``, not ``teamId``** —
                unlike the macro body, which uses ``teamId``.
            query: a name/body substring, up to 120 characters.
            language: a BCP-47-ish tag up to 8 characters. It **ranks** rather
                than filters: a macro in another language still comes back,
                lower down.

        This route is **not actually cursor-paginated.** It is
        pagination-exempt, takes no ``cursor`` or ``limit``, and the service
        hard-caps the result at 200 rows. The response is a bare JSON array,
        which this method wraps in a single :class:`~chatly.pagination.Page`
        with ``next_cursor`` of ``None`` — so the shape matches the other
        list methods and :meth:`iter_list` terminates after one call. A
        workspace with more than 200 macros silently sees only 200; narrow
        with ``query`` or ``scope`` rather than paging.
        """
        return self._page(
            "/v1/macros",
            {"scope": scope, "team": team, "query": query, "language": language, **params},
        )

    def iter_list(self, **params: Any) -> Iterator[JsonDict]:
        """Every macro the filters match, as a generator.

        Terminates after one request — see :meth:`list` for why. It exists so
        that ``iter_*`` is available on every list in this SDK and a caller
        does not have to remember which routes page.
        """
        params.pop("cursor", None)
        return self._walk("/v1/macros", params)

    def create(
        self,
        *,
        name: str,
        scope: str,
        body: Optional[str] = None,
        actions: Optional[Sequence[Mapping[str, Any]]] = None,
        short_code: Optional[str] = None,
        team_id: Optional[str] = None,
        language: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        **extra: Any,
    ) -> JsonDict:
        """Create a macro.

        Args:
            name: required, 1–200 characters.
            scope: required — ``workspace``, ``team`` or ``personal``.
            body: the reply text, up to 20,000 characters.
            actions: up to 16 ``{"key": ..., "params": {...}}`` objects. The
                accepted ``key`` vocabulary is served by
                ``GET /v1/macros/actions`` (reachable through
                :meth:`chatly.ChatlyClient.request`); an unknown key is a
                400.
            short_code: a slash command, matching
                ``/^\\/?[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/``. A leading ``/``
                is stripped server-side, so ``"/thanks"`` and ``"thanks"``
                are the same short code.
            team_id: **required when ``scope`` is ``team``** — and note it is
                ``teamId`` here while the list filter is ``team``.
            language: 2–8 characters, default ``"en"``.
            tags: up to 20 tags of up to 40 characters.

        **``body`` or ``actions`` must be non-empty.** A macro that neither
        says nor does anything is a 400 reported against the ``body`` field,
        which is confusing if what you forgot was ``actions``.
        """
        payload: JsonDict = {"name": name, "scope": scope}
        for key, value in (
            ("body", body),
            ("actions", list(actions) if actions is not None else None),
            ("shortCode", short_code),
            ("teamId", team_id),
            ("language", language),
            ("tags", list(tags) if tags is not None else None),
        ):
            if value is not None:
                payload[key] = value
        payload.update(extra)
        return self._post_obj("/v1/macros", payload)

    def update(self, macro_id: str, **fields: Any) -> JsonDict:
        """Update a macro. Every field is optional.

        Takes the same **wire** names as the response — ``name``, ``body``,
        ``actions``, ``shortCode``, ``teamId``, ``scope``, ``language``,
        ``tags`` — rather than snake_case keywords, so that an explicit
        ``None`` can reach the server. That matters here: omitting
        ``shortCode`` leaves it alone, while ``shortCode=None`` clears it.
        The same is true of ``teamId``.

            client.macros.update(macro_id, body="Updated text")
            client.macros.update(macro_id, shortCode=None)  # clear it

        The "body or actions must be non-empty" rule only fires when both are
        present in the same call.
        """
        return self._patch_obj(f"/v1/{encode_path('macros', macro_id)}", dict(fields))

    def delete(self, macro_id: str) -> None:
        """Delete a macro. Returns ``None`` — the route answers 204, no body."""
        self._delete(f"/v1/{encode_path('macros', macro_id)}")
        return None


__all__ = ["Macros"]
