"""``client.billing`` — plan prices and metered usage."""

from __future__ import annotations

from typing import Any, List, Optional

from ..errors import InvalidArgumentError
from ._base import JsonDict, Resource, as_list

#: The metered event types ``GET /v1/billing/usage`` will total.
USAGE_EVENT_TYPES = (
    "conversation.opened",
    "message.sent.agent",
    "message.sent.bot",
    "ai.tokens",
)


class Billing(Resource):
    """Read-only billing. Requires a key with ``workspace:billing:read``.

    Every route here is reachable on a **suspended** workspace, which is
    deliberate: the billing surface is how a workspace stops being suspended,
    so refusing it would be a lock with the key inside.
    """

    def plans(self) -> List[JsonDict]:
        """Purchasable plan prices, as a bare list. No parameters.

        Each row is ``{"plan", "cadence", "priceId", "unitAmount",
        "currency", "interval"}``. ``cadence`` is ``monthly`` or ``annual``;
        ``unitAmount`` is in minor units (cents) and may be ``null``;
        ``interval`` is whatever Stripe reports, kept separate from
        ``cadence`` deliberately.

        **An empty list is a success, not an error.** It is the self-hosted
        or no-Stripe-keys state. Only ``starter``, ``growth`` and
        ``business`` are ever listed — ``free`` needs no price and
        ``enterprise`` is quoted, so neither appears even though both are
        real plans. Prices whose Stripe id cannot be resolved are omitted
        silently, so a shorter list than you expect means a configuration
        problem, not a product decision.
        """
        return as_list(self._get("/v1/billing/plans"))

    def usage(
        self,
        event_type: str,
        *,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        **params: Any,
    ) -> JsonDict:
        """Total one metered event type over a window.

        Args:
            event_type: **required** — one of ``conversation.opened``,
                ``message.sent.agent``, ``message.sent.bot``, ``ai.tokens``.
                It is required by the handler rather than by a schema, so
                the generated OpenAPI spec shows it as optional; it is not.
                An unknown value is a 400 listing the accepted ones. This
                SDK checks it locally first, so the mistake costs no
                round-trip.
            from_: ISO timestamp, inclusive. Sent as ``from``.
            to: ISO timestamp, **exclusive**.

        Omitting both dates uses the current UTC calendar month. ``to <=
        from_`` is a 400, and so is a timestamp that will not parse.

        Returns ``{"workspaceId", "eventType", "from", "to", "total",
        "count"}``, where ``from``/``to`` are the window the server actually
        used — read them back rather than assuming your dates were applied.
        ``total`` sums the recorded quantity; ``count`` is the number of
        rows, and they differ whenever a row carries a quantity above one
        (``ai.tokens`` always does).
        """
        if event_type not in USAGE_EVENT_TYPES:
            raise InvalidArgumentError(
                f"unknown billing event_type {event_type!r}; expected one of "
                f"{', '.join(USAGE_EVENT_TYPES)}"
            )
        return self._get_obj(
            "/v1/billing/usage",
            {"eventType": event_type, "from": from_, "to": to, **params},
        )


    def summary(self) -> JsonDict:
        """Plan, subscription state and seat counts. No parameters.

        Returns ``{"plan", "status", "trialEnd", "currentPeriodEnd",
        "seatsUsed", "seatsBilled", "seatsLimit", "seatsRemaining",
        "seatsAtLimit", "stripeConnected", "hasSubscription",
        "upcomingInvoiceAmountCents", "upcomingInvoiceCurrency"}``.

        **``seatsLimit: -1`` means uncapped, not "no seats".** So does
        ``seatsRemaining: -1``. That is the value on every plan today, so a
        UI that renders "0 of -1 seats" is the normal case rather than an
        edge one. The field to act on is ``seatsAtLimit``: when it is
        ``True`` the next accepted invite is a 402.

        ``status`` is a plain string (``trialing``, ``active``, ``past_due``,
        ``canceled``, ``incomplete``) — do not map it onto a strict enum.
        ``stripeConnected: False`` is a deployment with no Stripe keys
        configured, where ``plan`` is whatever an operator set by hand.
        """
        return self._get_obj("/v1/billing")

    def invoices(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        **params: Any,
    ) -> JsonDict:
        """One page of invoices, newest first — **in a ``data`` envelope**.

        Args:
            cursor: from the previous response's ``nextCursor``. It is an
                **ISO timestamp**, not an opaque id, because the keyset is
                ``createdAt``. Pass back exactly what you were given: an
                unparseable cursor is **silently ignored and page one comes
                back again**, which is an infinite loop in any walker that
                synthesises one.
            limit: 1–100, default 25. Clamped rather than rejected, and a
                non-numeric value is dropped in favour of the default.

        **This is the one cursor-paginated route on the typed surface that
        does not return the ``{"items", "nextCursor"}`` envelope**, so it
        returns a plain ``dict`` rather than a :class:`~chatly.Page` and
        there is no ``iter_invoices``. The rows are under ``data``:

            cursor = None
            while True:
                page = client.billing.invoices(cursor=cursor)
                for invoice in page["data"]:
                    ...
                cursor = page["nextCursor"]
                if cursor is None:
                    break

        Reading this as "not paginated" silently truncates every customer
        with more than 25 invoices, which is the reason this docstring is
        the length it is.

        A row carries ``id``, ``stripeInvoiceId``, ``amountCents``,
        ``currency``, ``status`` (``paid``, ``open``, ``void``),
        ``invoicePdfUrl``, ``hostedInvoiceUrl``, ``periodStart``,
        ``periodEnd`` and ``paidAt`` — the URLs and dates all nullable.
        """
        return self._get_obj(
            "/v1/billing/invoices", {"cursor": cursor, "limit": limit, **params}
        )

    def usage_daily(
        self,
        event_type: str,
        *,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        **params: Any,
    ) -> JsonDict:
        """One metered event type, bucketed per UTC day.

        Args:
            event_type: **required** — one of
                :data:`USAGE_EVENT_TYPES`. The schema calls it optional and
                the handler answers 422 when it is absent, so it is
                required; this SDK checks it locally.
            from_: ISO instant, inclusive. Sent as ``from``. Defaults to the
                start of the current UTC calendar month.
            to: ISO instant, **exclusive**. Defaults to ``from_`` plus one
                month.

        Returns ``{"workspaceId", "eventType", "from", "to", "days"}``, where
        ``from``/``to`` are the window actually used — read them back.

        **``days`` is dense**: one entry per UTC day in the window, zeros
        included, each ``day`` a full ISO midnight instant. So you can zip it
        against a date range, unlike
        :meth:`chatly.resources.reports.Reports.conversations_by_day`, which
        omits empty days.

        **The 365-day ceiling is a silent truncation, not a refusal.** A
        two-year window returns the first 366 days with no error and no flag
        — nothing in the response says it was cut, so bound the window
        yourself. A malformed date, or ``to <= from_``, is a 422.
        """
        if event_type not in USAGE_EVENT_TYPES:
            raise InvalidArgumentError(
                f"unknown billing event_type {event_type!r}; expected one of "
                f"{', '.join(USAGE_EVENT_TYPES)}"
            )
        return self._get_obj(
            "/v1/billing/usage/daily",
            {"eventType": event_type, "from": from_, "to": to, **params},
        )

    def usage_monthly(self, *, month: Optional[str] = None, **params: Any) -> JsonDict:
        """Every metered event type for one calendar month.

        Args:
            month: exactly ``YYYY-MM``. Defaults to the current UTC month. A
                malformed value is a 422 saying so, and so is a month outside
                01–12 — this one rejects rather than clamping.

        Returns ``{"workspaceId", "monthStart", "items", "total"}``.

        **``items`` is always all four event types, zeros included**, and
        unlike :meth:`usage_daily` you cannot narrow to one. Each is
        ``{"eventType", "total", "count", "monthStart"}``; the top-level
        ``total`` is the sum of their ``total``s.

        It has an ``items`` key and is **not** a page — there is no cursor
        here, so do not reach for :class:`~chatly.Page`. The window is always
        a whole calendar month; use :meth:`usage` for an arbitrary range.
        """
        return self._get_obj(
            "/v1/billing/usage/monthly", {"month": month, **params}
        )


__all__ = ["USAGE_EVENT_TYPES", "Billing"]
