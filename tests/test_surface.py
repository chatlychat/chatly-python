"""Every method in ``surface.json`` exists and calls the route it claims.

``scripts/check-sdk-surface-parity.mjs`` enforces that the *names* exist in
every SDK. This enforces the half a name check cannot see: that
``client.tickets.split(...)`` actually sends ``POST /v1/tickets/{id}/split``
and not a near-miss. Two of the bugs this guards against have shipped in
this repo — a method pointing at the wrong path, and a path assembled with
the right segments in the wrong order — and neither is visible to a gate
that only greps for identifiers.

The invocation table itself lives in :mod:`invocations`, which this module
and :mod:`test_surface_lock` share.

The expected table is built from ``packages/sdk-spec/surface.json`` when it
is present (it is, in the monorepo) and falls back to an embedded copy
otherwise, so the test still checks something from an extracted sdist. The
two are asserted to agree, and a floor on the count makes a table that
failed to load fail loudly instead of passing vacuously.
"""

from __future__ import annotations

import json
import pathlib
import unittest
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import support
from invocations import CALLS
from support import build_client

import chatly

#: Dummy values substituted for each ``{placeholder}`` in a spec path.
TOKENS = {
    "id": "ID1",
    "tag": "TAG1",
    "slug": "SLUG1",
    "conversation_id": "CONV1",
    "conversationId": "CONV1",
    "contactId": "CONT1",
    "messageId": "MSG1",
    "deliveryId": "DEL1",
    "provider": "openai",
    # A real overridable kind: `EmailTemplates` checks the value locally, so
    # a placeholder like "KIND1" would raise before a request was issued and
    # the route would go unexercised.
    "kind": "workspace_invite",
    "scheduled_id": "SCHED1",
}

