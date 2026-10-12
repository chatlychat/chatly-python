"""Every method in ``surface.json`` exists and calls the route it claims.

``scripts/check-sdk-surface-parity.mjs`` enforces that the *names* exist in
every SDK. This enforces the half a name check cannot see: that
``client.tickets.split(...)`` actually sends ``POST /v1/tickets/{id}/split``
and not a near-miss. Two of the bugs this guards against have shipped in
this repo — a method pointing at the wrong path, and a path assembled with
the right segments in the wrong order — and neither is visible to a gate
that only greps for identifiers.

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
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import support
from support import build_client

import chatly

#: Dummy values substituted for each ``{placeholder}`` in a spec path.
TOKENS = {
    "id": "ID1",
    "tag": "TAG1",
    "slug": "SLUG1",
    "conversation_id": "CONV1",
    "scheduled_id": "SCHED1",
}

#: The expected surface, embedded. ``(ns, name, http, path)``.
EMBEDDED: List[Tuple[str, str, str, str]] = [
    ("root", "whoami", "GET", "/v1/api-keys/whoami"),
    ("contacts", "list", "GET", "/v1/contacts"),
    ("contacts", "get", "GET", "/v1/contacts/{id}"),
    ("contacts", "upsert", "POST", "/v1/contacts"),
    ("contacts", "bulk_upsert", "POST", "/v1/contacts/bulk"),
    ("contacts", "merge", "POST", "/v1/contacts/{id}/merge"),
    ("contacts", "add_tags", "POST", "/v1/contacts/{id}/tags"),
    ("contacts", "remove_tag", "DELETE", "/v1/contacts/{id}/tags/{tag}"),
    ("contacts", "unsubscribe", "POST", "/v1/contacts/{id}/unsubscribe"),
    ("contacts", "journey", "GET", "/v1/contacts/{id}/journey"),
    ("conversations", "list", "GET", "/v1/conversations"),
    ("conversations", "get", "GET", "/v1/conversations/{id}"),
    ("conversations", "messages", "GET", "/v1/conversations/{id}/messages"),
    ("conversations", "send", "POST", "/v1/conversations/{id}/messages"),
    ("conversations", "unattended", "GET", "/v1/conversations/unattended"),
    ("conversations", "agent_handling", "GET", "/v1/conversations/{id}/agent-handling"),
    ("conversations", "set_agent_handling", "PUT", "/v1/conversations/{id}/agent-handling"),
    ("conversations", "generated_replies", "GET", "/v1/conversations/{id}/generated-replies"),
    ("conversations", "generate_reply", "POST", "/v1/conversations/{id}/generated-replies"),
    ("conversations", "scheduled_messages", "GET", "/v1/conversations/{id}/scheduled-messages"),
    ("conversations", "schedule_message", "POST", "/v1/conversations/{id}/scheduled-messages"),
    (
        "conversations",
        "cancel_scheduled",
        "DELETE",
        "/v1/conversations/scheduled-messages/{scheduled_id}",
    ),
    ("tickets", "list", "GET", "/v1/tickets"),
    ("tickets", "comments", "GET", "/v1/tickets/{id}/comments"),
    ("tickets", "for_conversation", "GET", "/v1/tickets/for-conversation/{conversation_id}"),
    ("tickets", "queues", "GET", "/v1/tickets/queues"),
    ("tickets", "merge", "POST", "/v1/tickets/{id}/merge"),
    ("tickets", "split", "POST", "/v1/tickets/{id}/split"),
    ("tickets", "bulk", "POST", "/v1/tickets/bulk"),
    ("macros", "list", "GET", "/v1/macros"),
    ("macros", "create", "POST", "/v1/macros"),
    ("macros", "update", "PATCH", "/v1/macros/{id}"),
    ("macros", "delete", "DELETE", "/v1/macros/{id}"),
    ("kb", "articles", "GET", "/v1/kb/articles"),
    ("kb", "article", "GET", "/v1/kb/articles/{slug}"),
    ("kb", "collections", "GET", "/v1/kb/collections"),
    ("search", "query", "GET", "/v1/search"),
    ("events", "track", "POST", "/v1/cdp/events"),
    ("events", "list", "GET", "/v1/cdp/events"),
    ("webhooks", "deliveries", "GET", "/v1/webhooks/deliveries"),
    ("webhooks", "delivery", "GET", "/v1/webhooks/deliveries/{id}"),
    ("webhooks", "redeliver", "POST", "/v1/webhooks/deliveries/{id}/redeliver"),
    ("reports", "overview", "GET", "/v1/reports/overview"),
    ("reports", "agents", "GET", "/v1/reports/agents"),
    ("reports", "conversations_by_day", "GET", "/v1/reports/conversations-by-day"),
    ("reports", "sla", "GET", "/v1/reports/sla"),
    ("channels", "list", "GET", "/v1/channels"),
    ("channels", "get", "GET", "/v1/channels/{id}"),
    ("billing", "plans", "GET", "/v1/billing/plans"),
    ("billing", "usage", "GET", "/v1/billing/usage"),
    ("workspace", "settings", "GET", "/v1/workspace/settings"),
    ("workspace", "labels", "GET", "/v1/labels"),
    ("workspace", "inboxes", "GET", "/v1/inboxes"),
    ("workspace", "team_members", "GET", "/v1/teams/{id}/members"),
    ("workspace", "agent_skills", "GET", "/v1/agents/skills"),
]

#: How to invoke each entry with throwaway arguments. One per surface entry.
CALLS: Dict[Tuple[str, str], Callable[[Any], Any]] = {
    ("root", "whoami"): lambda c: c.whoami(),
    ("contacts", "list"): lambda c: c.contacts.list(),
    ("contacts", "get"): lambda c: c.contacts.get("ID1"),
    ("contacts", "upsert"): lambda c: c.contacts.upsert(email="a@example.com"),
    ("contacts", "bulk_upsert"): lambda c: c.contacts.bulk_upsert([{"email": "a@example.com"}]),
    ("contacts", "merge"): lambda c: c.contacts.merge("ID1", "ID2"),
    ("contacts", "add_tags"): lambda c: c.contacts.add_tags("ID1", "vip"),
    ("contacts", "remove_tag"): lambda c: c.contacts.remove_tag("ID1", "TAG1"),
    ("contacts", "unsubscribe"): lambda c: c.contacts.unsubscribe("ID1"),
    ("contacts", "journey"): lambda c: c.contacts.journey("ID1"),
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
    ("tickets", "list"): lambda c: c.tickets.list(),
    ("tickets", "comments"): lambda c: c.tickets.comments("ID1"),
    ("tickets", "for_conversation"): lambda c: c.tickets.for_conversation("CONV1"),
    ("tickets", "queues"): lambda c: c.tickets.queues(),
    ("tickets", "merge"): lambda c: c.tickets.merge("ID1", "ID2"),
    ("tickets", "split"): lambda c: c.tickets.split("ID1", "Spun off"),
    ("tickets", "bulk"): lambda c: c.tickets.bulk(["ID1"], "status", {"status": "open"}),
    ("macros", "list"): lambda c: c.macros.list(),
    ("macros", "create"): lambda c: c.macros.create(name="Thanks", scope="workspace", body="ta"),
    ("macros", "update"): lambda c: c.macros.update("ID1", name="Thanks again"),
    ("macros", "delete"): lambda c: c.macros.delete("ID1"),
    ("kb", "articles"): lambda c: c.kb.articles(),
    ("kb", "article"): lambda c: c.kb.article("SLUG1"),
    ("kb", "collections"): lambda c: c.kb.collections(),
    ("search", "query"): lambda c: c.search.query("refund"),
    ("events", "track"): lambda c: c.events.track("ID1", "trial_started"),
    ("events", "list"): lambda c: c.events.list(),
    ("webhooks", "deliveries"): lambda c: c.webhooks.deliveries(),
    ("webhooks", "delivery"): lambda c: c.webhooks.delivery("ID1"),
    ("webhooks", "redeliver"): lambda c: c.webhooks.redeliver("ID1"),
    ("reports", "overview"): lambda c: c.reports.overview(),
    ("reports", "agents"): lambda c: c.reports.agents(),
    ("reports", "conversations_by_day"): lambda c: c.reports.conversations_by_day(),
    ("reports", "sla"): lambda c: c.reports.sla(),
    ("channels", "list"): lambda c: c.channels.list(),
    ("channels", "get"): lambda c: c.channels.get("ID1"),
    ("billing", "plans"): lambda c: c.billing.plans(),
    ("billing", "usage"): lambda c: c.billing.usage("ai.tokens"),
    ("workspace", "settings"): lambda c: c.workspace.settings(),
    ("workspace", "labels"): lambda c: c.workspace.labels(),
    ("workspace", "inboxes"): lambda c: c.workspace.inboxes(),
    ("workspace", "team_members"): lambda c: c.workspace.team_members("ID1"),
    ("workspace", "agent_skills"): lambda c: c.workspace.agent_skills(),
}

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
        self.assertGreaterEqual(len(EMBEDDED), 55)
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

    def test_every_paged_entry_has_an_auto_paginator(self) -> None:
        """Contract §5 — both forms, for every list the spec marks paged."""
        spec_entries = _load_spec()
        if spec_entries is None:
            self.skipTest("surface.json not present")
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        paged = [(e["ns"], e["name"]) for e in spec["entries"] if e.get("paged")]
        self.assertGreaterEqual(len(paged), 8, "the paged set shrank; is the spec parsed?")
        client, _, _ = build_client()
        for ns, name in paged:
            with self.subTest(method=f"{ns}.{name}"):
                namespace = getattr(client, ns)
                candidates = [f"iter_{name}", "iter_list" if name == "list" else f"iter_{name}"]
                found = [c for c in candidates if callable(getattr(namespace, c, None))]
                self.assertTrue(
                    found, f"{ns}.{name} is paged but has no iter_* generator"
                )

    def test_the_paginators_are_generators_not_lists(self) -> None:
        import types

        client, _, _ = build_client()
        for ns, name in (
            ("contacts", "iter_list"),
            ("conversations", "iter_list"),
            ("conversations", "iter_messages"),
            ("tickets", "iter_list"),
            ("macros", "iter_list"),
            ("kb", "iter_articles"),
            ("events", "iter_list"),
            ("webhooks", "iter_deliveries"),
            ("search", "iter_query"),
        ):
            with self.subTest(method=f"{ns}.{name}"):
                namespace = getattr(client, ns)
                method = getattr(namespace, name)
                result = method("ID1") if name == "iter_messages" else (
                    method("refund") if name == "iter_query" else method()
                )
                self.assertIsInstance(result, types.GeneratorType)


if __name__ == "__main__":
    unittest.main()
