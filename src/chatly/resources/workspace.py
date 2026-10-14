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


    def mine(self) -> List[JsonDict]:
        """Every workspace the caller can reach. A bare list.

        **For an API key that is a list of exactly one** — the workspace the
        key was minted in — which makes this the cheapest way to confirm
        which tenant a credential actually points at, and to get the
        workspace's ``name``, ``slug`` and ``plan`` while you are there. The
        route is the cross-workspace one, so the single-entry answer is a
        property of the credential rather than of the route.

        Each row is ``{"id", "name", "slug", "plan", "role", "createdAt"}``.
        ``role`` is **the caller's role in that workspace, not a property of
        the workspace** — and for a key it is the synthetic ``restricted``
        every key is given, never the role of whoever created it. What a key
        may actually do is its scope set: read that from the client's own
        ``me()`` or :meth:`chatly.ChatlyClient.whoami`.

        Reachable on a **suspended** workspace, deliberately: this is how a
        caller discovers the others, and refusing it would strand someone in
        the suspended one with a healthy workspace a click away.

        Pagination-exempt — the list is bounded by the caller's own
        memberships.
        """
        return as_list(self._get("/v1/workspaces/me"))

    def key_scopes(self) -> List[JsonDict]:
        """The scopes an API key can be granted. A bare list.

        Each row is ``{"value", "group"}``, where ``group`` is just the part
        of ``value`` before the first colon.

        **Static and workspace-independent** — identical for every caller, so
        cache it. It is also the only route on the api-keys controller a key
        may call besides ``whoami``: managing keys with a key is a
        privilege-escalation shape.

        **This is deliberately not the whole permission vocabulary.** It once
        returned all ~80 permissions, which let customers mint keys scoped to
        permissions no key-accessible route honours — every call then 403'd.
        It is now pinned to the permissions actually required by decorated
        routes, so it **grows as the surface grows**: fetch it rather than
        hard-coding a copy.

        Compare :meth:`chatly.ChatlyClient.whoami`, which reports the scopes
        *your* key really holds.
        """
        return as_list(self._get("/v1/api-keys/scopes"))

    def secrets(self) -> JsonDict:
        """A census of every credential the workspace stores.

        **Needs two scopes, ANDed: ``workspace:write`` and
        ``integrations:read``.** It is the only route on this SDK's surface
        that requires two, and a key holding one of them gets a 403.

        Returns ``{"items", "total", "truncated"}`` — an ``items`` key and
        **no cursor**, so this is not a page. It cannot be one: the census
        spans nine tables with mixed UUID v4 and v7 ids and no common keyset.

        **No entry carries a secret, a prefix of one, a hash of one, or its
        length.** That is a hard constraint and the reason this route may be
        key-accessible at all.

        Each item is ``{"id", "source", "kind", "label", "location",
        "resourceId", "surfaces", "owner", "status", "createdAt",
        "rotatedAt", "rotatedAtBasis", "lastUsedAt", "lastUsedBasis",
        "rotateRoute", "scopes", "headerNames"}``. ``id`` is a synthetic
        ``<source>:<rowid>[:<keypath>]``, not a database id.

        Three fields need reading carefully:

        * **Read the ``*Basis`` field before believing a null timestamp.**
          ``None`` with ``"none"`` means *nothing records this* — true of
          ``rotatedAt`` on eight of the nine sources, because no table has a
          rotated-at column. ``None`` with ``"column"`` or ``"derived"``
          means we looked and it genuinely has not happened.
        * ``headerNames`` is ``[]`` on kinds that have no headers, but
          **``None`` means the encrypted bag could not be decrypted** — a
          distinct and actionable fact about a rotated encryption key.
        * ``rotateRoute`` is a literal ``"VERB /v1/..."`` with ids already
          substituted, or ``None`` where rotation takes more than one call.

        ``status: "inactive"`` does **not** mean safe to ignore: the material
        is still live.

        **Check ``truncated`` before concluding a credential does not
        exist.** ``True`` means at least one source hit its 250-row cap and
        the census is incomplete.
        """
        return self._get_obj("/v1/workspace/secrets")


__all__ = ["Workspace"]
