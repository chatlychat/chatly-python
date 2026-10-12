"""Transport, query serialisation, the escape hatch, and the odd responses."""

from __future__ import annotations

import datetime as dt
import json
import unittest
from urllib.parse import urlsplit

import support
from support import build_client, error_response, json_response

import chatly
from chatly import (
    ChatlyClient,
    HTTPResponse,
    InvalidArgumentError,
    ResponseDecodeError,
)
from chatly._transport import build_query, encode_path


class QuerySerialisation(unittest.TestCase):
    def test_none_values_are_dropped(self) -> None:
        self.assertEqual(build_query({"cursor": None, "limit": 50}), "limit=50")
        self.assertEqual(build_query({}), "")
        self.assertEqual(build_query(None), "")
        self.assertEqual(build_query({"a": None}), "")

    def test_repeated_keys_stay_repeated(self) -> None:
        """Contract §2 — two parameters, not one comma-joined value."""
        self.assertEqual(
            build_query({"kinds": ["kb", "article"]}), "kinds=kb&kinds=article"
        )
        self.assertNotIn("%2C", build_query({"kinds": ["kb", "article"]}))

    def test_booleans_are_true_and_false_not_one_and_zero(self) -> None:
        self.assertEqual(build_query({"blocked": True}), "blocked=true")
        self.assertEqual(build_query({"blocked": False}), "blocked=false")

    def test_dates_are_iso(self) -> None:
        self.assertEqual(
            build_query({"from": dt.date(2026, 10, 12)}), "from=2026-10-12"
        )
        self.assertIn(
            "2026-10-12T09%3A30%3A00",
            build_query({"from": dt.datetime(2026, 10, 12, 9, 30, 0)}),
        )

    def test_a_dict_value_is_refused_rather_than_stringified(self) -> None:
        """``str(dict)`` on the wire is a parameter no server can read."""
        with self.assertRaises(InvalidArgumentError):
            build_query({"filter": {"status": "open"}})

    def test_values_are_percent_encoded(self) -> None:
        self.assertIn("q=caf%C3%A9+au+lait", build_query({"q": "café au lait"}))


class PathEncoding(unittest.TestCase):
    def test_a_segment_cannot_escape_the_path(self) -> None:
        self.assertEqual(encode_path("tags", "a/b"), "tags/a%2Fb")
        self.assertEqual(encode_path("x", "?a=1"), "x/%3Fa%3D1")
        self.assertEqual(encode_path("x", "..", "y"), "x/../y".replace("..", ".."))

    def test_an_empty_segment_is_refused(self) -> None:
        with self.assertRaises(InvalidArgumentError):
            encode_path("contacts", "")

    def test_a_tag_with_a_slash_hits_the_right_route(self) -> None:
        client, transport, _ = build_client()
        client.contacts.remove_tag("c1", "needs/review")
        self.assertEqual(
            urlsplit(transport.last.url).path, "/v1/contacts/c1/tags/needs%2Freview"
        )

    def test_a_slug_with_a_slash_hits_the_right_route(self) -> None:
        client, transport, _ = build_client()
        client.kb.article("guides/getting-started")
        self.assertEqual(
            urlsplit(transport.last.url).path,
            "/v1/kb/articles/guides%2Fgetting-started",
        )


class ResponseHandling(unittest.TestCase):
    def test_204_decodes_to_none(self) -> None:
        client, _, _ = build_client([HTTPResponse(status=204, headers={}, body=b"")])
        self.assertIsNone(client.macros.delete("m1"))

    def test_an_empty_200_body_decodes_to_none(self) -> None:
        client, _, _ = build_client([HTTPResponse(status=200, headers={}, body=b"  ")])
        self.assertIsNone(client.request("GET", "/v1/anything"))

    def test_a_non_json_2xx_body_raises_rather_than_returning_none(self) -> None:
        """A 200 that is not JSON means something else answered.

        Returning ``None`` for it sends the caller looking for a bug in their
        own code; a captive portal or a wrong base URL that happens to serve
        a 200 is the real cause.
        """
        client, _, _ = build_client(
            [HTTPResponse(status=200, headers={}, body=b"<html>hello</html>")]
        )
        with self.assertRaises(ResponseDecodeError) as caught:
            client.contacts.list()
        self.assertEqual(caught.exception.status, 200)
        self.assertIn("html", caught.exception.body)

    def test_a_201_is_a_success(self) -> None:
        client, _, _ = build_client([json_response({"id": "c1"}, status=201)])
        self.assertEqual(client.contacts.upsert(email="a@example.com")["id"], "c1")

    def test_response_headers_are_matched_case_insensitively(self) -> None:
        client, _, _ = build_client(
            [error_response(404, "not_found", "no", headers={"X-Request-Id": "REQ-9"})]
        )
        with self.assertRaises(chatly.NotFoundError) as caught:
            client.contacts.get("x")
        self.assertEqual(caught.exception.request_id, "REQ-9")


