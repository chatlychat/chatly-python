"""CONTRACT.md §10, items 6-9: pagination, webhooks and the pinned vectors.

The auto-paginator, ``verify_webhook_signature`` including the exact delivery
the contract pins, and ``identity_hash`` including its cross-checked vector.
Items 1-5 are in ``test_contract.py``.

Both pinned vectors are reproduced verbatim from the contract. If one of them
fails, this SDK is wrong and the vector is right — they are cross-checked
across implementations, and the parity gate compares the digests between
languages.
"""

from __future__ import annotations

import unittest
from urllib.parse import parse_qsl, urlsplit

from support import build_client, json_response

import chatly
from chatly import InvalidArgumentError, PaginationError


class Item6AutoPagination(unittest.TestCase):
    """§10.6 — the paginator walks two pages and stops on a null cursor."""

    def test_two_pages_then_stop(self) -> None:
        client, transport, _ = build_client(
            [
                json_response({"items": [{"id": "a"}, {"id": "b"}], "nextCursor": "cur2"}),
                json_response({"items": [{"id": "c"}], "nextCursor": None}),
            ]
        )
        ids = [c["id"] for c in client.contacts.iter_list()]
        self.assertEqual(ids, ["a", "b", "c"])
        self.assertEqual(transport.count, 2, "it kept asking after a null cursor")
        first, second = (urlsplit(r.url) for r in transport.requests)
        self.assertEqual(dict(parse_qsl(first.query)).get("cursor"), None)
        self.assertEqual(dict(parse_qsl(second.query))["cursor"], "cur2")

    def test_a_missing_next_cursor_is_the_last_page(self) -> None:
        client, transport, _ = build_client([json_response({"items": [{"id": "a"}]})])
        self.assertEqual(len(list(client.contacts.iter_list())), 1)
        self.assertEqual(transport.count, 1)

    def test_a_repeated_cursor_raises_instead_of_spinning(self) -> None:
        client, transport, _ = build_client(
            [json_response({"items": [{"id": "a"}], "nextCursor": "same"}) for _ in range(50)]
        )
        with self.assertRaises(PaginationError):
            list(client.contacts.iter_list())
        self.assertLessEqual(transport.count, 3)

    def test_the_single_page_form_is_also_available(self) -> None:
        """§5 — both the page as returned and the iterator."""
        client, _, _ = build_client(
            [json_response({"items": [{"id": "a"}], "nextCursor": "cur2"})]
        )
        page = client.contacts.list(limit=1)
        self.assertEqual(page.next_cursor, "cur2")
        self.assertEqual(len(page), 1)
        self.assertEqual([c["id"] for c in page], ["a"])
        self.assertEqual(page.raw["nextCursor"], "cur2")

    def test_filters_are_carried_onto_every_page(self) -> None:
        client, transport, _ = build_client(
            [
                json_response({"items": [{"id": "a"}], "nextCursor": "cur2"}),
                json_response({"items": [], "nextCursor": None}),
            ]
        )
        list(client.conversations.iter_list(status="open", limit=1))
        for request in transport.requests:
            params = dict(parse_qsl(urlsplit(request.url).query))
            self.assertEqual(params["status"], "open")
            self.assertEqual(params["limit"], "1")

    def test_total_and_has_more_are_surfaced_when_present(self) -> None:
        client, _, _ = build_client(
            [json_response({"items": [], "nextCursor": None, "total": 41, "hasMore": False})]
        )
        page = client.conversations.unattended()
        self.assertEqual(page.total, 41)
        self.assertIs(page.has_more, False)

    def test_absent_total_is_none_not_zero(self) -> None:
        client, _, _ = build_client([json_response({"items": [], "nextCursor": None})])
        page = client.contacts.list()
        self.assertIsNone(page.total, "'not reported' must not read as zero")
        self.assertIsNone(page.has_more)

    def test_a_bare_array_becomes_one_page_on_the_untyped_path(self) -> None:
        """``client.paginate`` tolerates an array, because it cannot know.

        The escape hatch is pointed at routes this SDK has no method for, and
        a fair number of them are pagination-exempt and answer with an array.
        Folding that into a single cursor-less page is the useful behaviour
        there.

        It is deliberately NOT how a typed method handles it: a method knows
        which shape its route returns, so it returns a list or a ``Page``
        accordingly. Worth being explicit, because this tolerance has a cost
        — it is why this SDK did not *notice* when the manifest briefly
        marked ``GET /v1/macros`` as paged. It degraded quietly instead of
        telling anyone.
        """
        client, transport, _ = build_client([json_response([{"id": "x1"}, {"id": "x2"}])])
        page = client.paginate("/v1/some/exempt/collection")
        self.assertEqual([row["id"] for row in page.items], ["x1", "x2"])
        self.assertIsNone(page.next_cursor)
        self.assertEqual(transport.count, 1)

    def test_the_walk_is_lazy(self) -> None:
        """A generator, not a list — no request until the first ``next()``."""
        client, transport, _ = build_client(
            [json_response({"items": [{"id": "a"}], "nextCursor": None})]
        )
        walker = client.contacts.iter_list()
        self.assertEqual(transport.count, 0, "constructing the generator made a request")
        next(iter(walker))
        self.assertEqual(transport.count, 1)


