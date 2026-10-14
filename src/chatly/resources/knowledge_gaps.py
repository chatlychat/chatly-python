"""``client.knowledge_gaps`` — questions the AI could not answer."""

from __future__ import annotations

from typing import Any, List, Optional

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list

#: The lifecycle of a gap. ``drafted`` is not a terminal state — see
#: :meth:`KnowledgeGaps.draft`.
GAP_STATUSES = ("open", "drafted", "resolved", "dismissed")


class KnowledgeGaps(Resource):
    """The recorder's queue of unanswered questions, and the drafter.

    A gap is ``{"id", "question", "occurrences", "firstSeenAt",
    "lastSeenAt", "status", "articleId", "conversationId"}``. The two
    timestamps are ISO strings. ``articleId`` and ``conversationId`` are
    **nullable, not absent**, and ``conversationId: None`` is the one that
    matters: a gap with no conversation behind it cannot be drafted at all
    (:meth:`draft` answers 400, not an empty draft).

    Reads need ``kb:read``; both writes need ``kb:write``.
    """

    def list(
        self,
        *,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        **params: Any,
    ) -> List[JsonDict]:
        """Open gaps, busiest first. A bare list — no cursor on this route.

        Args:
            status: one of :data:`GAP_STATUSES`. **An unrecognised value is
                silently ignored rather than rejected**, so ``status="OPEN"``
                returns every gap in every state and looks like a working
                filter. Compare the ``status`` on the rows you get back if it
                matters.
            limit: 1–200, default 100. Clamped, and ``limit=0`` becomes 100
                rather than an empty list.

        Ordering is ``occurrences`` then ``lastSeenAt``, both descending —
        this is a work queue, not a log. The recorder bounds a workspace at
        200 open gaps, which is why there is no cursor: the whole set fits in
        one response.
        """
        return as_list(
            self._get(
                "/v1/knowledge-gaps", {"status": status, "limit": limit, **params}
            )
        )

    def update(self, gap_id: str, status: str) -> JsonDict:
        """Move a gap to ``status``. Returns the updated gap.

        ``status`` is required and is the **only** accepted field: the body
        schema is strict, so an extra key is a 400 rather than being
        stripped. Use this to ``dismiss`` a question that should not become
        an article, or to mark one ``resolved`` after answering it some other
        way.

        The route requires an ``Idempotency-Key``, which this SDK mints per
        call — without one it is a 428 in production.
        """
        return self._patch_obj(
            f"/v1/{encode_path('knowledge-gaps', gap_id)}", {"status": status}
        )

    def draft(self, gap_id: str) -> JsonDict:
        """Draft a KB article for a gap from its conversation transcript.

        Takes no body. Answers **201**, and returns
        ``{"gap", "articleId", "reason"}``.

        **This costs an LLM call** — up to a 45-second one — and it drafts
        from the transcript of the conversation the gap was recorded on,
        never from research into the question. It reads the last ~7,500
        characters of up to 200 messages, with internal notes excluded.

        Three outcomes, and only the first is what the name suggests:

        * An article was written → ``articleId`` is set, ``reason`` is
          ``None``, and the gap becomes **``drafted``**, not ``resolved``.
          The article is created with ``status: "draft"`` and is **not
          published**, so nothing is customer-visible until someone
          publishes it.
        * The model judged there is no reusable answer in the transcript →
          a success with ``articleId: None`` and a human-readable
          ``reason``. Check ``articleId``, not the status code.
        * The gap has no conversation, or its transcript is empty → a 400.
          That is a property of the gap, so retrying will not change it.

        An unknown gap id is a 404. Requires an ``Idempotency-Key``, which
        this SDK mints per call; pin one with
        :meth:`chatly.ChatlyClient.with_idempotency_key` if a retry across
        process restarts must not pay for a second generation.
        """
        return self._post_obj(f"/v1/{encode_path('knowledge-gaps', gap_id)}/draft")


__all__ = ["GAP_STATUSES", "KnowledgeGaps"]
