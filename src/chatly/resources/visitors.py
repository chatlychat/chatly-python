"""``client.visitors`` — opening a thread with someone who has not written.

ONE method, and the other two routes on that controller are deliberately
absent. ``GET /v1/visitors/live`` and ``GET /v1/visitors/{contactId}/pages``
sit beside :meth:`Visitors.start_conversation` in
``apps/api/src/modules/visitors/visitors.controller.ts`` and carry **no**
``@AllowApiKey()``, so a ``ck_`` key gets a 403 from both. They are not SDK
surface: shipping a method that always fails is worse than not shipping one,
because the failure arrives at runtime, in production, in somebody else's
integration. Reach them with a signed-in session, or not at all.
"""

from __future__ import annotations

from .._transport import encode_path
from ._base import JsonDict, Resource


class Visitors(Resource):
    """Proactive outreach: start a conversation the contact did not start.

    Everything else in this SDK answers or reads a thread the *contact*
    opened. This namespace is the one that reaches out first, which is why it
    is gated by a workspace decision rather than by a scope alone — see
    :meth:`start_conversation`.

    Needs ``conversations:write``.
    """

    def start_conversation(self, contact_id: str) -> JsonDict:
        """Open a conversation with a contact who did **not** write first.

        ``POST /v1/visitors/{contactId}/start-conversation``. Takes no body
        and no query parameters — the contact id is the whole input. Returns
        ``{"conversationId": ...}``.

        Args:
            contact_id: the contact to reach. Percent-encoded into the path.

        ─── A 403 HERE IS PROBABLY NOT YOUR SCOPES ──────────────────────

        **This is off by default, per workspace.** The flag is
        ``settings.proactiveOutreach.apiKeysMayStartConversations``. An owner
        or admin turns it on with ``PATCH /v1/workspace/settings``, which
        needs a signed-in person and so is **not reachable from this SDK**;
        you can read the current value with
        :meth:`chatly.resources.workspace.Workspace.settings`, which is
        key-accessible.

        So a :class:`~chatly.errors.PermissionDeniedError` from this method
        means one of two quite different things, and the workspace setting is
        the likelier one. The scope is **not** the opt-in:
        ``conversations:write`` was already grantable and is already held by
        keys minted for ticket bulk actions and schedule-send, so opening
        this route on the permission alone would have handed cold outreach to
        credentials nobody re-reviewed. Check the setting before you go
        looking at your key.

        ─── THE OTHER TWO THINGS TO KNOW ────────────────────────────────

        **Three per contact per hour.** The limit is counted per workspace
        and per *contact*, not per caller — the abuse shape here is N threads
        aimed at one person, which a per-caller limit cannot see. The fourth
        call inside the window raises
        :class:`~chatly.errors.RateLimitError` with ``retry_after`` set to
        the window's remaining TTL.

        Worth knowing where that number comes from, because it is not where
        the contract's other 429s put it. This refusal sends **no
        ``Retry-After`` header**: the API's exception filter sets no headers,
        and the hook that synthesises one only folds the buckets
        ``@nestjs/throttler`` emits, which this check is not. The TTL travels
        in the body instead, at ``error.details["retryAfterSeconds"]``, and
        this SDK reads it from there when the header is absent — so
        ``retry_after`` is populated either way. The route additionally
        inherits the global ceilings (30 per second, 100 per fifteen minutes)
        and a 429 from those *does* carry the header.

        **An offline visitor is not notified.** The greeting is persisted and
        the widget renders it from history on their next page view: no email,
        no push, no provider message, and nothing queued or dropped. An
        integration that needs to reach someone who has left the site wants
        an email or SMS conversation instead of this.

        The controller declares ``@RequireIdempotencyKey()`` at class level
        with no opt-out on this handler, so the key is **required** rather
        than merely honoured — without one the API answers 428 in
        production. This SDK mints one per call; pin one with
        :meth:`chatly.ChatlyClient.with_idempotency_key` if a retry across
        process restarts must replay the first outreach rather than open a
        second thread.

        An unknown contact, or one in another workspace, is a 404. A contact
        who has blocked or unsubscribed is refused rather than messaged.
        """
        return self._post_obj(
            f"/v1/{encode_path('visitors', contact_id)}/start-conversation"
        )


__all__ = ["Visitors"]
