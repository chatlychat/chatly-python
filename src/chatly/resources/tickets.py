"""``client.tickets`` — the ticketing side of a conversation."""

from __future__ import annotations

from typing import Any, Iterator, List, Mapping, Optional, Sequence, Union

from .._transport import encode_path
from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, as_list, csv


class Tickets(Resource):
    """Read tickets and queues, merge, split, and bulk-update.

    **There is no way to create a ticket or add a comment with an API key.**
    ``POST /v1/tickets``, ``POST /v1/tickets/{id}/comments``,
    ``PATCH /v1/tickets/{id}`` and ``POST /v1/tickets/{id}/transition`` all
    require a signed-in person, so a key gets 403 and no method for them
    exists here. Key-authenticated integrations can read, merge, split and
    bulk-update — tickets are normally created by the platform from an
    inbound email or conversation, not by an integration.

    A ticket carries ``id``, ``workspaceId``, ``conversationId``, ``number``
    (the customer-facing integer), ``title``, ``description``, ``status``,
    ``priority``, ``type``, ``assigneeUserId``, ``teamId``,
    ``parentTicketId``, ``mergedIntoId``, ``splitFromTicketId``, ``queueId``,
    ``slaPolicyId``, the SLA clock fields (``dueAt``, ``firstResponseAt``,
    ``firstResponseDueAt``, ``resolvedAt``, ``resolutionDueAt``,
    ``slaWarnedAt``, ``slaBreachedAt``), ``closedAt``, ``tags`` and
    ``customFields``. ``status``, ``priority`` and ``type`` come back as
    plain strings — do not map them onto a strict ``Enum``, because a newer
    deploy can write a value this release has never heard of.
    """

    def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        fields: CsvValue = None,
        filter: Union[None, str, Sequence[str]] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of tickets.

        Args:
            cursor: from the previous page's ``next_cursor``.
            limit: 1–100, default 25. Unlike the contacts and conversations
                lists, this route **rejects** an out-of-range limit with a
                400 instead of clamping it.
            sort: one of ``id``, ``createdAt``, ``updatedAt``, ``dueAt``,
                optionally prefixed ``-`` for descending. Default is
                ``createdAt`` descending.
            fields: a projection. Restricted to the ticket field names above;
                anything else is a 400. **Using it returns a subset of keys**,
                so code that reads a field it did not ask for will
                ``KeyError``.
            filter: one clause or a list of them, repeated on the wire.
                Grammar: ``field:value``, ``field:op:value``,
                ``field:null``, ``field:notnull``. Operators: ``eq``, ``ne``,
                ``in``, ``gt``, ``gte``, ``lt``, ``lte``, ``null``,
                ``notnull``. Filterable fields: ``status``, ``priority``,
                ``type``, ``assigneeUserId``, ``teamId``, ``conversationId``,
                ``queueId``, ``splitFromTicketId``. Maximum 32 clauses. An
                unknown field or operator is a 400 — this is the one list
                parameter here that fails loudly rather than being ignored.

        ``merged`` tickets are excluded unless you filter on ``status``
        yourself, so counts from this list will not match a raw table count.

        Sent as repeated ``filter`` keys, not ``filter[]``: the bracketed
        form was silently dropped for a year before a fold was added for it,
        and the plain key has always worked.
        """
        return self._page(
            "/v1/tickets",
            {
                "cursor": cursor,
                "limit": limit,
                "sort": sort,
                "fields": csv(fields),
                "filter": filter,
                **params,
            },
        )

    def iter_list(
        self,
        *,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        fields: CsvValue = None,
        filter: Union[None, str, Sequence[str]] = None,
        **params: Any,
    ) -> Iterator[JsonDict]:
        """Every matching ticket, as a generator.

            for ticket in client.tickets.iter_list(filter="status:eq:open"):
                print(ticket["number"], ticket["title"])
        """
        return self._walk(
            "/v1/tickets",
            {
                "limit": limit,
                "sort": sort,
                "fields": csv(fields),
                "filter": filter,
                **params,
            },
        )

    def comments(self, ticket_id: str) -> List[JsonDict]:
        """A ticket's comments, oldest first. A bare list, capped at 500.

        Each is ``{"id", "ticketId", "body", "isInternal", "authorUserId",
        "authorEmail", "createdAt", "editedAt"}``. ``isInternal`` comments are
        agent-only notes and must not be shown to a contact.

        Adding a comment needs a signed-in person, so there is no write half
        of this in a key-authenticated SDK.
        """
        return as_list(self._get(f"/v1/{encode_path('tickets', ticket_id)}/comments"))

    def for_conversation(self, conversation_id: str) -> List[JsonDict]:
        """Tickets attached to a conversation. A bare list.

        **A smaller shape than a full ticket**: ``{"id", "number", "title",
        "status", "priority", "type", "dueAt", "assigneeUserId", "isOrigin",
        "conversationCount"}``. ``isOrigin`` and ``conversationCount`` appear
        only here; the other 19 ticket fields do not. Call :meth:`list` with
        a ``conversationId`` filter if you need whole tickets.
        """
        return as_list(
            self._get(f"/v1/tickets/for-conversation/{encode_path(conversation_id)}")
        )

    def queues(self) -> List[JsonDict]:
        """The workspace's ticket queues. A bare list.

        ``{"id", "workspaceId", "createdAt", "updatedAt", "name",
        "description", "color", "defaultAssigneeUserId", "slaPolicyId"}``.
        """
        return as_list(self._get("/v1/tickets/queues"))

    def merge(self, ticket_id: str, loser_id: str) -> JsonDict:
        """Merge ``loser_id`` INTO ``ticket_id``.

        The path is the **winner**; the body names the ticket absorbed. The
        loser's conversations move across and its status becomes ``merged``.

        Returns ``{"winnerId", "loserId", "movedConversations"}`` — not a
        ticket object. Read the winner back with :meth:`list` if you need it.

        The body field is ``loserId`` here and ``mergedId`` on
        :meth:`chatly.resources.contacts.Contacts.merge`. Same operation,
        two names, and nothing will tell you if you cross them — a contact
        merge with a ``loserId`` key silently drops it and merges nothing,
        because unknown body fields are stripped rather than rejected.
        """
        return self._post_obj(f"/v1/{encode_path('tickets', ticket_id)}/merge", {"loserId": loser_id})

    def split(
        self,
        ticket_id: str,
        title: str,
        *,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        type: Optional[str] = None,
        assignee_user_id: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        conversation_ids: Optional[Sequence[str]] = None,
        **extra: Any,
    ) -> JsonDict:
        """Split a new child ticket off ``ticket_id``.

        Args:
            title: required, 1–280 characters after trimming.
            description: up to 10,000 characters.
            priority: omitted inherits the origin's.
            type: omitted inherits the origin's.
            assignee_user_id: omitted inherits the origin's assignee.
                ``None`` here means "omitted", because that is what an
                unpassed keyword argument looks like in Python. To create
                the child deliberately *unassigned*, send the explicit null
                by its wire name: ``split(..., assigneeUserId=None)`` —
                extra keyword arguments are passed through unfiltered.
            tags: up to 20 tags of up to 40 characters. ``[]`` clears them
                rather than inheriting.
            conversation_ids: up to 100 conversations to move to the child.

        Returns ``{"originId", "originNumber", "childId", "childNumber",
        "movedConversations", "sharedConversations"}``.

        **A replay creates a second child** with its own allocated number,
        and there is no unsplit. The ``Idempotency-Key`` this SDK sends is
        what makes a retried call safe; pin one with
        :meth:`chatly.ChatlyClient.with_idempotency_key` if you retry across
        process restarts.
        """
        body: JsonDict = {"title": title}
        for key, value in (
            ("description", description),
            ("priority", priority),
            ("type", type),
            ("assigneeUserId", assignee_user_id),
            ("tags", list(tags) if tags is not None else None),
            ("conversationIds", list(conversation_ids) if conversation_ids is not None else None),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return self._post_obj(f"/v1/{encode_path('tickets', ticket_id)}/split", body)

    def bulk(
        self,
        ids: Sequence[str],
        action: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> JsonDict:
        """Apply one action to 1–200 tickets.

        Args:
            ids: ticket ids, 1–200.
            action: exactly one of ``status``, ``assign``, ``priority``,
                ``queue``. (Shorter than the conversations bulk vocabulary —
                there is no tag, snooze or macro action here.)
            payload: the value for the action.

                * ``status`` → ``{"status": "open"}``. ``merged`` is
                  rejected; merge with :meth:`merge` instead.
                * ``assign`` → ``{"assigneeUserId": "..."}``, or ``None`` for
                  that key to unassign.
                * ``priority`` → ``{"priority": "high"}``.
                * ``queue`` → ``{"queueId": "..."}``, or ``None`` to unqueue.

        Returns ``{"updated": int, "skipped": [{"id", "reason"}]}``. A ticket
        the caller cannot touch is *skipped*, not an error, so check
        ``skipped`` rather than trusting a 200.

        Which payload key an action needs is checked in the service, not by
        the schema, so a mismatched pair is a runtime 4xx with a message
        rather than a field-level validation error.

        This is the one write in this namespace that does not require an
        ``Idempotency-Key``. The SDK sends one anyway — it is harmless, and
        it keeps every write on one code path.
        """
        body: JsonDict = {"ids": list(ids), "action": action}
        if payload is not None:
            body["payload"] = dict(payload)
        return self._post_obj("/v1/tickets/bulk", body)


    def conversations(self, ticket_id: str) -> List[JsonDict]:
        """The conversations a ticket covers. A bare list.

        Each row is ``{"conversationId", "isOrigin", "subject", "status",
        "channelType"}``-shaped, **origin first** — that is the only ordering
        key, so rows within each group arrive in no defined order.

        ``subject``, ``status`` and ``channelType`` are **nullable**: the
        join is outer, so a link whose conversation was hard-deleted still
        returns a row with the detail missing. That is deliberate — the link
        is the fact, the conversation is the lookup.

        **An unknown or cross-tenant ticket id returns ``[]``, not 404.**
        And the rows are narrowed by the caller's inbox scope, so a
        restricted credential legitimately sees fewer conversations than the
        ticket covers. Neither case is distinguishable from "no
        conversations", so do not use an empty list as an existence check.
        """
        return as_list(
            self._get(f"/v1/{encode_path('tickets', ticket_id)}/conversations")
        )

    def lineage(self, ticket_id: str) -> JsonDict:
        """How a ticket relates to the ones it was split from or follows.

        Returns ``{"splitFromTicketId", "parentTicketId", "splitFrom",
        "splitInto", "splitIntoTruncated", "followUpOf", "followUps",
        "followUpsTruncated"}``. A resolved reference is
        ``{"id", "number", "title", "status"}``.

        **The raw ids come back beside the resolved references on purpose.**
        Neither column has a foreign key, so a non-null id with a ``None``
        reference is a dangling pointer — a ticket that was hard-deleted —
        and you can only see that by comparing the two.

        ``splitInto`` and ``followUps`` are each capped at 25 with a
        ``*Truncated`` flag beside them; there is no cursor to the rest.

        Unlike :meth:`conversations`, an unknown ticket is a **404** here,
        and so is one whose conversations you cannot see — the response
        carries other tickets' titles, so visibility is checked before
        anything is returned.
        """
        return self._get_obj(f"/v1/{encode_path('tickets', ticket_id)}/lineage")

    def open_count(self, conversation_id: str) -> JsonDict:
        """How many open tickets a **conversation** has.

        Returns ``{"openTickets": n}``.

        Note the argument: this route is keyed by a conversation, not a
        ticket, which is why it sits under ``/v1/tickets/open-count/...``
        rather than taking a ticket id like its neighbours.

        "Open" means **not ``resolved`` and not ``closed``** — so
        ``pending``, ``snoozed`` and anything a newer deploy introduces all
        count. It counts through the link table, so a tracker ticket spanning
        several conversations counts once on each of them.

        An unknown conversation answers ``{"openTickets": 0}``. A
        conversation outside your inbox scope is a **404** rather than a 403,
        deliberately, so this cannot be used to enumerate what exists.
        """
        return self._get_obj(
            f"/v1/tickets/open-count/{encode_path(conversation_id)}"
        )

    def status_history(self, ticket_id: str) -> JsonDict:
        """A ticket's status transitions. An **object**, not a list.

        Returns ``{"ticketId", "status", "currentStatusForSeconds", "items",
        "truncated"}`` — the transitions are under ``items``, **oldest
        first**.

        ``status`` is read from the ticket itself rather than from the last
        history row, so it is right even when history is incomplete.
        ``currentStatusForSeconds`` is time since the most recent *recorded*
        transition, and ``None`` when there is none.

        ``items`` is capped at 500 and ``truncated`` is the only thing that
        distinguishes a capped timeline from a short one. When it is capped
        you keep the **recent** end, not the beginning.

        Per transition: ``previousStatus`` is ``None`` on the ticket's first
        row and on the first row *returned*, as is
        ``timeInPreviousStatusSeconds``. ``changeSource`` is a closed set —
        ``manual``, ``workflow``, ``api``, ``sla_breach``,
        ``customer_reply`` — and ``changedByUserId``/``changedByEmail`` are
        ``None`` for everything automated.

        An unknown ticket is a 404, so that a row-level-security miss cannot
        read as "no history".
        """
        return self._get_obj(
            f"/v1/{encode_path('tickets', ticket_id)}/status-history"
        )

    def time(self, ticket_id: str) -> JsonDict:
        """Logged time on a ticket. An **object**, not a list.

        Returns ``{"items", "totalMinutes", "billableMinutes"}``, newest
        first. An entry is ``{"id", "minutes", "note", "startedAt",
        "billable", "userId", "createdAt", ...}``.

        **Time is not tracked automatically.** There is exactly one writer in
        the product — ``POST /v1/tickets/{id}/time`` — so this list is empty
        unless somebody posted entries. And **that write is not available to
        an API key**: a key can read this and can never populate it, which
        makes an empty result the expected answer for a key-only
        integration rather than a sign something is wrong.

        ``billableMinutes`` is the figure that reaches an invoice;
        ``totalMinutes`` includes non-billable entries.

        **An unknown or cross-tenant ticket answers zeros, not 404** — unlike
        :meth:`lineage` and :meth:`status_history`, this one does not check
        the ticket exists.
        """
        return self._get_obj(f"/v1/{encode_path('tickets', ticket_id)}/time")


__all__ = ["Tickets"]