class ObjectShapeGuard(unittest.TestCase):
    """A method that promises one object says so when it gets something else.

    Nine key-accessible routes answer with a top-level array, and the API
    adds fields without a major version. A method typed ``-> JsonDict`` that
    simply cast the payload would hand a list to a caller doing
    ``result["id"]``, which fails three frames from the cause.
    """

    def test_a_list_where_an_object_was_promised_raises(self) -> None:
        client, _, _ = build_client([json_response([{"id": "a"}, {"id": "b"}])])
        with self.assertRaises(ResponseDecodeError) as caught:
            client.contacts.get("c1")
        self.assertIn("got list of 2", str(caught.exception))

    def test_a_null_where_an_object_was_promised_raises(self) -> None:
        client, _, _ = build_client([json_response(None)])
        with self.assertRaises(ResponseDecodeError) as caught:
            client.whoami()
        self.assertIn("null", str(caught.exception))

    def test_an_object_passes_through_unchanged(self) -> None:
        payload = {"id": "c1", "email": "a@example.com", "unknownFutureField": 1}
        client, _, _ = build_client([json_response(payload)])
        self.assertEqual(client.contacts.get("c1"), payload)


class EscapeHatch(unittest.TestCase):
    """Contract §8 — 85 key-accessible routes have no typed method."""

    def test_get_with_query(self) -> None:
        client, transport, _ = build_client([json_response({"skills": ["billing"]})])
        result = client.request("GET", "/v1/agents/skills", query={"team": "t1"})
        self.assertEqual(result["skills"], ["billing"])
        self.assertEqual(transport.last.method, "GET")
        self.assertEqual(urlsplit(transport.last.url).path, "/v1/agents/skills")
        self.assertEqual(urlsplit(transport.last.url).query, "team=t1")

    def test_a_write_through_the_hatch_gets_auth_and_idempotency(self) -> None:
        client, transport, _ = build_client()
        client.request("PUT", "/v1/api-keys/k1/machine-user", body={"userId": "u1"})
        request = transport.last
        self.assertEqual(request.headers["authorization"], "Bearer ck_test_key")
        self.assertIn("idempotency-key", request.headers)
        self.assertEqual(request.body, b'{"userId":"u1"}')

    def test_a_write_with_no_body_sends_an_empty_object(self) -> None:
        client, transport, _ = build_client()
        client.request("POST", "/v1/some/action")
        self.assertEqual(transport.last.body, b"{}")

    def test_a_delete_with_no_body_sends_nothing(self) -> None:
        client, transport, _ = build_client()
        client.request("DELETE", "/v1/some/thing")
        self.assertIsNone(transport.last.body)

    def test_errors_are_the_same_typed_ones(self) -> None:
        client, _, _ = build_client([error_response(403, "forbidden", "no scope")])
        with self.assertRaises(chatly.PermissionDeniedError):
            client.request("GET", "/v1/whatever")

    def test_retries_apply_to_the_hatch_too(self) -> None:
        client, transport, _ = build_client(
            [error_response(503, "unavailable", "no"), json_response({"ok": True})]
        )
        self.assertEqual(client.request("GET", "/v1/whatever")["ok"], True)
        self.assertEqual(transport.count, 2)

    def test_a_relative_path_is_refused(self) -> None:
        client, _, _ = build_client()
        with self.assertRaises(InvalidArgumentError):
            client.request("GET", "v1/contacts")

    def test_paginate_walks_an_untyped_route(self) -> None:
        client, _, _ = build_client(
            [json_response({"items": [{"id": "x"}], "nextCursor": "n2"})]
        )
        page = client.paginate("/v1/custom-objects", query={"limit": 1})
        self.assertEqual(page.next_cursor, "n2")
        self.assertEqual(len(page), 1)


class ConstructionAndConfig(unittest.TestCase):
    def test_a_bad_timeout_is_refused(self) -> None:
        for bad in (0, -1):
            with self.subTest(timeout=bad):
                with self.assertRaises(InvalidArgumentError):
                    ChatlyClient("ck_x", timeout=bad, transport=support.FakeTransport())

    def test_the_timeout_reaches_the_transport(self) -> None:
        client, transport, _ = build_client(timeout=2.5)
        client.contacts.list()
        self.assertEqual(transport.last.timeout, 2.5)

    def test_the_default_timeout_is_fifteen_seconds(self) -> None:
        client, transport, _ = build_client()
        client.contacts.list()
        self.assertEqual(transport.last.timeout, 15.0)

    def test_an_empty_api_url_is_refused(self) -> None:
        with self.assertRaises(InvalidArgumentError):
            ChatlyClient("ck_x", api_url="", transport=support.FakeTransport())


