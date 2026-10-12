"""``client.conversations`` — threads, messages, and the agent-handling handshake."""

from __future__ import annotations

from typing import Any, Iterator, List, Mapping, Optional, Sequence, Union

from .._transport import encode_path
from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, as_list, csv, flag


class Conversations(Resource):
    """Read threads, send messages, schedule sends, and propose replies.

    A conversation object carries ``id``, ``workspaceId``, ``brandId``,
    ``channelType``, ``channelId``, ``contactId``, ``assigneeUserId``,
    ``assigneeAiBotId``, ``agentHandling`` (a nested object), ``reopenCount``,
    ``teamId``, ``status`` (``open|pending|snoozed|closed|merged``),
    ``priority`` (``low|normal|high|urgent``), ``subject``,
    ``lastMessagePreview``, ``lastMessageAt``, ``unreadAgentCount``,
    ``unreadContactCount``, ``tags``, ``createdAt``, ``updatedAt``,
    ``closedAt``.

    Closing, reopening, assigning, marking read and bulk operations are
    absent on purpose: they record *who* acted, so they answer an API key
    with 403.
    """

    def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        status: CsvValue = None,
        channel: CsvValue = None,
        tags: CsvValue = None,
        priority: CsvValue = None,
        assignee: Optional[str] = None,
        team: Optional[str] = None,
        segment: Optional[str] = None,
        brand: Optional[str] = None,
        sort: Optional[str] = None,
        unread: Optional[bool] = None,
        mentioned: Optional[bool] = None,
        unattended: Optional[bool] = None,
        sla: Optional[bool] = None,
        unattended_for: Optional[int] = None,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        filter: Optional[str] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of conversations.

        Args:
            cursor: from the previous page's ``next_cursor``.
            limit: 1–100, default 25, clamped rather than rejected.
            status: ``open``, ``pending``, ``snoozed``, ``closed``,
                ``merged``. A list is comma-joined into one parameter,
                because that is how this route reads it.
            channel: channel types, same comma-joined form.
            tags: tag names, comma-joined.
            priority: ``low``, ``normal``, ``high``, ``urgent``, comma-joined.
            assignee: an agent's user id, or ``unassigned``.
            team: a team id.
            segment: a saved-segment id.
            brand: a brand id, for a multi-brand workspace.
            sort: ``last_message_at_desc`` (default),
                ``last_message_at_asc``, ``priority_desc``, ``unread_desc``,
                ``created_at_desc``. An unrecognised value falls back to the
                default silently.
            unread: only threads with unread agent messages. ``False`` is
                sent as *omitted*, because this route reads anything other
                than ``"true"`` as off and sending ``false`` would be
                indistinguishable from not filtering.
            mentioned: only threads mentioning the caller.
            unattended: only threads nobody has answered.
            sla: only threads in SLA warning or breach.
            unattended_for: minutes, positive, capped at 10080 (7 days).
            from_: ISO-8601 lower bound on *message activity*. Named with the
                trailing underscore because ``from`` is a Python keyword; it
                is sent as ``from``.
            to: upper bound on message activity.
            created_from: ISO-8601 lower bound on *creation*. Different axis
                from ``from_`` — a thread created last month with a message
                today matches ``from_`` but not ``created_from``.
            created_to: upper bound on creation.
            filter: a base64 JSON group tree, as built by the dashboard's
                advanced filter. **It supersedes every flat parameter above
                when present**, and it is the only parameter on this route
                that returns 400 for bad input rather than being ignored.

        Everything except ``filter`` fails open: an unrecognised value is
        dropped and you get a wider result set, not an error. Check the
        returned rows rather than trusting that a filter applied.
        """
        return self._page("/v1/conversations", self._list_query(locals()))

    def iter_list(self, **params: Any) -> Iterator[JsonDict]:
        """Every conversation matching the filters, as a generator.

        Takes the same keyword arguments as :meth:`list` (minus ``cursor``,
        which the walk owns).

            for convo in client.conversations.iter_list(status="open"):
                print(convo["id"], convo["lastMessagePreview"])
        """
        params.pop("cursor", None)
        query = self._list_query({"params": params})
        return self._walk("/v1/conversations", query)

    @staticmethod
    def _list_query(scope: Mapping[str, Any]) -> JsonDict:
        """Translate :meth:`list`'s arguments into wire parameters.

        Shared by :meth:`list` and :meth:`iter_list` so the two cannot drift
        — the translation table (``from_`` → ``from``, CSV joining, boolean
        flags) is the part most likely to be fixed in one place only.
        """
        extra = dict(scope.get("params") or {})
        out: JsonDict = {
            "cursor": scope.get("cursor"),
            "limit": scope.get("limit"),
            "status": csv(scope.get("status")),
            "channel": csv(scope.get("channel")),
            "tags": csv(scope.get("tags")),
            "priority": csv(scope.get("priority")),
            "assignee": scope.get("assignee"),
            "team": scope.get("team"),
            "segment": scope.get("segment"),
            "brand": scope.get("brand"),
            "sort": scope.get("sort"),
            "unread": flag(scope.get("unread")),
            "mentioned": flag(scope.get("mentioned")),
            "unattended": flag(scope.get("unattended")),
            "sla": flag(scope.get("sla")),
            "unattendedFor": scope.get("unattended_for"),
            "from": scope.get("from_"),
            "to": scope.get("to"),
            "createdFrom": scope.get("created_from"),
            "createdTo": scope.get("created_to"),
            "filter": scope.get("filter"),
        }
        out = {k: v for k, v in out.items() if v is not None}
        # `iter_list` funnels its keyword arguments through `params`; apply the
        # same translation to them so `status=["open"]` behaves identically
        # whichever entry point you came in through.
        for key, value in extra.items():
            if value is None:
                continue
            if key in {"status", "channel", "tags", "priority"}:
                out[key] = csv(value)
            elif key in {"unread", "mentioned", "unattended", "sla"} and isinstance(value, bool):
                flagged = flag(value)
                if flagged is not None:
                    out[key] = flagged
            elif key == "from_":
                out["from"] = value
            elif key == "unattended_for":
                out["unattendedFor"] = value
            elif key == "created_from":
                out["createdFrom"] = value
            elif key == "created_to":
                out["createdTo"] = value
            else:
                out[key] = value
        return out

    def get(self, conversation_id: str) -> JsonDict:
        """One conversation by id."""
        return self._get_obj(f"/v1/{encode_path('conversations', conversation_id)}")

    def messages(
        self,
        conversation_id: str,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of messages in a thread.

        ``limit`` defaults to 50 here (not 25) and is clamped to 1–100.

        A message carries ``id``, ``conversationId``, ``authorType``
        (``agent|contact|bot|system``), ``authorId``, ``kind``, ``body``,
        ``attachments``, ``metadata``, ``createdAt``, ``deliveredAt``,
        ``readAt``, ``replyToMessageId``, ``replyTo`` and the edit/delete
        audit fields. Several fields — ``bodyHtml``, ``streamState``,
        ``hiddenFromContact``, ``clientRef``, ``llmText`` — may be **absent
        rather than null**, so read them with ``.get()``.
        """
        return self._page(
            f"/v1/{encode_path('conversations', conversation_id)}/messages",
            {"cursor": cursor, "limit": limit, **params},
        )

    def iter_messages(
        self, conversation_id: str, *, limit: Optional[int] = None, **params: Any
    ) -> Iterator[JsonDict]:
        """Every message in a thread, as a generator."""
        return self._walk(
            f"/v1/{encode_path('conversations', conversation_id)}/messages",
            {"limit": limit, **params},
        )

    def send(
        self,
        conversation_id: str,
        body: str,
        *,
        kind: Optional[str] = None,
        attachments: Optional[Sequence[Mapping[str, Any]]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        blocks: Optional[Sequence[Mapping[str, Any]]] = None,
        body_html: Optional[str] = None,
        canvas: Optional[Mapping[str, Any]] = None,
        client_ref: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
        **extra: Any,
    ) -> JsonDict:
        """Post a message into a thread. Returns the created message.

        Args:
            conversation_id: the thread. Taken from the path — you do not
                need to repeat it in the body, and if you do the path wins.
            body: the text, up to 10,000 characters. May be ``""`` (for an
                attachment-only message).
            kind: ``text`` (default), ``rich``, ``note`` (internal, not shown
                to the contact), ``system_event`` or ``attachment_only``.
            attachments: ``{"id", "filename", "mimeType", "sizeBytes",
                "url"}`` objects. Upload first; this only references.
            metadata: an open object stored with the message.
            blocks: structured message blocks.
            body_html: HTML, sanitised server-side. **It overwrites
                ``body``** — the server derives plain text from the HTML and
                discards whatever you sent as ``body``. Send one or the
                other, not both.
            canvas: a canvas payload.
            client_ref: your own 1–128 character reference, echoed back on
                the message. Useful for matching a send to your own record
                without relying on the id round-trip.
            reply_to_message_id: quote an earlier message.

        ``Idempotency-Key`` is minted automatically, so a network-level retry
        inside this SDK cannot post the message twice. To retry the same send
        yourself across process restarts, pin a key —
        :meth:`chatly.ChatlyClient.with_idempotency_key`.
        """
        payload: JsonDict = {"body": body}
        for key, value in (
            ("kind", kind),
            ("attachments", list(attachments) if attachments is not None else None),
            ("metadata", metadata),
            ("blocks", list(blocks) if blocks is not None else None),
            ("bodyHtml", body_html),
            ("canvas", canvas),
            ("clientRef", client_ref),
            ("replyToMessageId", reply_to_message_id),
        ):
            if value is not None:
                payload[key] = value
        payload.update(extra)
        return self._post_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/messages", payload
        )

    def unattended(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        assignee: Optional[str] = None,
        team: Optional[str] = None,
        channel: Optional[str] = None,
        older_than_minutes: Optional[int] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """Threads waiting on a first human answer.

        The only list in this SDK that reports ``total`` as well as
        ``next_cursor`` — ``page.total`` is the size of the whole backlog,
        not of the page, which is the number a staffing dashboard wants.

        ``older_than_minutes`` is in minutes, positive, silently capped at
        10080 (7 days).
        """
        return self._page(
            "/v1/conversations/unattended",
            {
                "cursor": cursor,
                "limit": limit,
                "assignee": assignee,
                "team": team,
                "channel": channel,
                "olderThanMinutes": older_than_minutes,
                **params,
            },
        )

    def iter_unattended(
        self,
        *,
        limit: Optional[int] = None,
        assignee: Optional[str] = None,
        team: Optional[str] = None,
        channel: Optional[str] = None,
        older_than_minutes: Optional[int] = None,
        **params: Any,
    ) -> Iterator[JsonDict]:
        """Every unattended thread, as a generator.

            for convo in client.conversations.iter_unattended(older_than_minutes=30):
                escalate(convo["id"])

        Yields rows, so the envelope's ``total`` is not visible here — call
        :meth:`unattended` when you want the backlog size rather than the
        backlog. Note the two disagree by design on a busy workspace: ``total``
        is computed per request, so a queue being worked while you walk it can
        yield fewer rows than the first page's ``total`` promised.
        """
        return self._walk(
            "/v1/conversations/unattended",
            {
                "limit": limit,
                "assignee": assignee,
                "team": team,
                "channel": channel,
                "olderThanMinutes": older_than_minutes,
                **params,
            },
        )

    def agent_handling(self, conversation_id: str) -> JsonDict:
        """Who or what is currently handling a thread.

        Returns ``{"conversationId", "handling": {"state", "actorUserId",
        "reason", "updatedAt"}, "escalated", "status"}``. ``handling.state``
        reads back as ``in_progress``, ``handed_off``, ``handled``,
        ``taken_over`` or ``null``.
        """
        return self._get_obj(f"/v1/{encode_path('conversations', conversation_id)}/agent-handling")

    def set_agent_handling(
        self, conversation_id: str, state: str, *, reason: Optional[str] = None
    ) -> JsonDict:
        """Claim, hand off, or finish handling a thread as a machine agent.

        Args:
            state: ``in_progress``, ``handed_off`` or ``handled``.
                ``taken_over`` is written by the platform when a human takes
                a thread from a bot, and sending it is a 400.
            reason: up to 2000 characters, shown in the thread's audit trail.

        **This route needs an API key linked to a machine user.** A key
        without one gets 403, and so does a signed-in human session: it is
        the write half of the bring-your-own-agent protocol, and the point is
        that the actor is identifiable as a non-person. Link a key with
        ``PUT /v1/api-keys/{id}/machine-user`` first — reachable through
        :meth:`chatly.ChatlyClient.request` if you are automating setup.
        """
        payload: JsonDict = {"state": state}
        if reason is not None:
            payload["reason"] = reason
        return self._put_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/agent-handling", payload
        )

    def generated_replies(self, conversation_id: str) -> List[JsonDict]:
        """Replies an agent (human or machine) has proposed for a thread.

        Returns a **bare list**, not a page — this route is pagination-exempt
        and takes no cursor, because a thread has a handful of open proposals
        at most.
        """
        return as_list(
            self._get(f"/v1/{encode_path('conversations', conversation_id)}/generated-replies")
        )

    def generate_reply(
        self,
        conversation_id: str,
        body: str,
        *,
        based_on_message_id: Optional[str] = None,
        proposed_by_label: Optional[str] = None,
        **extra: Any,
    ) -> JsonDict:
        """Propose a reply for human approval instead of sending it.

        Args:
            body: the proposed text.
            based_on_message_id: the inbound message this answers. Worth
                sending: the platform counts inbound messages that arrived
                *after* it (``newerInboundCount`` on the proposal), which is
                how a reviewer sees that a proposal has gone stale.
            proposed_by_label: 1–160 characters naming the proposer, shown in
                the approval UI.

        Sending the approved reply and discarding a proposal are *not* in
        this SDK: both routes record which person decided, so they answer an
        API key with 403. Approval happens in the dashboard.
        """
        payload: JsonDict = {"body": body}
        if based_on_message_id is not None:
            payload["basedOnMessageId"] = based_on_message_id
        if proposed_by_label is not None:
            payload["proposedByLabel"] = proposed_by_label
        payload.update(extra)
        return self._post_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/generated-replies", payload
        )

    def scheduled_messages(self, conversation_id: str) -> List[JsonDict]:
        """Messages queued to send later in this thread. A bare list."""
        return as_list(
            self._get(f"/v1/{encode_path('conversations', conversation_id)}/scheduled-messages")
        )

    def schedule_message(
        self, conversation_id: str, body: str, send_at: Union[str, Any], **extra: Any
    ) -> JsonDict:
        """Queue a message to send at ``send_at``.

        Args:
            body: 1–10,000 characters.
            send_at: when to send. An ISO-8601 string, or a
                :class:`datetime.datetime` — a naive datetime is serialised
                without an offset, so pass a timezone-aware one unless you
                are certain the server's reading of it is what you meant.

        Returns the scheduled message, whose ``status`` moves through
        ``pending`` → ``sent`` / ``cancelled`` / ``failed``. Treat it as an
        open string, not an enum: a newer deploy can write a value this
        release has never heard of.
        """
        payload: JsonDict = {"body": body, "sendAt": send_at}
        payload.update(extra)
        return self._post_obj(
            f"/v1/{encode_path('conversations', conversation_id)}/scheduled-messages", payload
        )

    def cancel_scheduled(self, scheduled_id: str) -> JsonDict:
        """Cancel a queued message. Returns it with ``cancelledAt`` set.

        The id is the **scheduled message's** id, and the route carries no
        conversation at all:
        ``DELETE /v1/conversations/scheduled-messages/{scheduled_id}``. A
        conversation id here is a 404 at best.
        """
        return self._delete_obj(
            f"/v1/conversations/scheduled-messages/{encode_path(scheduled_id)}"
        )


__all__ = ["Conversations"]
