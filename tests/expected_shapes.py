"""The response shape **this SDK's decoder expects** from each of the 163
routes, declared by hand.

======================= READ THIS BEFORE CHANGING A VALUE ===============

Hand-written from the API's handlers — from each one's ``@ZodResponse``
schema, or from the service return type where it has none — and deliberately
**not** read from ``packages/sdk-spec/surface.json``, even though the suite
next door loads that manifest for the path templates and the verbs.

A fixture derived from the manifest agrees with whatever the manifest says,
including when the manifest is wrong, and that is not hypothetical. The
sibling field ``paged`` was wrong in both directions for months:
``macros.list`` was flagged paged while its handler is ``@PaginationExempt``
and answers a bare 200 array, and three genuinely cursored routes were
unflagged. The .NET and Rust clients built paginators over ``GET /v1/macros``
and raised a decode error against the real API with green suites, because
their fake transports answered EVERY route with
``{"items": ..., "nextCursor": ...}``. Worse, Rust's derived page decoder
read the bare array as an *empty page* and returned it with a 200 — a wrong
answer rather than a missing one.

So this column is a second opinion, not a copy. ``tests/test_surface_lock.py``
feeds each method the shape declared here and asserts the value handed back
really has it; the lock carries the declaration; and
``scripts/check-sdk-surface-parity.mjs`` then diffs eight independently
written columns against the manifest. A wrong manifest row needs eight
authors to misread the same handler.

It lives in its own module only because ``test_surface_lock.py`` reached the
650-line ceiling the contract sets (§9). Nothing else imports it.

Rows that look wrong and are not — every one of these was read off a handler:

* ``contacts.remove_tag`` is a ``DELETE`` that answers 200 with the
  surviving contact — the same object the tag ``POST`` returns.
* ``conversations.cancel_scheduled`` is a ``DELETE`` that answers 200 with
  the row it just cancelled.
* ``macros.delete`` is the ONLY real 204 on this surface. Eleven other
  deletes answer 200 **with a body**, and they do not even agree on the
  body: ``{"ok": true}`` on ``triggers``, ``customer_cards`` and
  ``customer_card_endpoints``, ``{"deleted": true}`` on ``bot_routes`` and
  ``ai.delete_tool``, ``{"id": ...}`` on ``brands``, ``{"kept": n}`` on
  ``docs_sources``, ``{"restored": bool}`` on ``email_templates``.
* Four routes carry an ``items`` key and are **not** pages, because nothing
  cursors them: ``conversations.outcomes``, ``conversations.linked``,
  ``billing.usage_monthly``, ``workspace.secrets``, plus
  ``tickets.status_history`` and ``tickets.time``. A decoder keyed on the
  presence of ``items`` gets these wrong.
* ``billing.invoices`` is the opposite trap: genuinely cursor-paginated, and
  still ``object``, because its envelope key is ``data`` rather than
  ``items``. It is correctly not ``paged``, and the SDK hand-rolls the walk.
* Nine routes wrap a single list in a single key and so are objects:
  ``ai.providers`` (``providers``), ``webhooks.events`` (``eventTypes``),
  ``macros.templates`` (``items``), ``reports.theme_conversations``
  (``conversationIds``), ``workspace.agent_skills`` (``skills``) among them.
* ``bot_routes.fields`` is an object despite the plural name, and
  ``channels.adapters`` really is a bare array — of **strings**, not objects.
* Two of the four original report routes are bare arrays
  (``reports.agents``, ``reports.conversations_by_day``) and two of the nine
  added ones are too (``reports.attribution``, ``reports.sources``). The rest
  are objects. There is no pattern to lean on; each was read.
"""

from __future__ import annotations

from typing import Dict

