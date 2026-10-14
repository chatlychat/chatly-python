"""``client.bot_routes`` — which bot answers, and when."""

from __future__ import annotations

from typing import Any, List

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list


class BotRoutes(Resource):
    """Rules that pick a bot for an incoming conversation.

    A route is ``{"id", "workspaceId", "brandId", "botId", "name",
    "priority", "enabled", "channelTypes", "conditions", "evaluate",
    "createdAt", "updatedAt"}``. Reads need ``triggers:read``, writes
    ``triggers:write``.

    **Priority is evaluation order and the first match wins**, so a route's
    usefulness depends on what sits above it. :meth:`list` returns them in
    that order; :meth:`resolve` tells you what the order *does* for a given
    situation, which is almost always the faster way to debug one.
    """

    def list(self) -> List[JsonDict]:
        """Every route, in evaluation order. A bare list, no cursor.

        Ordered by ``priority`` ascending then ``createdAt`` ascending — the
        order the resolver walks, not an arbitrary one.

        **Disabled routes are included** (``enabled: False``), unlike
        :meth:`resolve`, which only considers enabled ones.

        A condition's ``value`` may be **absent** rather than null: the key
        is omitted when the stored rule has no comparand, so use ``.get()``.
        """
        return as_list(self._get("/v1/bot-routes"))

    def fields(self) -> JsonDict:
        """The vocabulary a condition may be written against.

        Returns ``{"fields", "prefixes", "operators", "evaluate"}`` — **an
        object, despite the plural name**. The array is under ``fields``.

        ``fields`` are the six fixed keys (``page.path``, ``page.url``,
        ``contact.identityVerified``, ``channel.publicId``, ``locale``,
        ``body``) as ``{"key", "label", "type", "description"}``, and
        ``prefixes`` are the three namespaces a single segment may be
        appended to — ``context.verified.``, ``context.unverified.``,
        ``contact.attributes.``. A workspace's own signed claim keys are
        deliberately **not** enumerated, which is what the prefixes are for.

        Static for the whole platform — no workspace, no database — so cache
        it rather than fetching it per form render. Anything outside this
        vocabulary is a 400 from :meth:`create` that names the legal set.
        """
        return self._get_obj("/v1/bot-routes/fields")

    def create(self, *, bot_id: str, name: str, **fields: Any) -> JsonDict:
        """Create a route. Answers 201. ``fields`` takes **wire** names.

        Args:
            bot_id: the bot to route to. **Validated against the workspace
                here** — a bot id from somewhere else is a 400. (Note
                :meth:`update` does *not* re-check it.)
            name: 1–160 characters.

        Optional, by wire name: ``priority`` (0–10,000), ``enabled``,
        ``channelTypes`` (up to 20), ``conditions`` (up to 20), ``brandId``
        (or ``None``), ``evaluate`` (``conversation_start`` or
        ``every_message``).

        ``priority``, ``enabled`` and ``evaluate`` are defaulted by the
        **database column** rather than by the request schema, so omitting
        them gets the platform's answer rather than a value this SDK invented.

        Each condition is ``{"field", "op", "value"}`` where ``field`` comes
        from :meth:`fields` — a single segment under a prefix, so
        ``context.verified.plan`` is legal and ``context.verified.plan.tier``
        is a 400 — and ``op`` is one of ``eq``, ``neq``, ``in``, ``gt``,
        ``lt``, ``contains``, ``matches``.
        """
        body: JsonDict = {"botId": bot_id, "name": name}
        body.update(fields)
        return self._post_obj("/v1/bot-routes", body)

    def update(self, route_id: str, **fields: Any) -> JsonDict:
        """Update a route. Every field optional, **wire** names.

        Two differences from :meth:`create` worth knowing. An **empty body is
        accepted** here — it just bumps ``updatedAt`` — so a no-op call
        succeeds silently rather than telling you nothing was sent. And
        ``botId`` is **not** re-validated against the workspace: a bad one is
        written straight through, and the route then matches and fails to
        resolve. Validate it yourself, or create a new route instead.

        A missing route id is a 404.
        """
        return self._patch_obj(
            f"/v1/{encode_path('bot-routes', route_id)}", dict(fields)
        )

    def delete(self, route_id: str) -> JsonDict:
        """Delete a route. Returns ``{"deleted": true}`` with a **200**.

        A hard delete — there is no ``deleted_at`` on this table and no undo.

        **It answers 200 for an id that does not exist**, because the service
        never checks the row count. ``deleted: True`` is a literal with
        nothing to branch on, so it tells you the call succeeded and nothing
        about whether a route was there. Note the sibling
        :meth:`chatly.resources.brands.Brands.delete` answers ``{"id": ...}``
        instead — the two are not interchangeable shapes.
        """
        return self._delete_obj(f"/v1/{encode_path('bot-routes', route_id)}")

    def resolve(self, **situation: Any) -> JsonDict:
        """Dry-run the routing table against a hypothetical conversation.

        Answers **201** (it is a POST), and **writes nothing** — it reads no
        conversation, no contact and no stored context. It is a POST only
        because the situation travels in a body.

            verdicts = client.bot_routes.resolve(
                page={"url": "https://acme.com/pricing"},
                contact={"identityVerified": True},
                moment="follow_up",
            )

        Every field is optional and defaulted, so ``resolve()`` is a valid
        call: ``page``, ``context`` (``{"verified": {}, "unverified": {}}``),
        ``contact`` (``{"identityVerified": False, "attributes": {}}``),
        ``channelType`` (default ``"web"``), ``channelPublicId``,
        ``brandId``, ``locale``, ``body``, ``moment``
        (``conversation_start`` — the default — or ``follow_up``).

        **The body is strict: an unknown key is a 400**, not ignored. That
        includes a misspelled nested key, since ``page``, ``context`` and
        ``contact`` are strict too.

        Returns ``{"selected", "routes", "event"}``. ``selected`` is ``None``
        when nothing matched. ``routes`` lists only the **enabled** routes,
        in evaluation order, each with a ``verdict`` whose ``kind`` is
        ``matched``, ``not_eligible_at_moment``, ``channel_excluded``,
        ``brand_excluded`` or ``condition_failed``; ``verdict.actual`` is
        what the field resolved to, and the difference between *absent* and a
        real value is the difference between "no such attribute" and "your
        expectation was wrong". ``event`` is the object the conditions ran
        against — the only way to watch a field path resolve to nothing.

        Two traps. ``moment`` is the first thing to reach for when a route
        "works on the first message and then stops": at ``follow_up`` only
        ``every_message`` routes are eligible. And a ``matched`` verdict does
        **not** promise the bot would actually answer — this applies no
        answerability guards, so a thread a human has taken over, or one the
        bot already owns, still shows a match.
        """
        return self._post_obj("/v1/bot-routes/resolve", dict(situation))


__all__ = ["BotRoutes"]
