"""``client.customer_cards`` — panels your own backend renders in the inbox."""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list


class CustomerCards(Resource):
    """Configure the cards Chatly fetches from your service per contact.

    A card is ``{"id", "key", "title", "url", "headerNames", "ttlSeconds",
    "enabled", "position"}``. **There is no ``headers`` field and no
    ``secret`` field on any read** — only the header *names*, so a
    configuration can be audited without exposing what it sends.

    Reads need ``integrations:read``, writes ``integrations:write``. A
    workspace may configure **25 cards**; the 26th is a 400 from inside the
    insert.

    To actually render cards for a contact, call
    :meth:`chatly.resources.contacts.Contacts.cards`.
    """

    def list(self) -> List[JsonDict]:
        """Every configured card. A bare list, no cursor.

        ``headerNames`` is names only. A row whose encrypted header bag
        cannot be decrypted comes back with ``[]`` rather than failing the
        list — so an empty list there means "unreadable", not "none
        configured".
        """
        return as_list(self._get("/v1/customer-cards"))

    def create(
        self,
        *,
        key: str,
        title: str,
        url: str,
        ttl_seconds: int,
        headers: Optional[Mapping[str, str]] = None,
        enabled: Optional[bool] = None,
        **extra: Any,
    ) -> JsonDict:
        """Register a card. Answers 201 with ``{"card", "secret"}``.

        Args:
            key: ``[A-Za-z0-9_-]``, 1–64 characters. Unique per workspace —
                a duplicate is a **409**.
            title: 1–80 characters, shown above the panel.
            url: your endpoint, ≤2000 characters. **https only**, no
                embedded credentials, and refused for a private, link-local,
                ``.local``, ``.internal`` or IPv6-literal host.
            ttl_seconds: how long Chatly may cache a response, 15 to
                31,536,000. Required — there is no default.
            headers: up to 10 plain headers. Reserved names are 400s,
                including ``content-type``, ``accept``, ``host`` and every
                ``x-chatly-*`` name Chatly sends itself.
            enabled: default ``True``.

        ``position`` is **not** accepted here: a new card goes last, and
        reordering is :meth:`update`.

        **``secret`` sits beside the card, not inside it, and this is one of
        only two times it is ever readable** — the other is
        :meth:`rotate_secret`. It is ``cc_``-prefixed, there is no read-back
        route, and a caller who loses it has to rotate.
        """
        body: JsonDict = {
            "key": key,
            "title": title,
            "url": url,
            "ttlSeconds": ttl_seconds,
        }
        for name, value in (
            ("headers", dict(headers) if headers is not None else None),
            ("enabled", enabled),
        ):
            if value is not None:
                body[name] = value
        body.update(extra)
        return self._post_obj("/v1/customer-cards", body)

    def update(self, card_id: str, **fields: Any) -> JsonDict:
        """Update a card. Every field optional, **wire** names.

        Takes everything :meth:`create` does — ``key``, ``title``, ``url``,
        ``ttlSeconds``, ``headers``, ``enabled`` — plus ``position``
        (0–1000), which is the only way to reorder.

        **``headers={}`` clears the bag**; it does not mean "no change".
        Omitting the key is what leaves the stored headers alone. The
        distinction is invisible in JSON and has cost people their
        authentication header.

        An unknown id is a 404. The id is not validated as a UUID by the
        server, so a malformed one surfaces as a 500 — pass one from
        :meth:`list`.
        """
        return self._patch_obj(
            f"/v1/{encode_path('customer-cards', card_id)}", dict(fields)
        )

    def rotate_secret(self, card_id: str) -> JsonDict:
        """Mint a new per-card secret. Answers 201 with ``{"secret"}``.

        **This is not the two-phase rotation its namesake performs.** It
        overwrites the live secret in one statement: the old one stops
        verifying immediately, so your endpoint must already accept the new
        value — which means updating your service *after* this call returns
        and before the next card fetch, or accepting a gap.

        The two-phase version, where the receiver picks the moment of the
        switch, is
        :meth:`chatly.resources.customer_card_endpoints.CustomerCardEndpoints.rotate_secret`
        plus ``activate_secret``. Configure an endpoint for the URL if the
        hard cut is not acceptable.

        Returned once; a 404 for an unknown id.
        """
        return self._post_obj(
            f"/v1/{encode_path('customer-cards', card_id)}/rotate-secret"
        )

    def delete(self, card_id: str) -> JsonDict:
        """Delete a card. Returns ``{"ok": true}`` with a **200**, not a 204.

        ``ok`` is a literal ``True``. A 404 for an unknown id — unlike
        several other deletes on this surface, this one does check.
        """
        return self._delete_obj(f"/v1/{encode_path('customer-cards', card_id)}")


__all__ = ["CustomerCards"]
