"""``client.reports`` — the thirteen key-accessible reporting rollups."""

from __future__ import annotations

from typing import Any, List, Optional

from .._transport import encode_path
from ..errors import InvalidArgumentError
from ._base import JsonDict, Resource, as_list, flag

#: The dimensions :meth:`Reports.attribution` can group by.
#:
#: The server's own ``PAGE_CONTEXT_KEYS``. Unlike ``days`` on the same route,
#: an unknown dimension is **refused** with a 400 rather than defaulted, so
#: this SDK checks it locally and spends no round-trip on a typo.
ATTRIBUTION_DIMENSIONS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "referrer_url",
    "page_url_at_open",
    "device_type",
    "browser",
    "os",
)


class Reports(Resource):
    """Workspace rollups. All read-only, all scoped by a day window.

    **Every route here has its own default window**, and they disagree: 7
    days for :meth:`overview`, :meth:`agents` and :meth:`sources`, 14 for
    :meth:`conversations_by_day`, 8 *weeks* for :meth:`cohorts`, and 30 for
    :meth:`sla`, :meth:`attribution`, :meth:`response_times`, :meth:`voice`,
    :meth:`teams` and :meth:`labels`. Two of them read the same numbers over
    different periods if you leave ``days`` off, so pass it explicitly
    whenever two of these results are going to sit side by side.

    **And they disagree about bad input, on one axis.** ``days`` and
    ``weeks`` are *clamped* everywhere — the server computes
    ``min(ceiling, max(1, parse(value) or default))``, so ``days=0`` and
    ``days="abc"`` both silently become the default and nothing in the
    response says you asked for something else, except on :meth:`cohorts`
    and the range routes, which echo the window they used. An explicit
    ``from_``/``to`` range is *rejected* instead: see :meth:`teams`.
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


    # ---- extended rollups ----------------------------------------------
    #
    # Four of these take a day count only, like the four above. Two
    # (:meth:`teams`, :meth:`labels`) take the richer range vocabulary the
    # API's shared `reports-range.ts` parses, which rejects rather than
    # clamps. Keeping them in one namespace but documenting the difference
    # per method is deliberate: the two groups do not accept the same query.

    def response_times(self, *, days: Optional[int] = None, **params: Any) -> JsonDict:
        """First-response and resolution percentiles, plus a daily series.

        Args:
            days: 1–90, default 30. Clamped, never rejected.

        Returns ``{"windowDays", "conversationsCreated",
        "conversationsClosed", "firstResponse", "resolution", "byDay"}``.
        The two percentile blocks are **seconds**, and every percentile in
        one is ``null`` when its ``sampleSize`` is 0 — not 0, which would
        read as "instant".

        ``byDay`` is the same ``{"day", "count"}`` shape
        :meth:`conversations_by_day` returns *bare*. The two are not
        interchangeable: this one is nested under a key and spans 30 days by
        default rather than 14.
        """
        return self._get_obj("/v1/reports/response-times", {"days": days, **params})

    def sources(self, *, days: Optional[int] = None, **params: Any) -> List[JsonDict]:
        """Where conversations came from, per channel. A bare list.

        Args:
            days: 1–90, **default 7**.

        ``channelId`` is nullable — rows can be grouped by channel *type*
        with no single channel behind them — but ``channelName`` never is: a
        row with no channel falls back to a human label for the type, so it
        is always safe to print.
        """
        return as_list(self._get("/v1/reports/sources", {"days": days, **params}))

    def attribution(
        self,
        *,
        days: Optional[int] = None,
        dimension: Optional[str] = None,
        **params: Any,
    ) -> List[JsonDict]:
        """Conversations and revenue grouped by one page-context dimension.

        A bare list.

        Args:
            days: 1–90, default 30. Clamped.
            dimension: one of :data:`ATTRIBUTION_DIMENSIONS`, default
                ``utm_source``. **Rejected with a 400 if unknown**, unlike
                ``days`` — so this SDK checks it locally.

        Two things about the rows. They are capped at 50: the 50th is a
        synthetic ``(other)`` bucket summing everything past the 49th, so the
        tail is counted but not itemised and there is no cursor to it. And
        the row whose ``value`` is ``None`` is the **untagged** bucket — a
        real row, not a null to filter out. Dropping it inflates every other
        row's ``percentage``.
        """
        if dimension is not None and dimension not in ATTRIBUTION_DIMENSIONS:
            raise InvalidArgumentError(
                f"unknown attribution dimension {dimension!r}; expected one of "
                f"{', '.join(ATTRIBUTION_DIMENSIONS)}"
            )
        return as_list(
            self._get(
                "/v1/reports/attribution",
                {"days": days, "dimension": dimension, **params},
            )
        )

    def cohorts(self, *, weeks: Optional[int] = None, **params: Any) -> JsonDict:
        """Weekly contact-retention cohorts.

        Args:
            weeks: 2–26, default 8. **Weeks, not days** — the only route in
                this namespace with a different unit. Clamped.

        Returns ``{"weeks", "cells"}``. Read ``weeks`` back: it is the
        *clamped* number the server used, which is how you find out that
        ``weeks=52`` became 26. The window is ``now - weeks × 7 days``, with
        no timezone option, so cohort boundaries are UTC.
        """
        return self._get_obj("/v1/reports/cohorts", {"weeks": weeks, **params})

    def voice(self, *, days: Optional[int] = None, **params: Any) -> JsonDict:
        """Call volume, answer and abandon rates, and recording storage.

        Args:
            days: 1–365, default 30. Clamped.

        ``answerRate`` and ``abandonRate`` are **fractions in 0–1, not
        percentages**, and both are nullable when there were no calls to
        divide by.

        ``recordingStorage.exact`` is the field to read before quoting a
        number: when it is ``False``, ``totalBytesUpperBound`` is part
        measured and part extrapolated from a bitrate over
        ``unmeasuredCalls``, so it is a ceiling rather than a size.
        """
        return self._get_obj("/v1/reports/voice", {"days": days, **params})

    def teams(
        self,
        *,
        days: Optional[int] = None,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        group_by: Optional[str] = None,
        business_hours: Optional[bool] = None,
        **params: Any,
    ) -> JsonDict:
        """Per-team volume and duration. Returns an object, not a list.

        Args:
            days: default 30, clamped.
            from_: ISO date or instant. **Must be passed with ``to``** or the
                route answers 400, and when both are present they *win over*
                ``days``. Sent as ``from``.
            to: **exclusive**, and a bare calendar date is pushed forward one
                day — so ``to="2026-07-31"`` includes all of 31 July. Bare
                dates parse as **UTC** midnight, not server-local. A span
                over 366 days is a 400 naming the span: the explicit range
                rejects where ``days`` clamps.
            group_by: ``hour``, ``day`` (default), ``week`` or ``month``,
                snake_case on the wire like :meth:`sla`. ``hour`` over more
                than 14 days is a 400 — **including here**, where the
                response carries no granularity at all, so on this route
                ``group_by`` can only ever fail or do nothing.
            business_hours: measure durations inside the workspace's
                business hours. The wire value is the literal ``"true"``;
                anything else reads as off, so ``False`` is *omitted* rather
                than sent.

        Returns ``{"from", "to", "windowDays", "businessHours", "rows"}``.
        ``rows`` includes a ``teamId: None`` row — the unassigned bucket.

        **Check ``businessHours.applied`` before captioning anything.** When
        it is ``False`` the durations are plain calendar time; they are not
        zeroed and not relabelled, and ``businessHours.reason`` says why
        (``disabled``, ``not_configured``, ``always_closed``,
        ``invalid_timezone``). ``businessHours.sampleTruncated`` means the
        20,000-conversation sample ran out.
        """
        return self._get_obj(
            "/v1/reports/teams",
            {
                "days": days,
                "from": from_,
                "to": to,
                "group_by": group_by,
                "business_hours": flag(business_hours),
                **params,
            },
        )

    def labels(
        self,
        *,
        days: Optional[int] = None,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        group_by: Optional[str] = None,
        business_hours: Optional[bool] = None,
        **params: Any,
    ) -> JsonDict:
        """Label usage over a window, with a trend series.

        Takes the same range vocabulary as :meth:`teams`, with the same
        rules: ``from_``/``to`` together or 400, ``to`` exclusive,
        ``group_by`` snake_case, ``hour`` capped at 14 days, ``False`` for
        ``business_hours`` omitted rather than sent.

        Returns ``{"from", "to", "windowDays", "granularity",
        "businessHours", "labelledConversations", "unlabelledConversations",
        "otherLabels", "rows", "trend"}``.

        Two caps worth knowing, because neither has a cursor behind it:
        ``rows`` is the 50 busiest labels and everything else is counted in
        ``otherLabels``, and ``trend`` covers only the top 8. There is no way
        to page to the tail — narrow the window instead.

        ``trend[]["counts"]`` is keyed by label **name**, which is customer
        data: it can contain anything, including a key that collides with a
        field name in your own code.

        Not to be confused with
        :meth:`chatly.resources.workspace.Workspace.labels`, which lists the
        label definitions rather than reporting on their use.
        """
        return self._get_obj(
            "/v1/reports/labels",
            {
                "days": days,
                "from": from_,
                "to": to,
                "group_by": group_by,
                "business_hours": flag(business_hours),
                **params,
            },
        )

    def themes(self, *, date: Optional[str] = None, **params: Any) -> JsonDict:
        """The latest batch of clustered conversation themes.

        Args:
            date: a ``YYYY-MM-DD`` batch date. Omit it for the most recent
                batch — the route resolves the newest ``batchDate`` first and
                then reads only that batch, so two batches are never mixed.

                **Pass a well-formed date or nothing at all.** The value is
                handed to a Postgres ``date`` column unvalidated, so a
                malformed one — including an *empty string*, which is not the
                same as omitting the argument — is a 500 rather than a 400.

        Returns ``{"batchDate", "themes"}``. ``batchDate`` is ``None`` with
        ``themes: []`` when no batch has ever been generated, which is the
        normal state of a new workspace rather than an error.

        Theme rows deliberately omit their conversation ids; fetch those per
        theme with :meth:`theme_conversations`. Batches are produced by a
        daily worker job — there is no route to generate or edit one.
        """
        return self._get_obj("/v1/reports/themes", {"date": date, **params})

    def theme_conversations(self, theme_id: str) -> JsonDict:
        """The conversation ids clustered into one theme.

        Returns ``{"conversationIds": [...]}`` — **an object wrapping a
        list**, not a bare array and not a page, so read the key. Up to
        5,000 ids per theme, with no cursor.

        **An unknown or purged theme id answers 200 with an empty list, not
        404**, so this cannot tell you "the theme is gone" apart from "the
        theme matched nothing". If that distinction matters, check the id
        against :meth:`themes` first.
        """
        return self._get_obj(
            f"/v1/{encode_path('reports', 'themes', theme_id)}/conversations"
        )


__all__ = ["ATTRIBUTION_DIMENSIONS", "Reports"]