class NamespaceSpecifics(unittest.TestCase):
    """Behaviour this SDK implements because the route demands it."""

    def _query(self, transport) -> dict:
        from urllib.parse import parse_qsl

        return dict(parse_qsl(urlsplit(transport.last.url).query))

    def _raw_query(self, transport) -> str:
        return urlsplit(transport.last.url).query

    def test_search_sends_repeated_bare_kinds(self) -> None:
        """``kinds[]`` is silently dropped and a single ``kinds`` is a 400.

        The route parses ``z.array(z.enum(...))`` straight off the query with
        no preprocessing, so the bracketed key is an unknown field that gets
        stripped (200, unfiltered) and one bare value arrives as a string
        (400). Repeating it is the only spelling that works, which means a
        single kind must be sent twice.
        """
        client, transport, _ = build_client()
        client.search.query("refund", kinds=["kb", "ticket"])
        self.assertEqual(self._raw_query(transport), "q=refund&kinds=kb&kinds=ticket")
        self.assertNotIn("kinds%5B%5D", self._raw_query(transport))

        client, transport, _ = build_client()
        client.search.query("refund", kinds="kb")
        self.assertEqual(self._raw_query(transport), "q=refund&kinds=kb&kinds=kb")

    def test_search_kb_helper_narrows_to_articles(self) -> None:
        client, transport, _ = build_client()
        client.search.kb("refund policy")
        self.assertEqual(
            self._raw_query(transport), "q=refund+policy&kinds=kb&kinds=kb"
        )

    def test_an_unknown_search_kind_is_refused_locally(self) -> None:
        client, transport, _ = build_client()
        with self.assertRaises(InvalidArgumentError):
            client.search.query("x", kinds=["article"])
        self.assertEqual(transport.count, 0, "it should not cost a round-trip")

    def test_an_empty_search_q_is_refused_locally(self) -> None:
        client, transport, _ = build_client()
        with self.assertRaises(InvalidArgumentError):
            client.search.query("   ")
        self.assertEqual(transport.count, 0)

    def test_conversation_list_csv_params_are_comma_joined(self) -> None:
        """These four are CSV in one key, not repeated keys."""
        client, transport, _ = build_client()
        client.conversations.list(status=["open", "pending"], priority=["high"])
        params = self._query(transport)
        self.assertEqual(params["status"], "open,pending")
        self.assertEqual(params["priority"], "high")

    def test_conversation_list_from_is_sent_without_the_underscore(self) -> None:
        client, transport, _ = build_client()
        client.conversations.list(from_="2026-10-01T00:00:00Z", created_from="2026-09-01T00:00:00Z")
        params = self._query(transport)
        self.assertEqual(params["from"], "2026-10-01T00:00:00Z")
        self.assertEqual(params["createdFrom"], "2026-09-01T00:00:00Z")
        self.assertNotIn("from_", params)

    def test_conversation_list_false_flags_are_omitted(self) -> None:
        """The route reads anything but ``"true"`` as off, so ``false`` lies."""
        client, transport, _ = build_client()
        client.conversations.list(unread=False, mentioned=True)
        params = self._query(transport)
        self.assertNotIn("unread", params)
        self.assertEqual(params["mentioned"], "true")

    def test_the_iterator_translates_params_the_same_way(self) -> None:
        client, transport, _ = build_client(
            [json_response({"items": [], "nextCursor": None})]
        )
        list(client.conversations.iter_list(status=["open", "pending"], from_="2026-10-01T00:00:00Z"))
        params = self._query(transport)
        self.assertEqual(params["status"], "open,pending")
        self.assertEqual(params["from"], "2026-10-01T00:00:00Z")

    def test_labels_usage_is_sent_as_one_or_zero(self) -> None:
        client, transport, _ = build_client()
        client.workspace.labels(usage=True)
        self.assertEqual(self._query(transport)["usage"], "1")
        client.workspace.labels(usage=False)
        self.assertEqual(self._query(transport)["usage"], "0")
        client.workspace.labels()
        self.assertNotIn("usage", self._query(transport))

    def test_reports_sla_group_by_is_snake_case_on_the_wire(self) -> None:
        """The handler reads ``query.group_by`` only; ``groupBy`` is ignored."""
        client, transport, _ = build_client()
        client.reports.sla(group_by="week", from_="2026-09-01", to="2026-10-01")
        params = self._query(transport)
        self.assertEqual(params["group_by"], "week")
        self.assertNotIn("groupBy", params)
        self.assertEqual(params["from"], "2026-09-01")

    def test_billing_usage_requires_a_known_event_type(self) -> None:
        client, transport, _ = build_client()
        with self.assertRaises(InvalidArgumentError):
            client.billing.usage("messages.sent")
        self.assertEqual(transport.count, 0)
        client.billing.usage("ai.tokens")
        self.assertEqual(self._query(transport)["eventType"], "ai.tokens")

    def test_contacts_merge_sends_mergedid_and_tickets_merge_sends_loserid(self) -> None:
        """Same operation, two field names. Crossing them merges nothing."""
        client, transport, _ = build_client()
        client.contacts.merge("survivor", "absorbed")
        self.assertEqual(json.loads(transport.last.body), {"mergedId": "absorbed"})
        client.tickets.merge("winner", "loser")
        self.assertEqual(json.loads(transport.last.body), {"loserId": "loser"})

    def test_cancel_scheduled_has_no_conversation_in_the_path(self) -> None:
        client, transport, _ = build_client()
        client.conversations.cancel_scheduled("s1")
        self.assertEqual(
            urlsplit(transport.last.url).path, "/v1/conversations/scheduled-messages/s1"
        )

    def test_events_track_sends_the_event_at_the_top_level(self) -> None:
        client, transport, _ = build_client()
        client.events.track("c1", "trial_started", {"plan": "growth"})
        self.assertEqual(
            json.loads(transport.last.body),
            {"contactId": "c1", "name": "trial_started", "properties": {"plan": "growth"}},
        )

    def test_upsert_omits_unset_fields(self) -> None:
        """``None`` means "leave it alone", and that is unambiguous here.

        Every field on ``contactUpsertInputSchema`` is ``.optional()`` and
        none is ``.nullable()``, so ``null`` is a 400 and there is no
        clear-a-field operation for an omitted ``None`` to collide with.
        """
        client, transport, _ = build_client()
        client.contacts.upsert(email="a@example.com", name=None)
        self.assertEqual(json.loads(transport.last.body), {"email": "a@example.com"})

    def test_upsert_extra_reaches_the_server_untouched(self) -> None:
        """``extra`` is for a field added after this release, not for nulls."""
        client, transport, _ = build_client()
        client.contacts.upsert(email="a@example.com", **{"companyId": "co_1"})
        self.assertEqual(
            json.loads(transport.last.body),
            {"email": "a@example.com", "companyId": "co_1"},
        )

    def test_macros_update_passes_an_explicit_null_through(self) -> None:
        """Here a null is meaningful: omitted leaves the short code, null clears it.

        This is why ``update`` takes wire-named keyword arguments and filters
        nothing, while ``contacts.upsert`` takes snake_case ones and drops
        ``None``. The two routes mean different things by a null.
        """
        client, transport, _ = build_client()
        client.macros.update("m1", shortCode=None)
        self.assertEqual(json.loads(transport.last.body), {"shortCode": None})

    def test_tickets_split_can_create_an_unassigned_child(self) -> None:
        """``assigneeUserId`` is nullish there: omitted inherits, null unassigns."""
        client, transport, _ = build_client()
        client.tickets.split("t1", "Spun off", **{"assigneeUserId": None})
        self.assertEqual(
            json.loads(transport.last.body), {"title": "Spun off", "assigneeUserId": None}
        )

    def test_bare_array_routes_return_a_list(self) -> None:
        client, _, _ = build_client([json_response([{"id": "a"}, {"id": "b"}])])
        self.assertEqual(len(client.channels.list()), 2)

    def test_a_bare_array_route_returning_null_gives_an_empty_list(self) -> None:
        client, _, _ = build_client([HTTPResponse(status=204, headers={}, body=b"")])
        self.assertEqual(client.kb.collections(), [])

    def test_send_puts_the_conversation_in_the_path_not_the_body(self) -> None:
        client, transport, _ = build_client()
        client.conversations.send("c9", "hi", kind="note")
        self.assertEqual(
            urlsplit(transport.last.url).path, "/v1/conversations/c9/messages"
        )
        self.assertEqual(json.loads(transport.last.body), {"body": "hi", "kind": "note"})

    def test_tickets_filter_is_repeated_not_bracketed(self) -> None:
        client, transport, _ = build_client()
        client.tickets.list(filter=["status:eq:open", "priority:eq:high"])
        self.assertEqual(
            self._raw_query(transport),
            "filter=status%3Aeq%3Aopen&filter=priority%3Aeq%3Ahigh",
        )


if __name__ == "__main__":
    unittest.main()
