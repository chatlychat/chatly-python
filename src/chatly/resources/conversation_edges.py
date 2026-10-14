"""The conversation routes that are *about* a thread rather than in it.

Split out of :mod:`chatly.resources.conversations` because that file reached
the 650-line ceiling the contract sets (§9), and these six are the coherent
half to move: none of them reads or writes the message stream the way
``messages``/``send`` do. They answer four different questions a thread
raises once it exists — what it was merged with, what it achieved, who owns
it now, and what the badges say — plus the one route that edits a message
already sent.

It is a mixin rather than a second namespace on the client on purpose:
``surface.json`` groups all six under ``conversations``, so
``client.conversations`` has to expose them. The split is in the source, not
in the API.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from .._transport import encode_path
from ._base import JsonDict, Resource


class ConversationEdges(Resource):
    """The methods :class:`chatly.resources.conversations.Conversations`
    inherits. Not meant to be instantiated directly — reach them through
    ``client.conversations``.
    """

    def linked(self, conversation_id: str) -> JsonDict:
        """Conversations merged into or out of this one.

        Returns ``{"items": [...]}`` — an object around a list, with **no
        cursor**, so this is not a page.

        Each item is ``{"id", "subject", "status", "relation", "mergedAt"}``.
        ``relation`` is exactly two values: ``merged_into`` is the single
        thread this one was absorbed by, ``merged_from`` are the threads it
        absorbed.

        **Despite the name this is the merge graph**, not the "mark as
        duplicate" link — if you are looking for the latter, this is not it.

        ``mergedAt`` is derived from the other row and is ``None`` when that
        row has no close time. Items your inbox scope excludes are silently
        omitted, so this can legitimately be shorter for a restricted
        credential.

        One rough edge: the ``merged_from`` side has no cap, so a thread that
        absorbed five hundred duplicates returns five hundred items. And the
        id is not validated here, so a malformed one surfaces as a server
        error rather than a 400.
        """
        return self._get_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/linked"
        )

    def outcomes(self, conversation_id: str) -> JsonDict:
        """What this conversation achieved: resolutions, escalations, sales.

        Returns ``{"conversationId", "items"}`` — an ``items`` key with no
        cursor, so not a page.

        Items are merged from three places and ordered newest first. Each is
        ``{"outcome", "recordId", "recordedIn", "recordedAt", "source",
        "reason", "valueCents", "currency", "outcomeRef"}``. ``outcome`` is
        ``resolved``, ``escalated`` or ``purchased``; the last three fields
        are non-null on ``purchased`` only.

        **``source`` is the field this read exists for.** It says *who
        decided*: ``agent_report`` is this API, ``visitor_chip`` is the
        visitor pressing "this answered my question" in the widget, and
        ``bot_handoff``/``agent_request`` are escalation routes. Treat it as
        an open string.

        **Each of the three sources is capped at 20 items, silently.** There
        is no cursor and no flag, so a very long conversation can be
        truncated at 60 rows with nothing saying so.
        """
        return self._get_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/outcomes"
        )

    def record_outcome(
        self,
        conversation_id: str,
        outcome: str,
        *,
        reason: Optional[str] = None,
        message_id: Optional[str] = None,
        value_cents: Optional[int] = None,
        currency: Optional[str] = None,
        outcome_ref: Optional[str] = None,
        **extra: Any,
    ) -> JsonDict:
        """Record an outcome against a conversation. Answers 201.

        Args:
            outcome: ``resolved``, ``escalated`` or ``purchased``.
            reason: up to 2000 characters, trimmed. Schema-optional, but
                effectively required on ``escalated`` — it becomes the
                handoff reason and the internal note an agent reads.
            message_id: the message the outcome is attributed to.
            value_cents: 0 to 1,000,000,000. **Refused, not ignored, on
                ``resolved`` and ``escalated``.**
            currency: three letters, upper-cased server-side. **Required
                whenever ``value_cents`` is given.**
            outcome_ref: 1–200 characters. **Required when ``outcome`` is
                ``purchased``**, and unique per workspace forever — it is the
                only thing standing between a retry from another process and
                a double-counted purchase.

        Returns ``{"outcome", "conversationId", "recordId", "recordedIn",
        "recordedAt", "created", "feeds"}``. ``recordId`` is nullable (the
        escalation path returns no row id) and ``feeds`` is a human sentence
        saying where the number will show up.

        **``created: False`` means an equal outcome was already on record and
        this call changed nothing** — a replayed ``resolved`` within 24 hours
        per source, an ``escalated`` within 60 seconds, or a ``purchased``
        whose ``outcome_ref`` we already hold. It is 201 either way, never a
        409, so read the flag.

        **``escalated`` is not merely recorded: it really hands the thread
        over.** Status becomes ``pending``, bot ownership is released, and
        your ``reason`` is posted as an internal note. Do not use it to
        annotate history.

        And **``purchased`` writes an event against the contact that no
        report in this product sums.** The amount is stored and totalled
        nowhere; it is for your own analytics to pull back out.

        The body is strict, so an unknown key is a 400 rather than a silent
        drop.
        """
        body: JsonDict = {"outcome": outcome}
        for key, value in (
            ("reason", reason),
            ("messageId", message_id),
            ("valueCents", value_cents),
            ("currency", currency),
            ("outcomeRef", outcome_ref),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return self._post_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/outcomes", body
        )

    def return_to_bot(self, conversation_id: str, bot_id: str) -> JsonDict:
        """Hand an open thread back to a bot. Answers 201.

        Returns ``{"returned": true, "conversationId", "botId", "botName",
        "returnedAt"}``.

        **It changes assignment**: the human assignee is cleared and the bot
        becomes the assignee in one statement, so the thread leaves the agent
        queue. It also posts a private internal note ("Handed back to …") —
        nothing visitor-facing — and publishes
        ``conversation.returned_to_bot``.

        Needs **``conversations:assign``**, a higher bar than replying, and
        deliberately so.

        Four refusals worth knowing, all 400s:

        * the conversation must be ``open`` — ``pending``, ``snoozed``,
          ``closed`` and ``merged`` are each refused with their own reason;
        * the bot must be ``active`` — a paused or draft bot is refused
          rather than quietly assigned;
        * a thread **another** assistant already owns is refused, not
          overwritten (use a bot-to-bot transfer for that);
        * an unknown conversation or bot is a 404.

        **Returning a thread to the bot that already owns it is a success**,
        with a fresh ``returnedAt`` and no write performed — so this is safe
        to call defensively.

        This is the one write in this namespace a key may call, and it works
        because it records a *null* actor for a key rather than stamping the
        key's own id into a field the inbox renders as a person.
        """
        return self._post_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/return-to-bot",
            {"botId": bot_id},
        )

    def unread_counts(self, *, brand: Optional[str] = None, **params: Any) -> JsonDict:
        """The inbox sidebar's badge numbers.

        Args:
            brand: a brand id — and note the wire name is ``brand``, not
                ``brandId``. It is unvalidated, so a non-UUID value is a
                server error rather than a 400.

        Returns ``{"unread", "mentions", "participating", "unattended",
        "byInbox", "byTeam", "byLabel"}``.

        **These are per-USER counts, and an API key is not a user.** The
        numbers are computed against ``membership.userId``, which for a key
        is the machine user it acts as — or, for an unlinked key, the key's
        own id, which has no read watermark and appears in no mention or
        participant row. So an unlinked key sees every open conversation as
        unread and gets a **structural zero** for ``mentions`` and
        ``participating``. It does not fail, which is exactly why this needs
        saying: link the key to a machine user, or treat this as an
        agent-dashboard endpoint and not an integration one.

        **``mentions``, ``participating`` and ``unattended`` are subsets of
        ``unread``** — summing them double-counts. Only open conversations
        are counted.

        ``byInbox``/``byTeam`` omit null channel and team rows entirely.
        ``byLabel`` is capped at 50 buckets ordered by count, and labels
        beginning ``__`` are stripped as internal. Every number is narrowed
        by the caller's inbox scope, so a badge never counts a row the caller
        cannot open.

        A key granted only ``conversations:read:assigned`` gets zeros
        throughout, since nothing is assigned to it.
        """
        return self._get_obj(
            "/v1/conversations/unread-counts", {"brand": brand, **params}
        )

    def update_blocks(
        self,
        conversation_id: str,
        message_id: str,
        patches: Sequence[Mapping[str, Any]],
    ) -> JsonDict:
        """Patch the rich blocks of one already-sent message.

        Args:
            patches: 1–50 of ``{"id", "set"}``, where ``id`` names a block
                (top-level first, then cards inside a grid block) and ``set``
                is the fields to merge into it. Each patch is strict — those
                two keys and nothing else.

        Returns ``{"id", "blocks", "body"}``. ``blocks`` comes back as
        unvalidated JSON on purpose, so re-validate at your render boundary;
        ``body`` is included because a patch can change the plain-text
        rendition, which is what email and SMS copies of the thread carry.

        **The batch is all-or-nothing.** An unknown block id is a 404, and a
        batch whose *merged* result fails block validation refuses the whole
        batch — a half-applied patch would leave a shape no author ever
        wrote. ``type`` cannot be patched, and trying surfaces as that same
        invalid-merge refusal rather than as a field error.

        A message with no rich blocks is refused: there is nothing to patch,
        and this will not create blocks on a plain message.

        Publishes ``message.updated``, so an open widget re-renders without
        polling. This is the typical way a card is marked "paid" or an
        in-chat form is disabled after submission.
        """
        return self._patch_obj(
            f"/v1/{encode_path('conversations', conversation_id, 'messages', message_id)}/blocks",
            {"patches": [dict(patch) for patch in patches]},
        )

__all__ = ["ConversationEdges"]