#: The expected surface, embedded. ``(ns, name, http, path)``.
EMBEDDED: List[Tuple[str, str, str, str]] = [
    ("ai", "add_provider", "POST", "/v1/ai-providers"),
    ("ai", "create_tool", "POST", "/v1/ai/tools"),
    ("ai", "delete_tool", "DELETE", "/v1/ai/tools/{id}"),
    ("ai", "generate_tone", "POST", "/v1/ai/tone/generate"),
    ("ai", "providers", "GET", "/v1/ai-providers"),
    ("ai", "quota", "GET", "/v1/ai/quota"),
    ("ai", "set_tone", "PUT", "/v1/ai/tone"),
    ("ai", "test_provider", "POST", "/v1/ai-providers/{provider}/test"),
    ("ai", "tone", "GET", "/v1/ai/tone"),
    ("ai", "tone_preview", "GET", "/v1/ai/tone/preview"),
    ("ai", "tools", "GET", "/v1/ai/tools"),
    ("ai", "update_tool", "PATCH", "/v1/ai/tools/{id}"),
    ("billing", "invoices", "GET", "/v1/billing/invoices"),
    ("billing", "plans", "GET", "/v1/billing/plans"),
    ("billing", "summary", "GET", "/v1/billing"),
    ("billing", "usage", "GET", "/v1/billing/usage"),
    ("billing", "usage_daily", "GET", "/v1/billing/usage/daily"),
    ("billing", "usage_monthly", "GET", "/v1/billing/usage/monthly"),
    ("bot_routes", "create", "POST", "/v1/bot-routes"),
    ("bot_routes", "delete", "DELETE", "/v1/bot-routes/{id}"),
    ("bot_routes", "fields", "GET", "/v1/bot-routes/fields"),
    ("bot_routes", "list", "GET", "/v1/bot-routes"),
    ("bot_routes", "resolve", "POST", "/v1/bot-routes/resolve"),
    ("bot_routes", "update", "PATCH", "/v1/bot-routes/{id}"),
    ("bots", "analytics", "GET", "/v1/bots/{id}/analytics"),
    ("bots", "create", "POST", "/v1/bots"),
    ("bots", "deliveries", "GET", "/v1/bots/{id}/deliveries"),
    ("bots", "delivery", "GET", "/v1/bots/{id}/deliveries/{deliveryId}"),
    ("bots", "get", "GET", "/v1/bots/{id}"),
    ("bots", "list", "GET", "/v1/bots"),
    ("bots", "redeliver", "POST", "/v1/bots/{id}/deliveries/{deliveryId}/redeliver"),
    ("bots", "rotate_external_secret", "POST", "/v1/bots/{id}/external/rotate-secret"),
    ("bots", "test_delivery", "POST", "/v1/bots/{id}/test-delivery"),
    ("bots", "update", "PATCH", "/v1/bots/{id}"),
    ("bots", "update_external", "PATCH", "/v1/bots/{id}/external"),
    ("brands", "create", "POST", "/v1/brands"),
    ("brands", "delete", "DELETE", "/v1/brands/{id}"),
    ("brands", "list", "GET", "/v1/brands"),
    ("brands", "update", "PATCH", "/v1/brands/{id}"),
    ("canvas_steps", "get", "GET", "/v1/canvas-steps/{id}"),
    ("canvas_steps", "resolve", "POST", "/v1/canvas-steps/{id}/resolve"),
    ("channels", "adapters", "GET", "/v1/channels/adapters"),
    ("channels", "create", "POST", "/v1/channels"),
    ("channels", "get", "GET", "/v1/channels/{id}"),
    ("channels", "list", "GET", "/v1/channels"),
    ("channels", "rotate_secret", "POST", "/v1/channels/{id}/secret/rotate"),
    ("channels", "update", "PATCH", "/v1/channels/{id}"),
    ("contacts", "add_tags", "POST", "/v1/contacts/{id}/tags"),
    ("contacts", "bulk_upsert", "POST", "/v1/contacts/bulk"),
    ("contacts", "cards", "POST", "/v1/contacts/{contactId}/cards"),
    ("contacts", "get", "GET", "/v1/contacts/{id}"),
    ("contacts", "journey", "GET", "/v1/contacts/{id}/journey"),
    ("contacts", "list", "GET", "/v1/contacts"),
    ("contacts", "merge", "POST", "/v1/contacts/{id}/merge"),
    ("contacts", "mood", "GET", "/v1/contacts/{id}/mood"),
    ("contacts", "remove_tag", "DELETE", "/v1/contacts/{id}/tags/{tag}"),
    ("contacts", "unsubscribe", "POST", "/v1/contacts/{id}/unsubscribe"),
    ("contacts", "upsert", "POST", "/v1/contacts"),
    ("conversations", "agent_handling", "GET", "/v1/conversations/{id}/agent-handling"),
    ("conversations", "cancel_scheduled", "DELETE", "/v1/conversations/scheduled-messages/{scheduled_id}"),
    ("conversations", "generate_reply", "POST", "/v1/conversations/{id}/generated-replies"),
    ("conversations", "generated_replies", "GET", "/v1/conversations/{id}/generated-replies"),
    ("conversations", "get", "GET", "/v1/conversations/{id}"),
    ("conversations", "linked", "GET", "/v1/conversations/{id}/linked"),
    ("conversations", "list", "GET", "/v1/conversations"),
    ("conversations", "messages", "GET", "/v1/conversations/{id}/messages"),
    ("conversations", "outcomes", "GET", "/v1/conversations/{id}/outcomes"),
    ("conversations", "record_outcome", "POST", "/v1/conversations/{id}/outcomes"),
    ("conversations", "return_to_bot", "POST", "/v1/conversations/{id}/return-to-bot"),
    ("conversations", "schedule_message", "POST", "/v1/conversations/{id}/scheduled-messages"),
    ("conversations", "scheduled_messages", "GET", "/v1/conversations/{id}/scheduled-messages"),
    ("conversations", "send", "POST", "/v1/conversations/{id}/messages"),
    ("conversations", "set_agent_handling", "PUT", "/v1/conversations/{id}/agent-handling"),
    ("conversations", "unattended", "GET", "/v1/conversations/unattended"),
    ("conversations", "unread_counts", "GET", "/v1/conversations/unread-counts"),
    ("conversations", "update_blocks", "PATCH", "/v1/conversations/{id}/messages/{messageId}/blocks"),
    ("customer_card_endpoints", "activate_secret", "POST", "/v1/customer-card-endpoints/{id}/activate-secret"),
    ("customer_card_endpoints", "create", "POST", "/v1/customer-card-endpoints"),
    ("customer_card_endpoints", "delete", "DELETE", "/v1/customer-card-endpoints/{id}"),
    ("customer_card_endpoints", "list", "GET", "/v1/customer-card-endpoints"),
    ("customer_card_endpoints", "rotate_secret", "POST", "/v1/customer-card-endpoints/{id}/rotate-secret"),
    ("customer_cards", "create", "POST", "/v1/customer-cards"),
    ("customer_cards", "delete", "DELETE", "/v1/customer-cards/{id}"),
    ("customer_cards", "list", "GET", "/v1/customer-cards"),
    ("customer_cards", "rotate_secret", "POST", "/v1/customer-cards/{id}/rotate-secret"),
    ("customer_cards", "update", "PATCH", "/v1/customer-cards/{id}"),
    ("docs_sources", "create", "POST", "/v1/docs-sources"),
    ("docs_sources", "delete", "DELETE", "/v1/docs-sources/{id}"),
    ("docs_sources", "discover", "POST", "/v1/docs-sources/discover"),
    ("docs_sources", "list", "GET", "/v1/docs-sources"),
    ("docs_sources", "providers", "GET", "/v1/docs-sources/providers"),
    ("docs_sources", "sync", "POST", "/v1/docs-sources/{id}/sync"),
    ("docs_sources", "update", "PATCH", "/v1/docs-sources/{id}"),
    ("docs_sources", "webhook", "POST", "/v1/docs-sources/{id}/webhook"),
    ("email_templates", "delete", "DELETE", "/v1/email-templates/{kind}"),
    ("email_templates", "list", "GET", "/v1/email-templates"),
    ("email_templates", "preview", "POST", "/v1/email-templates/preview"),
    ("email_templates", "update", "PUT", "/v1/email-templates/{kind}"),
    ("events", "list", "GET", "/v1/cdp/events"),
    ("events", "track", "POST", "/v1/cdp/events"),
    ("kb", "article", "GET", "/v1/kb/articles/{slug}"),
    ("kb", "articles", "GET", "/v1/kb/articles"),
    ("kb", "collections", "GET", "/v1/kb/collections"),
    ("knowledge_gaps", "draft", "POST", "/v1/knowledge-gaps/{id}/draft"),
    ("knowledge_gaps", "list", "GET", "/v1/knowledge-gaps"),
    ("knowledge_gaps", "update", "PATCH", "/v1/knowledge-gaps/{id}"),
    ("macros", "actions", "GET", "/v1/macros/actions"),
    ("macros", "create", "POST", "/v1/macros"),
    ("macros", "delete", "DELETE", "/v1/macros/{id}"),
    ("macros", "get", "GET", "/v1/macros/{id}"),
    ("macros", "list", "GET", "/v1/macros"),
    ("macros", "template", "GET", "/v1/macros/templates/{slug}"),
    ("macros", "templates", "GET", "/v1/macros/templates"),
    ("macros", "update", "PATCH", "/v1/macros/{id}"),
    ("reports", "agents", "GET", "/v1/reports/agents"),
    ("reports", "attribution", "GET", "/v1/reports/attribution"),
    ("reports", "cohorts", "GET", "/v1/reports/cohorts"),
    ("reports", "conversations_by_day", "GET", "/v1/reports/conversations-by-day"),
    ("reports", "labels", "GET", "/v1/reports/labels"),
    ("reports", "overview", "GET", "/v1/reports/overview"),
    ("reports", "response_times", "GET", "/v1/reports/response-times"),
    ("reports", "sla", "GET", "/v1/reports/sla"),
    ("reports", "sources", "GET", "/v1/reports/sources"),
    ("reports", "teams", "GET", "/v1/reports/teams"),
    ("reports", "theme_conversations", "GET", "/v1/reports/themes/{id}/conversations"),
    ("reports", "themes", "GET", "/v1/reports/themes"),
    ("reports", "voice", "GET", "/v1/reports/voice"),
    ("root", "me", "GET", "/v1/me"),
    ("root", "whoami", "GET", "/v1/api-keys/whoami"),
    ("search", "query", "GET", "/v1/search"),
    ("tickets", "bulk", "POST", "/v1/tickets/bulk"),
    ("tickets", "comments", "GET", "/v1/tickets/{id}/comments"),
    ("tickets", "conversations", "GET", "/v1/tickets/{id}/conversations"),
    ("tickets", "for_conversation", "GET", "/v1/tickets/for-conversation/{conversation_id}"),
    ("tickets", "lineage", "GET", "/v1/tickets/{id}/lineage"),
    ("tickets", "list", "GET", "/v1/tickets"),
    ("tickets", "merge", "POST", "/v1/tickets/{id}/merge"),
    ("tickets", "open_count", "GET", "/v1/tickets/open-count/{conversationId}"),
    ("tickets", "queues", "GET", "/v1/tickets/queues"),
    ("tickets", "split", "POST", "/v1/tickets/{id}/split"),
    ("tickets", "status_history", "GET", "/v1/tickets/{id}/status-history"),
    ("tickets", "time", "GET", "/v1/tickets/{id}/time"),
    ("triggers", "create", "POST", "/v1/triggers"),
    ("triggers", "delete", "DELETE", "/v1/triggers/{id}"),
    ("triggers", "list", "GET", "/v1/triggers"),
    ("webhooks", "create", "POST", "/v1/webhooks"),
    ("webhooks", "delete", "DELETE", "/v1/webhooks/{id}"),
    ("webhooks", "deliveries", "GET", "/v1/webhooks/deliveries"),
    ("webhooks", "delivery", "GET", "/v1/webhooks/deliveries/{id}"),
    ("webhooks", "events", "GET", "/v1/webhooks/events"),
    ("webhooks", "list", "GET", "/v1/webhooks"),
    ("webhooks", "redeliver", "POST", "/v1/webhooks/deliveries/{id}/redeliver"),
    ("webhooks", "schema_versions", "GET", "/v1/webhooks/schema-versions"),
    ("webhooks", "set_schema_version", "PATCH", "/v1/webhooks/{id}/schema-version"),
    ("workspace", "agent_skills", "GET", "/v1/agents/skills"),
    ("workspace", "inboxes", "GET", "/v1/inboxes"),
    ("workspace", "key_scopes", "GET", "/v1/api-keys/scopes"),
    ("workspace", "labels", "GET", "/v1/labels"),
    ("workspace", "mine", "GET", "/v1/workspaces/me"),
    ("workspace", "secrets", "GET", "/v1/workspace/secrets"),
    ("workspace", "settings", "GET", "/v1/workspace/settings"),
    ("workspace", "team_members", "GET", "/v1/teams/{id}/members"),
]

