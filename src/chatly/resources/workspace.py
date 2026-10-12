"""``client.workspace`` — settings, labels, inboxes, team rosters, skills."""

from __future__ import annotations

from typing import Any, List, Optional

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list


class Workspace(Resource):
    """Workspace-level configuration reads."""

    def settings(self) -> JsonDict:
        """The workspace settings blob. No parameters.

        Nine keys, **all always present** — the server fills defaults for
        anything absent or unparseable in storage, so you never have to
        guard a missing key:

            * ``autoTagging`` → ``{"enabled", "taxonomy"}``
            * ``dlqRetentionDays`` → int or ``null``
            * ``aiSimilarityThreshold`` → 0.5–0.95, default 0.7
            * ``notifications`` → ``{"richPushEnabled",
              "includeMessagePreview", "includeImagePreview",
              "showActionButtons"}``
            * ``robotsTxt`` → string or ``null``
            * ``accountFitScorecard`` → ``{"tierWeights",
              "employeeBandWeights", "revenueBandWeights", "industryBoosts"}``
            * ``onboarding`` → ``{"completed", "completedTours"}`` plus
              ``dismissedAt``, **the one genuinely optional key in the whole
              blob** — it is absent, not null, when nothing was dismissed
            * ``privacy`` → ``{"visitorReadReceipts"}``
            * ``quickReactions`` → 1–12 emoji

        Note the path is singular: ``/v1/workspace/settings``, while the rest
        of the workspace API is under ``/v1/workspaces``.

        Writing settings (``PATCH``) is not available to an API key.
        """
        return self._get_obj("/v1/workspace/settings")

    def labels(self, *, usage: Optional[bool] = None, **params: Any) -> List[JsonDict]:
        """Conversation labels, as a bare list ordered by name.

        Args:
            usage: ``False``/omitted returns ``{"id", "name", "description",
                "color", "showInSidebar", "createdAt", "updatedAt"}``.
                ``True`` returns **a different shape**: the same keys plus
                ``conversations``, ``contacts`` and ``registered``, and it
                also includes labels that are in use but were never
                registered. Those arrive with ``id: ""``, ``createdAt: ""``,
                ``updatedAt: ""``, ``color: "#94a3b8"`` and
                ``registered: false`` — so **do not key a dict on ``id``**
                when ``usage=True``; several rows can share the empty string.

        The wire parameter is the literal ``"0"`` or ``"1"`` and nothing
        else; anything else is a 400, so this method converts the boolean
        for you.

        Needs ``conversations:read`` — not ``workspace:read``, which is
        worth knowing when scoping a key for a labels-only integration.
        Creating, renaming and deleting labels require a signed-in person.
        """
        wire = None if usage is None else ("1" if usage else "0")
        return as_list(self._get("/v1/labels", {"usage": wire, **params}))

    def inboxes(self) -> List[JsonDict]:
        """Inboxes, as a bare list. No parameters, no paging.

        ``{"channelId", "name", "type", "enabled", "settings"}``.

        **The id field is ``channelId``, not ``id``** — an inbox *is* a
        channel on this API, and every sibling route is keyed by
        ``:channelId``. Code that reads ``row["id"]`` here raises
        ``KeyError``.

        ``settings`` is the fully resolved inbox configuration: routing
        (``routingStrategy``, which is ``null`` when it inherits the
        workspace default, and ``routingTeamId``), capacity
        (``capacityEnabled``, ``capacityLimit``, ``capacityExcludeLabels``,
        ``capacityExcludeIdleHours``, ``capacityOverflow`` which is ``queue``
        or ``overflow_team``, ``capacityOverflowTeamId``), skills
        (``skillsRequired``, ``skillsMatchLanguage``, ``skillsFromTags``,
        ``skillsUnmatched``, ``skillsUnmatchedTeamId``),
        ``stickyLookbackDays``, CSAT (``csatMode`` — ``inherit``, ``off`` or
        ``survey`` — ``csatSurveyId``, ``csatIncludeLabels``,
        ``csatExcludeLabels``) and ``businessHours`` (nullable).

        Needs ``channels:read``. Every other inboxes route, including all the
        settings writes, requires a signed-in person.
        """
        return as_list(self._get("/v1/inboxes"))

    def team_members(self, team_id: str) -> List[JsonDict]:
        """The members of one team, as a bare list. No paging.

        ``{"teamMemberId", "userId", "name", "email", "avatarUrl", "role",
        "joinedAt"}``. Note **two** ids per row: ``teamMemberId`` is the
        membership and ``userId`` is the person. Member-management routes
        take the user id; do not pass the membership id to one.

        Deliberately pagination-exempt — a team roster is a subset of the
        workspace's seats and is read as a single list.

        Takes a team id, so you need one from elsewhere: a conversation's
        ``teamId``, an inbox's ``settings["routingTeamId"]``, or a workflow.

        Needs ``members:read``.
        """
        return as_list(self._get(f"/v1/{encode_path('teams', team_id)}/members"))

    def agent_skills(self) -> JsonDict:
        """The workspace's skill taxonomy — the distinct skill labels in use.

        Returns ``{"skills": [...]}``, a settings-style list, typically under
        fifty entries. These are the labels skill-based routing matches
        against; an inbox with ``settings["skillsRequired"]`` set is matching
        on strings from this set.

        **Skill labels, not agents.** For the people, read a team's roster
        with :meth:`team_members`, or take ``userId`` from
        :meth:`chatly.resources.reports.Reports.agents`.

        Needs ``members:read``.
        """
        return self._get_obj("/v1/agents/skills")


__all__ = ["Workspace"]
