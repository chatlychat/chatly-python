"""``client.macros`` — saved replies and the actions attached to them."""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list


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
    ) -> List[JsonDict]:
        """Macros, ranked by language match, then use count, then recency.

        Args:
            scope: ``workspace``, ``team`` or ``personal``.
            team: a team id. **The wire name is ``team``, not ``teamId``** —
                unlike the macro body, which uses ``teamId``.
            query: a name/body substring, up to 120 characters.
            language: a BCP-47-ish tag up to 8 characters. It **ranks** rather
                than filters: a macro in another language still comes back,
                lower down.

        Returns a **plain list**, not a
        :class:`~chatly.pagination.Page`. Despite being a collection, this
        route is pagination-exempt: it takes no ``cursor`` and no ``limit``,
        and answers with a bare JSON array that the service caps at 200 rows
        ordered by usage rank. There is no cursor to walk, so there is no
        ``iter_list`` here — a workspace with more than 200 macros sees only
        200, and the way to narrow that is ``query`` or ``scope``, not
        paging.
        """
        return as_list(
            self._get(
                "/v1/macros",
                {"scope": scope, "team": team, "query": query, "language": language, **params},
            )
        )

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

    def get(self, macro_id: str) -> JsonDict:
        """One macro by id.

        A missing macro is a 404 — and so is **somebody else's
        ``personal``-scope macro**, because the row is hidden by a row-level
        security policy rather than refused by a permission check. You cannot
        tell the two apart, which is deliberate: a 403 would confirm the
        macro exists.

        That has a consequence for an API key specifically. A key's
        "user id" is the key's own id unless it is linked to a machine user,
        so a key sees ``workspace`` and ``team`` macros and **never a
        personal one** — not even one created by the agent who minted the
        key.
        """
        return self._get_obj(f"/v1/{encode_path('macros', macro_id)}")

    def actions(self) -> JsonDict:
        """The action vocabulary a macro's ``actions`` may use.

        Returns ``{"limit", "actions"}`` — **an object, not a list**. The
        actions are under ``actions``, each
        ``{"key", "label", "description", "permission"}``; eleven of them
        today, and the list is shared with the conversation-action registry
        rather than owned by macros.

        ``limit`` is the ceiling on actions in **one** macro (16), not a page
        size and not the number of action kinds. Read it instead of hard-coding
        the number: :meth:`create` rejects a longer list with a 400, and
        ``permission`` on each row tells you which grant an agent needs
        before the action will run for them.

        Static for the whole platform, so cache it rather than calling it per
        macro form.
        """
        return self._get_obj("/v1/macros/actions")

    def templates(self) -> JsonDict:
        """The built-in macro starter templates.

        Returns ``{"items", "total"}`` — **an object, not a list and not a
        page**. ``total`` always equals ``len(items)``: the catalogue is a
        frozen in-process array of 30 entries, so ``total`` is never a hint
        that a second page exists.

        Rows are a summary shape carrying ``bodyPreview`` rather than the
        full ``body``; fetch one with :meth:`template` to get the text you
        would actually store.
        """
        return self._get_obj("/v1/macros/templates")

    def template(self, slug: str) -> JsonDict:
        """One starter template, with its full body.

        Returns ``{"slug", "name", "body", "category", "language", "tags"}``
        plus ``actions`` and ``shortCode`` — and those last two are
        **absent keys rather than nulls** when the template does not set
        them, so use ``.get()``.

        ``category`` is one of ``greeting``, ``acknowledgement``,
        ``resolution``, ``billing``, ``support``, ``product``, ``lifecycle``,
        ``compliance``.

        An unknown slug is a 404. A template is a starting point, not a
        macro: nothing exists in the workspace until you pass these fields
        to :meth:`create`.
        """
        return self._get_obj(f"/v1/{encode_path('macros', 'templates', slug)}")

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