def _find_spec() -> pathlib.Path:
    """The manifest, in the monorepo or in a public mirror.

    `packages/sdk-spec/surface.json` in the monorepo. A mirror has no
    `packages/` above it, so `scripts/sync-sdk-repos.mjs` vendors the manifest
    at `<repo>/sdk-spec/` and this looks there too. Without the second
    candidate every surface test SKIPPED in every mirror, and the Python
    mirror reported `OK (skipped=8)` — a pass for assertions it never ran.

    Falling back to the monorepo path when neither exists keeps the failure
    message pointing at the canonical location.
    """
    package = pathlib.Path(__file__).resolve().parents[1]
    for candidate in (package.parent / "sdk-spec", package / "sdk-spec"):
        path = candidate / "surface.json"
        if path.exists():
            return path
    return package.parent / "sdk-spec" / "surface.json"


SPEC_PATH = _find_spec()


def _load_spec() -> Optional[List[Tuple[str, str, str, str]]]:
    if not SPEC_PATH.exists():
        return None
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return [(e["ns"], e["name"], e["http"], e["path"]) for e in spec["entries"]]


def _expected_path(spec_path: str) -> str:
    out = spec_path
    for name, token in TOKENS.items():
        out = out.replace("{" + name + "}", token)
    return out


class SurfaceParity(unittest.TestCase):
    def test_the_embedded_table_matches_the_spec_file(self) -> None:
        spec = _load_spec()
        if spec is None:
            self.skipTest(f"{SPEC_PATH} not present (running outside the monorepo)")
        self.assertEqual(
            sorted(spec), sorted(EMBEDDED), "surface.json and the embedded table disagree"
        )

    def test_the_table_is_not_empty_and_meets_the_floor(self) -> None:
        """A table that failed to load must fail, not pass vacuously."""
        # 162, the whole key-accessible typed surface. The floor exists so
        # that a manifest which stops parsing fails loudly instead of
        # shrinking the audited set; it has only ever moved up.
        self.assertGreaterEqual(len(EMBEDDED), 162)
        self.assertEqual(len(EMBEDDED), len(set(EMBEDDED)), "duplicate entries")
        self.assertEqual(
            len(CALLS), len(EMBEDDED), "every surface entry needs exactly one invocation"
        )

    def test_every_entry_has_an_invocation(self) -> None:
        missing = [(ns, name) for ns, name, _, _ in EMBEDDED if (ns, name) not in CALLS]
        self.assertEqual(missing, [])
        extra = [key for key in CALLS if key not in {(ns, n) for ns, n, _, _ in EMBEDDED}]
        self.assertEqual(extra, [], "an invocation with no surface entry")

    def test_every_method_exists_with_the_spec_name(self) -> None:
        client, _, _ = build_client()
        for ns, name, _, _ in EMBEDDED:
            with self.subTest(method=f"{ns}.{name}"):
                owner = client if ns == "root" else getattr(client, ns, None)
                self.assertIsNotNone(owner, f"no namespace '{ns}' on the client")
                self.assertTrue(
                    callable(getattr(owner, name, None)),
                    f"{ns}.{name} is missing or not callable",
                )

    def test_every_method_sends_the_verb_and_path_it_claims(self) -> None:
        for ns, name, verb, spec_path in EMBEDDED:
            with self.subTest(method=f"{ns}.{name}"):
                client, transport, _ = build_client()
                CALLS[(ns, name)](client)
                self.assertEqual(transport.count, 1, "expected exactly one request")
                request = transport.last
                self.assertEqual(request.method, verb, f"{ns}.{name} used the wrong verb")
                self.assertEqual(
                    urlsplit(request.url).path,
                    _expected_path(spec_path),
                    f"{ns}.{name} called the wrong path",
                )

    def test_the_namespaces_are_exactly_what_the_spec_groups(self) -> None:
        """No namespace invented, none forgotten.

        Read off the instance rather than the class: namespaces are wired in
        ``_wire``, which is also the path ``with_idempotency_key`` takes, so
        this doubles as a check that the derived-client path builds the same
        set.
        """
        expected = {ns for ns, _, _, _ in EMBEDDED} - {"root"}
        client, _, _ = build_client()
        self.assertEqual({n for n in vars(client) if not n.startswith("_")}, expected)
        derived = client.with_idempotency_key()
        self.assertEqual({n for n in vars(derived) if not n.startswith("_")}, expected)

    def test_walkers_match_the_manifests_paged_flag_in_BOTH_directions(self) -> None:
        """Every ``paged`` entry has a walker, and nothing else does.

        Driven entirely off the manifest, which is the point. The Node SDK had
        no ``messagesAll`` for months: ``conversations.messages`` had been
        flagged ``paged`` since the manifest was written and nothing connected
        the flag to the SDK's paginators, so the omission just sat there. A
        one-directional check would also have let this SDK keep
        ``macros.iter_list`` after that route turned out to be
        pagination-exempt — a walker advertising a cursor the route does not
        have.

        The mapping is mechanical: a paged entry ``(ns, name)`` must be
        matched by ``client.<ns>.iter_<name>``. Keeping it mechanical is what
        stops this test from becoming a second hand-maintained list that can
        drift the same way the first one did.
        """
        spec_entries = _load_spec()
        if spec_entries is None:
            self.skipTest("surface.json not present")
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

        expected: Dict[str, set] = {}
        for entry in spec["entries"]:
            namespace = entry["ns"]
            expected.setdefault(namespace, set())
            if entry.get("paged"):
                expected[namespace].add(f"iter_{entry['name']}")

        total_expected = sum(len(v) for v in expected.values())
        # Floor, and the history of why it has moved. 8, then 7, then 10,
        # now 13.
        #
        #   8 -> 7   `macros.list` came out: `GET /v1/macros` is
        #            `@PaginationExempt` and answers with a bare array capped
        #            at 200 by usage rank, so there was never a cursor.
        #   7 -> 10  `contacts.journey`, `conversations.unattended` and
        #            `search.query` went in: all three return
        #            `{ items, nextCursor }` and had never been flagged.
        #   10 -> 13 `bots.list`, `bots.deliveries` and `triggers.list` went
        #            in with the rest of the surface. All three are built by
        #            the API's shared `buildPaginatedResponse`, so they carry
        #            `hasMore` beside the cursor — read off the handlers,
        #            which is also how the manifest's own `$shapeMeans`
        #            prose was found to undercount the `hasMore` routes at
        #            four when there are six.
        #
        # Both moves were made on evidence read out of the handlers, not from
        # this file. The floor stays so that a manifest which silently stops
        # parsing fails loudly instead of shrinking the audited set to zero —
        # if this number drops again, check that the spec parses BEFORE you
        # conclude a route legitimately stopped paging.
        self.assertGreaterEqual(
            total_expected,
            13,
            "the paged set shrank below the floor; confirm surface.json parsed "
            "before concluding a route legitimately stopped paging",
        )

        client, _, _ = build_client()
        for namespace, want in sorted(expected.items()):
            with self.subTest(namespace=namespace):
                # `root` is the pseudo-namespace for methods on the client
                # itself (`whoami`), matching surface.json's own grouping.
                owner = client if namespace == "root" else getattr(client, namespace, None)
                self.assertIsNotNone(owner, f"no namespace '{namespace}'")
                got = {name for name in dir(owner) if name.startswith("iter_")}
                self.assertEqual(
                    got,
                    want,
                    f"client.{namespace}: walkers {sorted(got)} but the manifest's "
                    f"paged entries imply {sorted(want)}",
                )

    def test_every_walker_is_a_lazy_generator(self) -> None:
        """A walker must be a generator, not a list built up front.

        Derived from the manifest for the same reason as the test above, and
        checked by calling it: constructing the generator must issue no
        request at all.
        """
        import types

        spec_entries = _load_spec()
        if spec_entries is None:
            self.skipTest("surface.json not present")
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

        # Throwaway positional arguments for the walkers that need one.
        positional = {
            ("conversations", "iter_messages"): ("ID1",),
            ("contacts", "iter_journey"): ("ID1",),
            ("search", "iter_query"): ("refund",),
            ("bots", "iter_deliveries"): ("ID1",),
        }

        checked = 0
        for entry in spec["entries"]:
            if not entry.get("paged"):
                continue
            ns_name, walker = entry["ns"], f"iter_{entry['name']}"
            with self.subTest(method=f"{ns_name}.{walker}"):
                client, transport, _ = build_client()
                method = getattr(getattr(client, ns_name), walker)
                result = method(*positional.get((ns_name, walker), ()))
                self.assertIsInstance(result, types.GeneratorType)
                self.assertEqual(
                    transport.count,
                    0,
                    f"{ns_name}.{walker} made a request before it was iterated",
                )
                checked += 1
        self.assertGreaterEqual(checked, 13, "the walk-check examined too few entries")


if __name__ == "__main__":
    unittest.main()
