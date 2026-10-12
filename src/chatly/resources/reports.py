"""``client.reports`` — the four key-accessible reporting rollups."""

from __future__ import annotations

from typing import Any, List, Optional

from ._base import JsonDict, Resource, as_list


class Reports(Resource):
    """Workspace rollups. All read-only, all scoped by a day window.

    **Each route has a different default window** — 7 days for
    :meth:`overview` and :meth:`agents`, 14 for
    :meth:`conversations_by_day`, 30 for :meth:`sla` — so comparing two of
    them without passing ``days`` explicitly compares different periods.
    Pass ``days`` when the numbers are going to sit next to each other.
    """

    def overview(self, *, days: Optional[int] = None, **params: Any) -> JsonDict:
        """Headline counters.

        Args:
            days: 1–90, default 7. Out-of-range or unparseable values fall
                back to 7 silently rather than erroring, so check
                ``windowDays`` in the response if it matters.

        Returns ``{"windowDays", "openConversations", "messagesSent",
        "csat": {"average", "sampleSize"}}``. ``csat.average`` is ``0`` with
        no responses, not ``null`` — read ``sampleSize`` to tell "nobody
        answered" from "everybody scored zero".
        """
        return self._get_obj("/v1/reports/overview", {"days": days, **params})

    def agents(self, *, days: Optional[int] = None, **params: Any) -> List[JsonDict]:
        """Per-agent productivity. A bare list.

        Args:
            days: 1–90, default 7.

        Each row is ``{"userId", "name", "conversationsHandled",
        "avgFirstResponseSeconds", "avgResolutionSeconds", "csatAvg",
        "csatCount"}``. Note ``csatAvg``, not ``csatAverage``. ``name`` falls
        back to ``"Agent <first 8 of userId>"`` when the agent has no display
        name, so it is always a string.

        Not to be confused with ``/v1/reports/analytics/agents``, which has a
        different window default and an extra ``hoursOnline`` field, and
        which an API key cannot call.
        """
        return as_list(self._get("/v1/reports/agents", {"days": days, **params}))

    def conversations_by_day(
        self, *, days: Optional[int] = None, **params: Any
    ) -> List[JsonDict]:
        """A daily conversation count. A bare list of ``{"day", "count"}``.

        Args:
            days: 1–90, **default 14** — the odd one out among these four.

        ``day`` is ``YYYY-MM-DD``. **Days with no conversations are absent
        from the list**, not present with a zero, so do not zip this against
        a date range by index — a chart has to fill the gaps itself.
        """
        return as_list(
            self._get("/v1/reports/conversations-by-day", {"days": days, **params})
        )

    def sla(
        self,
        *,
        days: Optional[int] = None,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        group_by: Optional[str] = None,
        **params: Any,
    ) -> JsonDict:
        """SLA attainment, breaches and coverage.

        Args:
            days: 1–366, default 30. Silently clamped.
            from_: ISO lower bound. **Must be passed together with ``to``**
                or the route returns 400. Sent as ``from``.
            to: ISO upper bound, **exclusive**. A bare date is bumped forward
                one day, so ``to="2026-10-01"`` includes all of 30 September
                and nothing of 1 October. ``to <= from_`` is a 400, and an
                explicit range over 366 days is a 400 — note the asymmetry
                with ``days``, which is clamped instead.
            group_by: ``hour``, ``day`` (default), ``week`` or ``month``.
                **The wire name is snake_case ``group_by``**, and this is the
                only parameter in the SDK that is: the handler reads
                ``query.group_by`` only, so a camelCase ``groupBy`` is
                silently ignored and you get daily buckets back. ``hour``
                over a span longer than 14 days is a 400.

        Returns ``{"from", "to", "windowDays", "coverage", "clocks",
        "byTarget", "byPolicy", "byTeam", "byAgent", "breaches",
        "breachesTruncated"}``. ``breaches`` is capped at 200 rows —
        check ``breachesTruncated`` before treating it as the whole set.
        """
        return self._get_obj(
            "/v1/reports/sla",
            {"days": days, "from": from_, "to": to, "group_by": group_by, **params},
        )


__all__ = ["Reports"]
