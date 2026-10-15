"""``client.bots`` — AI personas, external agents, and their delivery ledger."""

from __future__ import annotations

import datetime as _dt
from typing import Any, Iterator, Optional, Sequence, Union

from .._transport import encode_path
from ..errors import InvalidArgumentError
from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, csv

#: The statuses of one delivery attempt to an external agent.
#:
#: ``failed`` **will** be retried; ``dead`` will not. That is the whole
#: distinction, and it is the one worth acting on.
DELIVERY_STATUSES = ("pending", "delivered", "failed", "dead")


def _instant(value: Union[str, _dt.datetime]) -> str:
    """An ``activateAt`` value as the wire sees it.

    A string is the caller's own ISO-8601 and goes through untouched — the
    server's schema is the authority on what it accepts. A datetime must be
    aware: a naive one has no zone, and guessing (local? UTC?) would shift
    the switch by hours with no error anywhere. It is converted to UTC and
    written with ``Z`` rather than ``+00:00``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidArgumentError(
                "activate_at is a naive datetime; pass a timezone-aware one "
                "(e.g. datetime.now(timezone.utc)) or an ISO-8601 string with "
                "an offset — a naive value has no zone to convert from"
            )
        utc = value.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        return utc.isoformat() + "Z"
    raise InvalidArgumentError(
        f"activate_at must be a str or a timezone-aware datetime, got {type(value).__name__}"
    )


class Bots(Resource):
    """Two kinds of bot behind one namespace, and the difference matters.

    A **Chatly bot** is a persona this platform runs: a system prompt, a
    model, tools, a KB scope, guardrails. An **external agent** is your own
    service, which we POST signed deliveries to and whose replies we relay.
    ``type`` tells them apart, and several fields are ``None`` on one kind by
    design rather than by accident — ``externalAgent`` is ``None`` on a
    Chatly bot, and three of :meth:`analytics`' counters are ``None`` on one
    kind or the other because that kind cannot produce the number.

    Reads need ``triggers:read`` (:meth:`analytics` needs ``reports:read``
    instead); writes need ``ai:configure``.

    **No read path ever returns a signing secret or a token.** They are shown
    once, by :meth:`create` and :meth:`rotate_external_secret`, and cannot be
    recovered.
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
        """One page of bots, newest first.

        Args:
            cursor: from the previous page's ``next_cursor``. **A cursor the
                server cannot read silently restarts at page one** rather
                than erroring, so never synthesise one.
            limit: 1–100, default 25. **Rejected with a 400** out of range,
                not clamped.
            sort: ``id``, ``name``, ``createdAt``, ``updatedAt`` or
                ``status``, optionally ``-`` prefixed. Default
                ``createdAt`` descending.
            fields: a projection — and the reason **every field on a row is
                optional**. Code that reads a key it did not ask for will
                ``KeyError``.
            filter: clauses, repeated on the wire. Filterable: ``status``
                (``active``, ``paused``, ``draft``), ``model``,
                ``templateOrigin``, ``createdAt``, ``updatedAt``.

        The envelope carries ``hasMore`` beside ``items`` and ``nextCursor``;
        :attr:`chatly.Page.has_more` surfaces it.
        """
        return self._page(
            "/v1/bots",
            {
                "cursor": cursor,
                "limit": limit,
                "sort": sort,
                "fields": csv(fields),
                "filter": filter,
                **params,
            },
        )

    def iter_list(self, **params: Any) -> Iterator[JsonDict]:
        """Every bot, as a generator.

            for bot in client.bots.iter_list(filter="status:eq:active"):
                print(bot["name"], bot["type"])

        Avoid ``fields`` here unless you know which keys you need: the
        projection applies to every page, so a missing key is a ``KeyError``
        inside your loop rather than at the call.
        """
        params.pop("cursor", None)
        if "fields" in params:
            params["fields"] = csv(params["fields"])
        return self._walk("/v1/bots", params)

    def get(self, bot_id: str) -> JsonDict:
        """One bot by id, in full.

        ``externalAgent`` is ``None`` for a Chatly bot; for an external one
        it is ``{"webhookUrl", "timeoutSeconds", "fallbackMessage",
        "signingSecretSet", "canStartConversations"}``. Note
        ``signingSecretSet`` is a **boolean** — the secret itself is not on
        any read path.
        """
        return self._get_obj(f"/v1/{encode_path('bots', bot_id)}")

    def create(self, **fields: Any) -> JsonDict:
        """Create a bot. Answers 201. Takes **wire** field names.

        Two disjoint bodies, chosen by ``type``:

            client.bots.create(
                name="Support", systemPrompt="You answer billing questions..."
            )
            client.bots.create(
                type="external", name="Our agent",
                webhookUrl="https://" + your_host + "/chatly",
            )

        A Chatly bot (``type`` omitted or ``"chatly"``) requires ``name`` and
        ``systemPrompt`` (**20**–20,000 characters) and accepts ``slug``,
        ``description``, ``model``, ``status``, ``enabledTools``,
        ``kbScope``, ``maxToolCalls``, ``guardrails``, ``personaMeta`` and
        ``escalationRules``. An external agent requires ``name`` and
        ``webhookUrl`` (**https**, and refused by an SSRF guard for a
        private, loopback or reserved host) and accepts ``slug``,
        ``description``, ``status``, ``personaMeta``, ``timeoutSeconds``
        (1–60, default 15), ``fallbackMessage`` and
        ``canStartConversations`` (default ``False``).

        **Neither half is strict, so a field from the wrong one is silently
        dropped.** ``create(type="external", systemPrompt=...)`` is a 201
        with no prompt stored. That is the trap this method takes wire names
        for: there is no keyword list that could make the mistake visible, so
        the burden is on reading the two sets above.

        The two kinds also default differently: an external agent is created
        **active**, a Chatly bot is not.

        An external agent's response is the only place ``signingSecret``,
        ``token`` (a ``cb_`` credential) and ``credentialId`` appear.
        **Both credentials are shown exactly once and cannot be recovered.**
        """
        return self._post_obj("/v1/bots", dict(fields))

    def update(self, bot_id: str, **fields: Any) -> JsonDict:
        """Update a Chatly bot's configuration. Takes **wire** field names.

        Accepts ``name``, ``description``, ``systemPrompt``, ``model``,
        ``status``, ``enabledTools``, ``kbScope``, ``maxToolCalls``,
        ``guardrails``, ``personaMeta``, ``escalationRules``. **Not ``slug``
        and not ``type``** — neither is patchable, and neither is an error
        either; they are simply not in the schema.

        ``description=None`` clears it. An **empty** call is a 400 ("No
        fields to update") rather than a no-op, so do not call this with a
        dict you have not checked.

        External-agent delivery settings live on :meth:`update_external`.
        """
        return self._patch_obj(f"/v1/{encode_path('bots', bot_id)}", dict(fields))

    def update_external(self, bot_id: str, **fields: Any) -> JsonDict:
        """Update an external agent's delivery settings. Wire field names.

        Accepts ``webhookUrl`` (https, SSRF-guarded), ``timeoutSeconds``
        (1–60), ``fallbackMessage`` and ``canStartConversations``. At least
        one is required; an empty body is a 400.

        ``canStartConversations`` is deliberately **not** defaulted by the
        schema here, unlike on :meth:`create`. If it were, a caller editing
        only the timeout would revoke the agent's permission to open
        conversations — so omitting it means "leave it alone", and that is
        load-bearing rather than incidental.

        Calling this on a Chatly bot is a 400. The signing secret survives
        the write: the server reads, merges and writes the whole external
        config bag rather than replacing it.
        """
        return self._patch_obj(
            f"/v1/{encode_path('bots', bot_id)}/external", dict(fields)
        )

    def rotate_external_secret(
        self,
        bot_id: str,
        *,
        activate_at: Union[None, str, _dt.datetime] = None,
    ) -> JsonDict:
        """Mint a new signing secret for an external agent. Answers 201.

        Returns ``{"signingSecret": "...", "activatesAt": ...}``, and that is
        the **only** time the secret is ever readable.

        Args:
            activate_at: when the new secret starts signing deliveries. Sent
                on the wire as ``activateAt``. An ISO-8601 string (with ``Z``
                or an offset) passes through verbatim and the server validates
                it; a :class:`datetime.datetime` must be **timezone-aware** and
                is sent as its UTC instant with a trailing ``Z``. A naive
                datetime raises :class:`~chatly.InvalidArgumentError` (a
                ``ValueError``) before anything is sent, because there is no
                way to know which zone it meant. More than 168 hours ahead of
                the *server's* clock is a 400; an instant already in the past
                is a hard cut rather than an error.

        **Without** ``activate_at`` there is no overlap window — exactly what
        this route has always done. The old secret stops signing the instant
        this returns, so deploy the new value at your endpoint as part of the
        same change, not afterwards; ``activatesAt`` is ``None``. The request
        body in that case is ``{}``, byte-for-byte what it was before this
        parameter existed.

        **With** ``activate_at`` the old secret goes on signing every delivery
        until that instant and the new one signs from then on, so
        ``activatesAt`` comes back as the switch instant. Each delivery
        carries **one** signature, never two, so the window is for *your
        verifier* to hold both secrets — accept either until the switch, then
        drop the old one. A deferred rotation on an agent that has no usable
        secret today is still a hard cut and answers ``activatesAt: None``.

        Read ``activatesAt``, not your own argument: ``None`` means the new
        secret is already signing, whatever you asked for.

        (Contrast
        :class:`chatly.resources.customer_card_endpoints.CustomerCardEndpoints`,
        whose rotation is two-phase and receiver-driven rather than timed.)

        A replayed ``Idempotency-Key`` returns the cached body rather than
        minting a second secret, which is what makes a retry safe here.
        """
        path = f"/v1/{encode_path('bots', bot_id)}/external/rotate-secret"
        if activate_at is None:
            # No body of our own: the transport sends `{}`, as it always has.
            return self._post_obj(path)
        return self._post_obj(path, {"activateAt": _instant(activate_at)})

    def analytics(self, bot_id: str, *, days: Optional[int] = None, **params: Any) -> JsonDict:
        """One bot's volume, latency, reliability and outcomes.

        Args:
            days: 1–365, default 30. **Rejected** out of range, not clamped.
                And ``from``, ``to``, ``weeks`` and ``date`` are each a
                deliberate 400 naming ``days`` — this route takes one window
                parameter and says so rather than ignoring the others.

        Needs ``reports:read``, not ``triggers:read`` like the rest of this
        namespace.

        Two things to read carefully. **Every rate is ``None``, never 0, when
        its sample size is 0** — "no basis for a number" rather than "zero
        per cent". And some counters are ``None`` for a whole *kind* of bot:
        ``volume.retrying``, ``reliability.fallbackCount`` and
        ``reliability.retriedCount`` are ``None`` for a Chatly bot (nothing
        retries a local persona), while ``volume.cancelled`` is ``None`` for
        an external one.

        ``latency.basis`` says what was timed — ``run_wall_clock`` (a whole
        agent run, seconds) or ``last_attempt`` (one HTTP round trip to your
        endpoint). **The two are not comparable**, so do not chart a Chatly
        bot's latency beside an external agent's.

        ``outcomes.conversations`` counts conversations the bot *touched* and
        does not partition them, so per-bot figures do not sum to a workspace
        total.
        """
        return self._get_obj(
            f"/v1/{encode_path('bots', bot_id)}/analytics", {"days": days, **params}
        )

    def deliveries(
        self,
        bot_id: str,
        *,
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of delivery attempts to an external agent, newest first.

        Args:
            status: one of :data:`DELIVERY_STATUSES`. **A plain enum
                parameter, not a ``filter`` clause**, and a typo is a 400
                naming the four — unlike most list filters on this API, which
                ignore what they do not understand.
            cursor: from the previous page's ``next_cursor``.
            limit: 1–100, default 25.
            sort: only ``createdAt`` is sortable, because delivery ids are
                UUID v4 and id order is not time order.

        **The rows carry no ``payload``** — fetch one with :meth:`delivery`
        for that. ``attempt`` is attempts *made*, so 0 means untried;
        ``httpStatus`` and ``durationMs`` are ``None`` when the request never
        completed; ``error`` is pre-truncated to 300 characters.

        Calling this for a **Chatly** bot is a 404, not an empty page: only
        an external agent has a delivery ledger.
        """
        return self._page(
            f"/v1/{encode_path('bots', bot_id)}/deliveries",
            {
                "status": status,
                "cursor": cursor,
                "limit": limit,
                "sort": sort,
                **params,
            },
        )

    def iter_deliveries(self, bot_id: str, **params: Any) -> Iterator[JsonDict]:
        """Every matching delivery for one agent, as a generator.

            for row in client.bots.iter_deliveries(bot_id, status="failed"):
                client.bots.redeliver(bot_id, row["id"])

        Note ``failed`` rows are still on the retry ladder; ``dead`` ones are
        the ones nothing else will try again.
        """
        params.pop("cursor", None)
        return self._walk(f"/v1/{encode_path('bots', bot_id)}/deliveries", params)

    def delivery(self, bot_id: str, delivery_id: str) -> JsonDict:
        """One delivery, with the ``payload`` that was sent.

        ``payload`` is typed as "anything" on purpose: an old row carries the
        shape that was current the day it was sent, not today's.

        The delivery is scoped to the bot in the path, so one agent's id plus
        another's delivery is a 404 rather than a 200.

        Note ``delivery_id`` is **not** validated as a UUID by the server, so
        a malformed one reaches the query and surfaces as a 500 rather than a
        400. Pass an id you got from :meth:`deliveries`.
        """
        return self._get_obj(
            f"/v1/{encode_path('bots', bot_id, 'deliveries', delivery_id)}"
        )

    def redeliver(self, bot_id: str, delivery_id: str) -> JsonDict:
        """Queue one delivery to be sent again. Answers 201.

        Returns ``{"queued": true, "deliveryId", "url"}``, where ``url`` is
        the agent's **current** endpoint rather than the one this attempt
        originally went to.

        **It re-sends the recorded bytes**, which has a consequence worth
        knowing: the event id is the same, so your own de-duplication will
        compare it equal to the original and discard it. Only replay
        something you never processed.

        It resets the row to ``pending`` with ``attempt: 0`` and restarts the
        whole retry ladder. ``fallbackAppliedAt`` is **not** cleared — the
        fallback message your visitor already saw stays on record.

        A 400 if the agent has no webhook URL; a 404 if the delivery or the
        external bot is absent.
        """
        return self._post_obj(
            f"/v1/{encode_path('bots', bot_id, 'deliveries', delivery_id)}/redeliver"
        )

    def test_delivery(self, bot_id: str) -> JsonDict:
        """Send a signed test payload to an external agent. Answers 201.

        **Writes nothing** — no ledger row, no conversation, no retry. The
        payload carries ``"test": true`` and all-zero UUIDs, and the agent
        should answer 2xx and **not** reply.

        Returns ``{"ok", "httpStatus", "durationMs", "error",
        "responseBody", "url", "signature", "payload"}``. ``signature`` and
        ``payload`` are the exact bytes and digest that were sent, so an
        integrator can check their verifier offline against a real delivery
        rather than a hand-built one. ``responseBody`` is up to 2,000
        characters of whatever your endpoint answered — on success as well
        as failure, which is where a 200-with-an-error-body shows up.

        A 400 unless the agent has **both** a webhook URL and a signing
        secret. The outbound guard is re-checked at call time, not just at
        configuration time, because a host that resolved publicly last week
        can resolve to a link-local address today.
        """
        return self._post_obj(f"/v1/{encode_path('bots', bot_id)}/test-delivery")


__all__ = ["DELIVERY_STATUSES", "Bots"]
