"""``client.customer_card_endpoints`` — one signing identity per card URL."""

from __future__ import annotations

from typing import List

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list


class CustomerCardEndpoints(Resource):
    """Group the cards that share a URL behind one rotatable secret.

    Without an endpoint, every card signs with its own ``cc_`` secret and
    Chatly sends ``x-chatly-card-id`` so the receiver can tell which. With
    one, **every request to that URL is signed by the endpoint's ``cce_``
    secret and that header stops being sent** — so creating one is a
    behaviour change at your service, not just a configuration tidy-up.
    Deploy the verifier first.

    An endpoint is ``{"id", "url", "cardKeys", "pendingSecretSet",
    "pendingSecretMintedAt", "createdAt", "updatedAt"}``. Reads need
    ``integrations:read``, writes ``integrations:write``.

    **The rotation here is two-phase**, which is the whole reason this
    resource exists: :meth:`rotate_secret` mints an inert secret,
    :meth:`activate_secret` promotes it, and the receiver chooses when. The
    per-card :meth:`chatly.resources.customer_cards.CustomerCards.rotate_secret`
    is a hard cut. Same verb, different operation.
    """

    def list(self) -> List[JsonDict]:
        """Every endpoint. A bare list, no cursor.

        **No read ever carries a secret.** ``pendingSecretSet`` is a bare
        boolean on purpose — no prefix, no last four characters, no hash —
        and ``pendingSecretMintedAt`` is ``None`` when nothing is pending.

        ``cardKeys`` is the set of configured cards pointing at this URL.
        **``[]`` means the endpoint signs nothing**: every card that used the
        URL was deleted or re-pointed, and the row is now an orphan. It is
        the only way to spot one.
        """
        return as_list(self._get("/v1/customer-card-endpoints"))

    def create(self, url: str) -> JsonDict:
        """Claim a URL. Answers 201 with ``{"endpoint", "secret"}``.

        ``secret`` is ``cce_``-prefixed — deliberately **not** the card's
        ``cc_``, because the two go in different slots of your
        configuration — and it is readable only here.

        The URL must already be used by at least one configured card: a URL
        no card uses is a 400 that enumerates the ones that do. **URLs
        compare byte for byte, trailing slash included**, so a card
        registered at ``/cards`` is not matched by an endpoint claiming
        ``/cards/``. A URL that already has an endpoint is a 409.

        The body is strict, so this method sends exactly ``{"url": ...}``.

        From this call onward, requests to that URL are signed with this
        secret and carry no ``x-chatly-card-id``.
        """
        return self._post_obj("/v1/customer-card-endpoints", {"url": url})

    def rotate_secret(self, endpoint_id: str) -> JsonDict:
        """Mint a **pending** secret. Answers 201 with ``{"secret", "active"}``.

        ``active`` is the literal ``False``, and it is not decoration: **the
        secret you are handed signs nothing yet.** Nothing about the live
        traffic changes until :meth:`activate_secret`.

        Correct order: rotate, deploy the new secret at your endpoint, then
        activate.

        Calling this twice before activating **replaces** the pending secret
        rather than erroring — deliberate, because an operator who lost the
        value it printed has no way to read it back.
        """
        return self._post_obj(
            f"/v1/{encode_path('customer-card-endpoints', endpoint_id)}/rotate-secret"
        )

    def activate_secret(self, endpoint_id: str) -> JsonDict:
        """Promote the pending secret. Answers 201 ``{"activated": true}``.

        **The previous secret is gone, with no undo.** Call this only once
        your endpoint accepts the pending value.

        With nothing pending this is a **409**, not a no-op — a caller asking
        twice has lost track of a rotation, and answering "fine" would hide
        that.

        The overlap this resource provides is an *order of operations*, not a
        span of time: Chatly sends one signature per request, so at every
        instant exactly one secret is live. What two-phase rotation buys is
        that **you** pick the instant.
        """
        return self._post_obj(
            f"/v1/{encode_path('customer-card-endpoints', endpoint_id)}/activate-secret"
        )

    def delete(self, endpoint_id: str) -> JsonDict:
        """Release a URL. Returns ``{"ok": true}`` with a **200**.

        **This is a behaviour change at your service, not a cleanup.**
        Signing reverts to each card's own ``cc_`` secret and
        ``x-chatly-card-id`` starts being sent again — so a receiver written
        against the endpoint secret begins rejecting every request.

        A 404 for an unknown id.
        """
        return self._delete_obj(
            f"/v1/{encode_path('customer-card-endpoints', endpoint_id)}"
        )


__all__ = ["CustomerCardEndpoints"]
