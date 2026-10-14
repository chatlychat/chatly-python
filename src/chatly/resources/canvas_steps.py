"""``client.canvas_steps`` — the pending half of an interactive canvas."""

from __future__ import annotations

from typing import Any, Mapping

from .._transport import encode_path
from ._base import JsonDict, Resource


class CanvasSteps(Resource):
    """Settle a canvas step your backend was asked to resolve.

    When the widget submits a canvas and your own service has to do work
    before the next screen exists, Chatly records a **pending step** and
    answers the visitor immediately. This namespace is how that step is
    looked up and then settled with the canvas to show.

    A step is ``{"id", "conversationId", "messageId", "canvasId", "reason",
    "actionId", "status", "expiresAt", "settledAt", "createdAt"}``.
    ``reason`` is ``step`` or ``submit``; ``status`` is ``pending``,
    ``resolved`` or ``expired``. Both are plain strings on the wire rather
    than closed enums, so compare them as strings.

    Reads need ``messages:read``, :meth:`resolve` needs ``messages:write``.
    **A step lives for ten minutes.**
    """

    def get(self, step_id: str) -> JsonDict:
        """One pending step, without its canvas.

        It deliberately carries **no ``canvas``** — this answers "did my
        resolve land, or did the step lapse?", which is the question a worker
        has after crashing between charging a card and showing the receipt.
        ``status`` and ``settledAt`` are the fields to read.

        A malformed id is a clean 400; an id that names nothing in this
        workspace is a 404.
        """
        return self._get_obj(f"/v1/{encode_path('canvas-steps', step_id)}")

    def resolve(self, step_id: str, canvas: Mapping[str, Any]) -> JsonDict:
        """Settle a step with the canvas to display. Answers **201**.

        Args:
            canvas: a canvas object. ``v`` must be the literal ``1``,
                ``canvasId`` is required (1–64 characters of
                ``A-Za-z0-9._:-``), and **exactly one** of ``blocks`` (1–20)
                or ``app`` must be present — neither and both are 400s.
                ``inputs`` (≤12), ``actions`` (≤4), ``state`` (≤8192
                characters) and ``path`` are optional. The object is strict,
                so an unknown key is a 400, and ``issuedAt`` is overwritten
                by the server even if you send one.

        Returns ``{"stepId", "conversationId", "messageId", "canvasId"}``.

        **This consumes the step**, in a single conditional update, so
        exactly one caller can win: a second resolve is a **409**, and so is
        one that arrives after the ten-minute expiry — that refusal carries
        the expiry instant so you can tell "already done" from "too late".

        Side effects beyond the step itself: it overwrites the canvas **and
        the plain-text body** of the step's message and publishes a
        ``message.updated`` event, so the visitor's open widget updates
        without polling.

        Two 404s that are not what they look like. Resolving from inside the
        request that *returned* ``{"pending": true}`` is a 404, because the
        step row is written after that answer is sent — wait for your own
        webhook or retry. And a step whose message an agent retracted is a
        404 with the step left ``pending`` rather than wrongly settled.

        It accepts **no host event**; fire one on the pending answer instead.
        """
        return self._post_obj(
            f"/v1/{encode_path('canvas-steps', step_id)}/resolve",
            {"canvas": dict(canvas)},
        )


__all__ = ["CanvasSteps"]
