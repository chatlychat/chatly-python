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
    """Read-only billing. Requires a key with ``workspace:billing:read``."""

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


__all__ = ["USAGE_EVENT_TYPES", "Billing"]