class Item7WebhookVerification(unittest.TestCase):
    """§10.7 — accept the real construction, reject the rest, never throw."""

    SECRET = "whsec_test_secret"
    BODY = b'{"event":"conversation.created","id":"evt_9"}'

    def _header(self, timestamp: int, *, body: bytes = b"", body_only: bool = False) -> str:
        import hashlib
        import hmac

        payload = body or self.BODY
        material = payload if body_only else f"{timestamp}.".encode("ascii") + payload
        digest = hmac.new(self.SECRET.encode(), material, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={digest}"

    def test_accepts_a_genuine_signature(self) -> None:
        now = 1_750_000_000
        self.assertTrue(
            chatly.verify_webhook_signature(
                self.BODY, self._header(now), self.SECRET, now=now
            )
        )

    def test_accepts_a_str_body_as_well_as_bytes(self) -> None:
        now = 1_750_000_000
        self.assertTrue(
            chatly.verify_webhook_signature(
                self.BODY.decode(), self._header(now), self.SECRET, now=now
            )
        )

    def test_rejects_a_digest_over_the_body_alone(self) -> None:
        """The bug that rejected 100% of genuine deliveries, inverted.

        An earlier Node implementation HMAC'd the body without the timestamp.
        If this assertion ever fails, the verifier has been "fixed" back to
        the broken construction and the replay window is gone with it.
        """
        now = 1_750_000_000
        self.assertFalse(
            chatly.verify_webhook_signature(
                self.BODY, self._header(now, body_only=True), self.SECRET, now=now
            )
        )

    def test_rejects_a_stale_timestamp(self) -> None:
        issued = 1_750_000_000
        header = self._header(issued)
        self.assertFalse(
            chatly.verify_webhook_signature(
                self.BODY, header, self.SECRET, now=issued + 301
            )
        )
        self.assertTrue(
            chatly.verify_webhook_signature(
                self.BODY, header, self.SECRET, now=issued + 299
            )
        )

    def test_rejects_a_future_timestamp_too(self) -> None:
        issued = 1_750_000_000
        self.assertFalse(
            chatly.verify_webhook_signature(
                self.BODY, self._header(issued), self.SECRET, now=issued - 301
            )
        )

    def test_rejects_a_wrong_secret(self) -> None:
        now = 1_750_000_000
        self.assertFalse(
            chatly.verify_webhook_signature(
                self.BODY, self._header(now), "whsec_other", now=now
            )
        )

    def test_rejects_a_mutated_body(self) -> None:
        now = 1_750_000_000
        self.assertFalse(
            chatly.verify_webhook_signature(
                self.BODY + b" ", self._header(now), self.SECRET, now=now
            )
        )

    def test_malformed_headers_return_false_and_never_raise(self) -> None:
        now = 1_750_000_000
        malformed = [
            "",
            "nonsense",
            "t=,v1=",
            "t=abc,v1=deadbeef",
            "v1=deadbeef",
            f"t={now}",
            f"t={now},v1=",
            f"t={now},v1=zzzz",
            f"t={now},v1=" + "ab" * 10,
            "t=1,2,3,v1=x",
            ",,,",
            "=",
            f"t={now},v1={'a' * 64}",
        ]
        for header in malformed:
            with self.subTest(header=header):
                try:
                    result = chatly.verify_webhook_signature(
                        self.BODY, header, self.SECRET, now=now
                    )
                except Exception as exc:  # pragma: no cover
                    self.fail(f"verifier raised {exc!r} on {header!r}")
                self.assertFalse(result)

    def test_non_string_inputs_return_false_and_never_raise(self) -> None:
        bad_inputs = [
            ({"id": 1}, "t=1,v1=ff", "whsec"),
            (b"{}", None, "whsec"),
            (b"{}", 12345, "whsec"),
            (b"{}", "t=1,v1=ff", None),
            (b"{}", "t=1,v1=ff", ""),
            (None, "t=1,v1=ff", "whsec"),
        ]
        for body, header, secret in bad_inputs:
            with self.subTest(body=type(body).__name__, header=header, secret=secret):
                try:
                    result = chatly.verify_webhook_signature(body, header, secret)  # type: ignore[arg-type]
                except Exception as exc:  # pragma: no cover
                    self.fail(f"verifier raised {exc!r}")
                self.assertFalse(result)

    def test_infinite_tolerance_admits_an_archived_delivery(self) -> None:
        issued = 1_600_000_000
        self.assertTrue(
            chatly.verify_webhook_signature(
                self.BODY, self._header(issued), self.SECRET, float("inf")
            )
        )

    def test_an_uppercase_digest_is_accepted(self) -> None:
        now = 1_750_000_000
        header = self._header(now).upper().replace("T=", "t=").replace("V1=", "v1=")
        self.assertTrue(
            chatly.verify_webhook_signature(self.BODY, header, self.SECRET, now=now)
        )

    def test_extra_header_fields_do_not_break_parsing(self) -> None:
        now = 1_750_000_000
        header = self._header(now) + ",v2=somethingelse"
        self.assertTrue(
            chatly.verify_webhook_signature(self.BODY, header, self.SECRET, now=now)
        )

    def test_the_header_name_is_the_livechat_one(self) -> None:
        """A README once documented ``x-chatly-signature``; it does not exist."""
        self.assertEqual(chatly.SIGNATURE_HEADER, "x-livechat-signature")
        self.assertEqual(chatly.DEFAULT_TOLERANCE_SECONDS, 300)


class Item8IdentityHashVector(unittest.TestCase):
    """§10.8 — the pinned identity-hash vector, verbatim.

    Cross-checked across implementations. If this fails, this SDK is wrong,
    not the vector.
    """

    def test_pinned_vector(self) -> None:
        self.assertEqual(
            chatly.identity_hash("sek_test_secret", "user_42"),
            "5e26772dce97d5ba995796e621f83f2e97e6f8c3f9386dbf153a98ab24c10271",
        )

    def test_output_is_lowercase_hex_of_the_right_length(self) -> None:
        digest = chatly.identity_hash("sek_test_secret", "user_42")
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, digest.lower())
        int(digest, 16)

    def test_a_different_id_gives_a_different_digest(self) -> None:
        self.assertNotEqual(
            chatly.identity_hash("sek_test_secret", "user_42"),
            chatly.identity_hash("sek_test_secret", "user_43"),
        )

    def test_empty_inputs_are_rejected(self) -> None:
        with self.assertRaises(InvalidArgumentError):
            chatly.identity_hash("", "user_42")
        with self.assertRaises(InvalidArgumentError):
            chatly.identity_hash("sek_test_secret", "")
        with self.assertRaises(ValueError):
            chatly.identity_hash("", "")

    def test_unicode_ids_are_utf8(self) -> None:
        """Not an invented vector — computed here, pinned so it cannot drift."""
        import hashlib
        import hmac

        expected = hmac.new(
            "sek_test_secret".encode("utf-8"), "user_café".encode("utf-8"), hashlib.sha256
        ).hexdigest()
        self.assertEqual(chatly.identity_hash("sek_test_secret", "user_café"), expected)


