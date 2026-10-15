"""One invocation per route on the typed surface, with throwaway arguments.

Separate from :mod:`test_surface` only because that module reached the
650-line ceiling the contract sets (§9) once the surface grew to 162 routes.

Every entry here is *called* — by :mod:`test_surface` to check the verb and
path each method really issues, and by :mod:`test_surface_lock` to generate
the committed lock. That is the point of the table: a doc comment cannot emit
an HTTP request, so a route with no entry here cannot be mistaken for an
implemented one.

The arguments are deliberately the cheapest thing that will reach the
transport. Where a method validates an argument locally — ``provider`` on the
AI routes, ``kind`` on the email templates, ``type`` on
``channels.create``, ``event_type`` on the billing usage routes — the value
must be a REAL member of that vocabulary, or the method raises before issuing
a request and the route goes unexercised while the suite stays green.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

#: How to invoke each entry with throwaway arguments. One per surface entry.
CALLS: Dict[Tuple[str, str], Callable[[Any], Any]] = {
    ("root", "whoami"): lambda c: c.whoami(),
    ("root", "me"): lambda c: c.me(),
    # -- ai ------------------------------------------------------------
    ("ai", "providers"): lambda c: c.ai.providers(),
    ("ai", "add_provider"): lambda c: c.ai.add_provider("openai", "sk-live-0123456789abcdef"),
    ("ai", "test_provider"): lambda c: c.ai.test_provider("openai"),
    ("ai", "tools"): lambda c: c.ai.tools(),
    ("ai", "create_tool"): lambda c: c.ai.create_tool(
        name="order.lookup",
        description="Look up an order by number",
        url_template="https://api.example.com/orders/{{order}}",
    ),
    ("ai", "update_tool"): lambda c: c.ai.update_tool("ID1", description="Look it up"),
    ("ai", "delete_tool"): lambda c: c.ai.delete_tool("ID1"),
    ("ai", "tone"): lambda c: c.ai.tone(),
    ("ai", "set_tone"): lambda c: c.ai.set_tone([{"category": "warmth", "rule": "Be kind"}]),
    ("ai", "generate_tone"): lambda c: c.ai.generate_tone("We write plainly and we never blame the customer."),
    ("ai", "tone_preview"): lambda c: c.ai.tone_preview(),
    ("ai", "quota"): lambda c: c.ai.quota(),
    # -- billing -------------------------------------------------------
    ("billing", "plans"): lambda c: c.billing.plans(),
    ("billing", "usage"): lambda c: c.billing.usage("ai.tokens"),
    ("billing", "summary"): lambda c: c.billing.summary(),
    ("billing", "invoices"): lambda c: c.billing.invoices(),
    ("billing", "usage_daily"): lambda c: c.billing.usage_daily("ai.tokens"),
    ("billing", "usage_monthly"): lambda c: c.billing.usage_monthly(),
    # -- bot routes ----------------------------------------------------
    ("bot_routes", "list"): lambda c: c.bot_routes.list(),
    ("bot_routes", "fields"): lambda c: c.bot_routes.fields(),
    ("bot_routes", "create"): lambda c: c.bot_routes.create(bot_id="BOT1", name="Pricing pages"),
    ("bot_routes", "update"): lambda c: c.bot_routes.update("ID1", name="Pricing"),
    ("bot_routes", "delete"): lambda c: c.bot_routes.delete("ID1"),
    ("bot_routes", "resolve"): lambda c: c.bot_routes.resolve(moment="follow_up"),
    # -- bots ----------------------------------------------------------
    ("bots", "list"): lambda c: c.bots.list(),
    ("bots", "create"): lambda c: c.bots.create(
        name="Support", systemPrompt="You answer billing questions for Acme."
    ),
    ("bots", "get"): lambda c: c.bots.get("ID1"),
    ("bots", "update"): lambda c: c.bots.update("ID1", name="Support v2"),
    ("bots", "update_external"): lambda c: c.bots.update_external("ID1", timeoutSeconds=30),
    ("bots", "rotate_external_secret"): lambda c: c.bots.rotate_external_secret("ID1"),
    ("bots", "analytics"): lambda c: c.bots.analytics("ID1"),
    ("bots", "deliveries"): lambda c: c.bots.deliveries("ID1"),
    ("bots", "delivery"): lambda c: c.bots.delivery("ID1", "DEL1"),
    ("bots", "redeliver"): lambda c: c.bots.redeliver("ID1", "DEL1"),
    ("bots", "test_delivery"): lambda c: c.bots.test_delivery("ID1"),
    # -- brands --------------------------------------------------------
    ("brands", "list"): lambda c: c.brands.list(),
    ("brands", "create"): lambda c: c.brands.create(name="Acme", slug="acme"),
    ("brands", "update"): lambda c: c.brands.update("ID1", name="Acme Ltd"),
    ("brands", "delete"): lambda c: c.brands.delete("ID1"),
    # -- canvas steps --------------------------------------------------
    ("canvas_steps", "get"): lambda c: c.canvas_steps.get("ID1"),
    ("canvas_steps", "resolve"): lambda c: c.canvas_steps.resolve(
        "ID1", {"v": 1, "canvasId": "receipt", "blocks": [{"type": "text", "text": "Paid"}]}
    ),
    # -- channels ------------------------------------------------------
    ("channels", "list"): lambda c: c.channels.list(),
    ("channels", "get"): lambda c: c.channels.get("ID1"),
    ("channels", "adapters"): lambda c: c.channels.adapters(),
    ("channels", "create"): lambda c: c.channels.create(
        type="api", name="Custom", public_id="custom-1"
    ),
    ("channels", "update"): lambda c: c.channels.update("ID1", name="Custom 2"),
    ("channels", "rotate_secret"): lambda c: c.channels.rotate_secret("ID1"),
    # -- contacts ------------------------------------------------------
    ("contacts", "list"): lambda c: c.contacts.list(),
    ("contacts", "get"): lambda c: c.contacts.get("ID1"),
    ("contacts", "upsert"): lambda c: c.contacts.upsert(email="a@example.com"),
    ("contacts", "bulk_upsert"): lambda c: c.contacts.bulk_upsert([{"email": "a@example.com"}]),
    ("contacts", "merge"): lambda c: c.contacts.merge("ID1", "ID2"),
    ("contacts", "add_tags"): lambda c: c.contacts.add_tags("ID1", "vip"),
    ("contacts", "remove_tag"): lambda c: c.contacts.remove_tag("ID1", "TAG1"),
    ("contacts", "unsubscribe"): lambda c: c.contacts.unsubscribe("ID1"),
    ("contacts", "journey"): lambda c: c.contacts.journey("ID1"),
    ("contacts", "mood"): lambda c: c.contacts.mood("ID1"),
    ("contacts", "cards"): lambda c: c.contacts.cards("CONT1"),
    # -- conversations -------------------------------------------------
    ("conversations", "list"): lambda c: c.conversations.list(),
    ("conversations", "get"): lambda c: c.conversations.get("ID1"),
    ("conversations", "messages"): lambda c: c.conversations.messages("ID1"),
    ("conversations", "send"): lambda c: c.conversations.send("ID1", "hello"),
    ("conversations", "unattended"): lambda c: c.conversations.unattended(),
    ("conversations", "agent_handling"): lambda c: c.conversations.agent_handling("ID1"),
    ("conversations", "set_agent_handling"): lambda c: c.conversations.set_agent_handling(
        "ID1", "handled"
    ),
    ("conversations", "generated_replies"): lambda c: c.conversations.generated_replies("ID1"),
    ("conversations", "generate_reply"): lambda c: c.conversations.generate_reply("ID1", "draft"),
    ("conversations", "scheduled_messages"): lambda c: c.conversations.scheduled_messages("ID1"),
    ("conversations", "schedule_message"): lambda c: c.conversations.schedule_message(
        "ID1", "later", "2026-10-13T09:00:00Z"
    ),
    ("conversations", "cancel_scheduled"): lambda c: c.conversations.cancel_scheduled("SCHED1"),
    ("conversations", "linked"): lambda c: c.conversations.linked("ID1"),
    ("conversations", "outcomes"): lambda c: c.conversations.outcomes("ID1"),
    ("conversations", "record_outcome"): lambda c: c.conversations.record_outcome(
        "ID1", "resolved", reason="Answered from the KB"
    ),
    ("conversations", "return_to_bot"): lambda c: c.conversations.return_to_bot("ID1", "BOT1"),
    ("conversations", "unread_counts"): lambda c: c.conversations.unread_counts(),
    ("conversations", "update_blocks"): lambda c: c.conversations.update_blocks(
        "ID1", "MSG1", [{"id": "card_1", "set": {"text": "Paid"}}]
    ),
    # -- customer cards ------------------------------------------------
    ("customer_cards", "list"): lambda c: c.customer_cards.list(),
    ("customer_cards", "create"): lambda c: c.customer_cards.create(
        key="orders", title="Recent orders", url="https://api.example.com/card", ttl_seconds=300
    ),
    ("customer_cards", "update"): lambda c: c.customer_cards.update("ID1", title="Orders"),
    ("customer_cards", "rotate_secret"): lambda c: c.customer_cards.rotate_secret("ID1"),
    ("customer_cards", "delete"): lambda c: c.customer_cards.delete("ID1"),
    ("customer_card_endpoints", "list"): lambda c: c.customer_card_endpoints.list(),
    ("customer_card_endpoints", "create"): lambda c: c.customer_card_endpoints.create(
        "https://api.example.com/card"
    ),
    ("customer_card_endpoints", "rotate_secret"): lambda c: c.customer_card_endpoints.rotate_secret(
        "ID1"
    ),
    ("customer_card_endpoints", "activate_secret"): (
        lambda c: c.customer_card_endpoints.activate_secret("ID1")
    ),
    ("customer_card_endpoints", "delete"): lambda c: c.customer_card_endpoints.delete("ID1"),
    # -- docs sources --------------------------------------------------
    ("docs_sources", "list"): lambda c: c.docs_sources.list(),
    ("docs_sources", "providers"): lambda c: c.docs_sources.providers(),
    ("docs_sources", "discover"): lambda c: c.docs_sources.discover(
        provider="gitbook", token="tok_123"
    ),
    ("docs_sources", "create"): lambda c: c.docs_sources.create(
        provider="gitbook", token="tok_123", organization_id="org_1", space_id="space_1"
    ),
    ("docs_sources", "update"): lambda c: c.docs_sources.update("ID1", label="Guides"),
    ("docs_sources", "sync"): lambda c: c.docs_sources.sync("ID1", full=True),
    ("docs_sources", "webhook"): lambda c: c.docs_sources.webhook("ID1"),
    ("docs_sources", "delete"): lambda c: c.docs_sources.delete("ID1"),
    # -- email templates -----------------------------------------------
    ("email_templates", "list"): lambda c: c.email_templates.list(),
    ("email_templates", "preview"): lambda c: c.email_templates.preview(
        "workspace_invite", subject="Join {{ workspace_name }}", body="Hello"
    ),
    ("email_templates", "update"): lambda c: c.email_templates.update(
        "workspace_invite", subject="Join us", body="Hello"
    ),
    ("email_templates", "delete"): lambda c: c.email_templates.delete("workspace_invite"),
    # -- cdp events ----------------------------------------------------
    ("events", "track"): lambda c: c.events.track("ID1", "trial_started"),
    ("events", "list"): lambda c: c.events.list(),
    # -- kb ------------------------------------------------------------
    ("kb", "articles"): lambda c: c.kb.articles(),
    ("kb", "article"): lambda c: c.kb.article("SLUG1"),
    ("kb", "collections"): lambda c: c.kb.collections(),
    # -- knowledge gaps ------------------------------------------------
    ("knowledge_gaps", "list"): lambda c: c.knowledge_gaps.list(),
    ("knowledge_gaps", "update"): lambda c: c.knowledge_gaps.update("ID1", "dismissed"),
    ("knowledge_gaps", "draft"): lambda c: c.knowledge_gaps.draft("ID1"),
    # -- macros --------------------------------------------------------
    ("macros", "list"): lambda c: c.macros.list(),
    ("macros", "create"): lambda c: c.macros.create(name="Thanks", scope="workspace", body="ta"),
    ("macros", "get"): lambda c: c.macros.get("ID1"),
    ("macros", "update"): lambda c: c.macros.update("ID1", name="Thanks again"),
    ("macros", "delete"): lambda c: c.macros.delete("ID1"),
    ("macros", "actions"): lambda c: c.macros.actions(),
    ("macros", "templates"): lambda c: c.macros.templates(),
    ("macros", "template"): lambda c: c.macros.template("SLUG1"),
    # -- reports -------------------------------------------------------
    ("reports", "overview"): lambda c: c.reports.overview(),
    ("reports", "agents"): lambda c: c.reports.agents(),
    ("reports", "conversations_by_day"): lambda c: c.reports.conversations_by_day(),
    ("reports", "sla"): lambda c: c.reports.sla(),
    ("reports", "attribution"): lambda c: c.reports.attribution(),
    ("reports", "cohorts"): lambda c: c.reports.cohorts(),
    ("reports", "labels"): lambda c: c.reports.labels(),
    ("reports", "response_times"): lambda c: c.reports.response_times(),
    ("reports", "sources"): lambda c: c.reports.sources(),
    ("reports", "teams"): lambda c: c.reports.teams(),
    ("reports", "themes"): lambda c: c.reports.themes(),
    ("reports", "theme_conversations"): lambda c: c.reports.theme_conversations("ID1"),
    ("reports", "voice"): lambda c: c.reports.voice(),
    # -- search --------------------------------------------------------
    ("search", "query"): lambda c: c.search.query("refund"),
    # -- tickets -------------------------------------------------------
    ("tickets", "list"): lambda c: c.tickets.list(),
    ("tickets", "comments"): lambda c: c.tickets.comments("ID1"),
    ("tickets", "for_conversation"): lambda c: c.tickets.for_conversation("CONV1"),
    ("tickets", "queues"): lambda c: c.tickets.queues(),
    ("tickets", "merge"): lambda c: c.tickets.merge("ID1", "ID2"),
    ("tickets", "split"): lambda c: c.tickets.split("ID1", "Spun off"),
    ("tickets", "bulk"): lambda c: c.tickets.bulk(["ID1"], "status", {"status": "open"}),
    ("tickets", "conversations"): lambda c: c.tickets.conversations("ID1"),
    ("tickets", "lineage"): lambda c: c.tickets.lineage("ID1"),
    ("tickets", "open_count"): lambda c: c.tickets.open_count("CONV1"),
    ("tickets", "status_history"): lambda c: c.tickets.status_history("ID1"),
    ("tickets", "time"): lambda c: c.tickets.time("ID1"),
    # -- triggers ------------------------------------------------------
    ("triggers", "list"): lambda c: c.triggers.list(),
    ("triggers", "create"): lambda c: c.triggers.create(
        name="Greet",
        event_type="conversation.created",
        enabled=True,
        conditions=[],
        actions=[{"type": "send_message", "params": {"body": "hi"}}],
    ),
    ("triggers", "delete"): lambda c: c.triggers.delete("ID1"),
    # -- visitors ------------------------------------------------------
    ("visitors", "start_conversation"): lambda c: c.visitors.start_conversation("CONT1"),
    # -- webhooks ------------------------------------------------------
    ("webhooks", "deliveries"): lambda c: c.webhooks.deliveries(),
    ("webhooks", "delivery"): lambda c: c.webhooks.delivery("ID1"),
    ("webhooks", "redeliver"): lambda c: c.webhooks.redeliver("ID1"),
    ("webhooks", "list"): lambda c: c.webhooks.list(),
    ("webhooks", "create"): lambda c: c.webhooks.create(
        url="https://hooks.example.com/chatly", event_types=["conversation.created"]
    ),
    ("webhooks", "events"): lambda c: c.webhooks.events(),
    ("webhooks", "schema_versions"): lambda c: c.webhooks.schema_versions(),
    ("webhooks", "delete"): lambda c: c.webhooks.delete("ID1"),
    ("webhooks", "set_schema_version"): lambda c: c.webhooks.set_schema_version(
        "ID1", "2026-10-14"
    ),
    # -- workspace -----------------------------------------------------
    ("workspace", "settings"): lambda c: c.workspace.settings(),
    ("workspace", "labels"): lambda c: c.workspace.labels(),
    ("workspace", "inboxes"): lambda c: c.workspace.inboxes(),
    ("workspace", "team_members"): lambda c: c.workspace.team_members("ID1"),
    ("workspace", "agent_skills"): lambda c: c.workspace.agent_skills(),
    ("workspace", "key_scopes"): lambda c: c.workspace.key_scopes(),
    ("workspace", "secrets"): lambda c: c.workspace.secrets(),
    ("workspace", "mine"): lambda c: c.workspace.mine(),
}

__all__ = ["CALLS"]