EXPECTED_SHAPE: Dict[str, str] = {
    "root.whoami": "object",
    # A discriminated union of two objects — `principal: "user" | "api_key"`
    # — so `object` either way. For a key the body is `whoami`'s plus the
    # discriminator.
    "root.me": "object",
    # -- ai ------------------------------------------------------------
    "ai.providers": "object",  # `{providers: [...]}`, not a bare array
    "ai.add_provider": "object",
    "ai.test_provider": "object",
    "ai.tools": "array",
    "ai.create_tool": "object",
    "ai.update_tool": "object",
    "ai.delete_tool": "object",  # 200 `{deleted: true}`, not a 204
    "ai.tone": "array",
    "ai.set_tone": "array",  # a PUT that answers with the stored list
    "ai.generate_tone": "object",
    "ai.tone_preview": "object",  # `{instruction}` — an object round a string
    "ai.quota": "object",
    # -- billing -------------------------------------------------------
    "billing.plans": "array",
    "billing.usage": "object",
    "billing.summary": "object",
    "billing.invoices": "object",  # paginated, but the key is `data`
    "billing.usage_daily": "object",
    "billing.usage_monthly": "object",  # has `items`, has no cursor
    # -- bot routes ----------------------------------------------------
    "bot_routes.list": "array",
    "bot_routes.fields": "object",  # `{fields, prefixes, operators, evaluate}`
    "bot_routes.create": "object",
    "bot_routes.update": "object",
    "bot_routes.delete": "object",  # 200 `{deleted: true}`
    "bot_routes.resolve": "object",
    # -- bots ----------------------------------------------------------
    "bots.list": "page",  # `buildPaginatedResponse`, so `hasMore` too
    "bots.create": "object",
    "bots.get": "object",
    "bots.update": "object",
    "bots.update_external": "object",
    "bots.rotate_external_secret": "object",
    "bots.analytics": "object",
    "bots.deliveries": "page",  # also `buildPaginatedResponse`
    "bots.delivery": "object",
    "bots.redeliver": "object",
    "bots.test_delivery": "object",
    # -- brands --------------------------------------------------------
    "brands.list": "array",
    "brands.create": "object",
    "brands.update": "object",
    "brands.delete": "object",  # 200 `{id}` — a third delete shape
    # -- canvas steps --------------------------------------------------
    "canvas_steps.get": "object",
    "canvas_steps.resolve": "object",
    # -- channels ------------------------------------------------------
    "channels.list": "array",
    "channels.get": "object",
    "channels.adapters": "array",  # an array of plain strings
    "channels.create": "object",
    "channels.update": "object",
    "channels.rotate_secret": "object",
    # -- contacts ------------------------------------------------------
    "contacts.list": "page",
    "contacts.get": "object",
    "contacts.upsert": "object",
    "contacts.bulk_upsert": "object",
    "contacts.merge": "object",
    "contacts.add_tags": "object",
    "contacts.remove_tag": "object",  # a DELETE with a body
    "contacts.unsubscribe": "object",
    "contacts.journey": "page",
    "contacts.mood": "object",
    "contacts.cards": "object",  # a POST that reads; `{cards: [...]}`
    # -- conversations -------------------------------------------------
    "conversations.list": "page",
    "conversations.get": "object",
    "conversations.messages": "page",
    "conversations.send": "object",
    "conversations.unattended": "page",  # the envelope with `total`
    "conversations.agent_handling": "object",
    "conversations.set_agent_handling": "object",
    "conversations.generated_replies": "array",
    "conversations.generate_reply": "object",
    "conversations.scheduled_messages": "array",
    "conversations.schedule_message": "object",
    "conversations.cancel_scheduled": "object",  # also a DELETE with a body
    "conversations.linked": "object",  # `{items}`, no cursor
    "conversations.outcomes": "object",  # `{conversationId, items}`, no cursor
    "conversations.record_outcome": "object",
    "conversations.return_to_bot": "object",
    "conversations.unread_counts": "object",
    "conversations.update_blocks": "object",
    # -- customer cards ------------------------------------------------
    "customer_cards.list": "array",
    "customer_cards.create": "object",  # `{card, secret}` — secret beside it
    "customer_cards.update": "object",
    "customer_cards.rotate_secret": "object",
    "customer_cards.delete": "object",  # 200 `{ok: true}`
    "customer_card_endpoints.list": "array",
    "customer_card_endpoints.create": "object",
    "customer_card_endpoints.rotate_secret": "object",
    "customer_card_endpoints.activate_secret": "object",
    "customer_card_endpoints.delete": "object",  # 200 `{ok: true}`
    # -- docs sources --------------------------------------------------
    "docs_sources.list": "array",
    "docs_sources.providers": "array",
    "docs_sources.discover": "array",  # a POST answering a bare array
    "docs_sources.create": "object",
    "docs_sources.update": "object",
    "docs_sources.sync": "object",
    "docs_sources.webhook": "object",
    "docs_sources.delete": "object",  # 200 `{kept: n}`
    # -- email templates -----------------------------------------------
    "email_templates.list": "array",  # five rows, always — the catalogue
    "email_templates.preview": "object",
    "email_templates.update": "object",
    "email_templates.delete": "object",  # 200 `{restored: bool}`
    # -- cdp events ----------------------------------------------------
    "events.track": "object",
    "events.list": "page",
    # -- kb ------------------------------------------------------------
    "kb.articles": "page",
    "kb.article": "object",
    "kb.collections": "array",
    # -- knowledge gaps ------------------------------------------------
    "knowledge_gaps.list": "array",
    "knowledge_gaps.update": "object",
    "knowledge_gaps.draft": "object",
    # -- macros --------------------------------------------------------
    # `@PaginationExempt`, bare array, capped at 200 by usage rank. The row
    # that cost two SDKs a decode error in production.
    "macros.list": "array",
    "macros.create": "object",
    "macros.get": "object",
    "macros.update": "object",
    "macros.delete": "empty",  # `@HttpCode(204)`, handler returns nothing
    "macros.actions": "object",  # `{limit, actions}`
    "macros.templates": "object",  # `{items, total}` — total == len(items)
    "macros.template": "object",
    # -- reports -------------------------------------------------------
    "reports.overview": "object",
    "reports.agents": "array",
    "reports.conversations_by_day": "array",
    "reports.sla": "object",
    "reports.attribution": "array",
    "reports.cohorts": "object",
    "reports.labels": "object",
    "reports.response_times": "object",
    "reports.sources": "array",
    "reports.teams": "object",
    "reports.themes": "object",
    "reports.theme_conversations": "object",  # `{conversationIds: [...]}`
    "reports.voice": "object",
    # -- search --------------------------------------------------------
    "search.query": "page",  # `items` + `nextCursor` + `tier` + `facets`
    # -- tickets -------------------------------------------------------
    "tickets.list": "page",
    "tickets.comments": "array",
    "tickets.for_conversation": "array",
    "tickets.queues": "array",
    "tickets.merge": "object",
    "tickets.split": "object",
    "tickets.bulk": "object",
    "tickets.conversations": "array",
    "tickets.lineage": "object",
    "tickets.open_count": "object",
    "tickets.status_history": "object",  # `{..., items, truncated}`, no cursor
    "tickets.time": "object",  # `{items, totalMinutes, billableMinutes}`
    # -- triggers ------------------------------------------------------
    "triggers.list": "page",
    "triggers.create": "object",
    "triggers.delete": "object",  # 200 `{ok: true}`, not a 204
    # -- visitors ------------------------------------------------------
    # `{conversationId}`. No `@ZodResponse` on this handler at all, so the
    # shape is read off the service it forwards to:
    # `VisitorsService.startProactiveConversation(): Promise<{ conversationId:
    # string }>`. An object, and emphatically not a page — nothing about a
    # POST that creates one thing suggests a cursor, and the sibling that
    # also answers a single created row (`conversations.send`) is an object
    # for the same reason.
    "visitors.start_conversation": "object",
    # -- webhooks ------------------------------------------------------
    "webhooks.deliveries": "page",
    "webhooks.delivery": "object",
    "webhooks.redeliver": "object",
    "webhooks.list": "array",
    "webhooks.create": "object",
    "webhooks.events": "object",  # `{eventTypes: [...]}`
    "webhooks.schema_versions": "object",
    "webhooks.delete": "object",  # 200 `{ok: true}`, and a real 404 on a miss
    "webhooks.set_schema_version": "object",
    # -- workspace -----------------------------------------------------
    "workspace.settings": "object",
    "workspace.labels": "array",
    "workspace.inboxes": "array",
    "workspace.team_members": "array",
    "workspace.agent_skills": "object",
    "workspace.key_scopes": "array",
    "workspace.secrets": "object",  # `{items, total, truncated}`, no cursor
    # `z.array(workspaceListItemSchema)`. A bare array that holds exactly one
    # entry for a key, which is a property of the credential and not of the
    # route — so it is an array, not an object.
    "workspace.mine": "array",
}

#: The distribution of the column above, from reading all 163
#: ``@ZodResponse`` schemas (55 on 2026-10-12, then 104 and finally 3 more on
#: 2026-10-14 — ``webhooks.delete``, ``root.me`` and ``workspace.mine``,
#: which were absent from the manifest's first 159 and each read at its
#: handler here before being believed). A fourth went in later that same day:
#: ``visitors.start_conversation``, which has no ``@ZodResponse`` and so was
#: read off its service's declared return type instead — ``object``, taking
#: that column from 115 to 116.
#:
#: Asserted, because every other assertion about this table would be
#: satisfied by a column that said ``object`` one hundred and sixty-two
#: times — unanimity about nothing. If the surface grows these numbers
#: change, but all four shapes must stay represented and ``empty`` must stay
#: at exactly one until a second real 204 genuinely ships.
SHAPE_COUNTS = {"array": 33, "page": 13, "object": 116, "empty": 1}

__all__ = ["EXPECTED_SHAPE", "SHAPE_COUNTS"]