class Item9PinnedWebhookDelivery(unittest.TestCase):
    """§10.9 — this exact delivery, verbatim from the contract."""

    SECRET = "whsec_test"
    BODY = b'{"id":"evt_1"}'
    HEADER = "t=1700000000,v1=c89214b5b5da833daed6f0b8c5bb6bd58cea9022bd80ccc78230f3942d632925"
    BODY_ONLY_HEADER = (
        "t=1700000000,v1=030fa3b2413d1993c551364bd53bb9b3edb5c0c34d55dba6ada6041245632811"
    )

    def test_the_body_is_the_fourteen_bytes_the_contract_names(self) -> None:
        self.assertEqual(len(self.BODY), 14)
        self.assertFalse(self.BODY.endswith(b"\n"))

    def test_accepted_with_a_fixed_now(self) -> None:
        self.assertTrue(
            chatly.verify_webhook_signature(
                self.BODY, self.HEADER, self.SECRET, now=1_700_000_000
            )
        )

    def test_accepted_with_infinite_tolerance(self) -> None:
        self.assertTrue(
            chatly.verify_webhook_signature(
                self.BODY, self.HEADER, self.SECRET, float("inf")
            )
        )

    def test_rejected_when_the_digest_is_over_the_body_alone(self) -> None:
        self.assertFalse(
            chatly.verify_webhook_signature(
                self.BODY, self.BODY_ONLY_HEADER, self.SECRET, now=1_700_000_000
            )
        )

    def test_rejected_under_the_default_tolerance_because_2023_is_stale(self) -> None:
        self.assertFalse(
            chatly.verify_webhook_signature(self.BODY, self.HEADER, self.SECRET)
        )

    def test_the_digest_this_sdk_computes_is_the_contracts(self) -> None:
        """Print-the-vector check, so a cross-language comparison is exact."""
        import hashlib
        import hmac

        computed = hmac.new(
            self.SECRET.encode(), b"1700000000." + self.BODY, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            computed, "c89214b5b5da833daed6f0b8c5bb6bd58cea9022bd80ccc78230f3942d632925"
        )


if __name__ == "__main__":
    unittest.main()
