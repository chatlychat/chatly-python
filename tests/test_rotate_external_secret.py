"""``bots.rotate_external_secret(..., activate_at=)`` — asserted on the REQUEST.

The route grew an optional body in d509799a: ``{"activateAt": "<ISO 8601>"}``
under a ``.strict()`` schema, so a snake_case ``activate_at`` on the wire is a
400 and an extra key is a 400. A fake transport that answers with a canned
body agrees with every one of those mistakes, so each test here reads
:attr:`FakeTransport.last` — what the SDK *sent* — and decodes the raw bytes.

The no-argument call is pinned byte-exact as ``b"{}"`` by
``test_path_only_writes.py``, which this change must leave untouched; the one
test below that repeats it does so beside the with-argument case so a
mutation that always attaches a body fails here too.
"""

from __future__ import annotations

import datetime as dt
import json
import unittest
from urllib.parse import urlsplit

import support  # noqa: F401  (puts src/ on sys.path)
from support import build_client, json_response

import chatly

PATH = "/v1/bots/b_1/external/rotate-secret"


def _sent_body(transport: support.FakeTransport) -> object:
    raw = transport.last.body
    assert raw is not None, "no body bytes were sent"
    return json.loads(raw.decode("utf-8"))


class RotateExternalSecretRequest(unittest.TestCase):
    def test_a_string_activate_at_is_sent_verbatim_under_the_camelcase_key(self) -> None:
        value = "2026-10-16T09:00:00.000Z"
        client, transport, _ = build_client()
        client.bots.rotate_external_secret("b_1", activate_at=value)

        self.assertEqual(transport.count, 1)
        request = transport.last
        self.assertEqual(request.method, "POST")
        self.assertEqual(urlsplit(request.url).path, PATH)
        self.assertEqual(urlsplit(request.url).query, "")
        self.assertIn("idempotency-key", request.headers)
        self.assertTrue(request.headers["idempotency-key"])
        body = _sent_body(transport)
        self.assertEqual(body, {"activateAt": value})
        # Spelled out because the schema is strict: snake_case is a 400.
        self.assertNotIn("activate_at", body)  # type: ignore[operator]

    def test_a_string_with_an_offset_is_not_rewritten(self) -> None:
        """The server validates strings; the SDK must not 'normalise' them."""
        value = "2026-10-16T11:00:00+02:00"
        client, transport, _ = build_client()
        client.bots.rotate_external_secret("b_1", activate_at=value)
        self.assertEqual(_sent_body(transport), {"activateAt": value})

    def test_an_aware_utc_datetime_is_sent_as_its_z_form(self) -> None:
        when = dt.datetime(2026, 10, 16, 9, 0, 0, tzinfo=dt.timezone.utc)
        client, transport, _ = build_client()
        client.bots.rotate_external_secret("b_1", activate_at=when)
        self.assertEqual(_sent_body(transport), {"activateAt": "2026-10-16T09:00:00Z"})

    def test_a_non_utc_datetime_is_converted_to_the_same_utc_instant(self) -> None:
        plus_two = dt.timezone(dt.timedelta(hours=2))
        when = dt.datetime(2026, 10, 16, 11, 30, 15, 250000, tzinfo=plus_two)
        client, transport, _ = build_client()
        client.bots.rotate_external_secret("b_1", activate_at=when)
        sent = _sent_body(transport)
        self.assertEqual(sent, {"activateAt": "2026-10-16T09:30:15.250000Z"})
        # And it really is the same instant, not merely a plausible string.
        parsed = dt.datetime.fromisoformat(sent["activateAt"].replace("Z", "+00:00"))  # type: ignore[index]
        self.assertEqual(parsed, when)

    def test_without_activate_at_the_request_is_what_it_always_was(self) -> None:
        client, transport, _ = build_client()
        client.bots.rotate_external_secret("b_1")
        self.assertEqual(transport.count, 1)
        self.assertEqual(transport.last.method, "POST")
        self.assertEqual(urlsplit(transport.last.url).path, PATH)
        self.assertEqual(transport.last.body, b"{}")
        self.assertIn("idempotency-key", transport.last.headers)

    def test_an_explicit_none_is_the_same_as_omitting_it(self) -> None:
        client, transport, _ = build_client()
        client.bots.rotate_external_secret("b_1", activate_at=None)
        self.assertEqual(transport.last.body, b"{}")

    def test_a_naive_datetime_raises_before_anything_is_sent(self) -> None:
        client, transport, _ = build_client()
        with self.assertRaises(ValueError) as caught:
            client.bots.rotate_external_secret(
                "b_1", activate_at=dt.datetime(2026, 10, 16, 9, 0, 0)
            )
        self.assertIsInstance(caught.exception, chatly.InvalidArgumentError)
        self.assertEqual(transport.count, 0, "a naive datetime reached the network")

    def test_a_value_of_the_wrong_type_raises_before_anything_is_sent(self) -> None:
        client, transport, _ = build_client()
        with self.assertRaises(chatly.InvalidArgumentError):
            client.bots.rotate_external_secret("b_1", activate_at=1760605200)  # type: ignore[arg-type]
        self.assertEqual(transport.count, 0)


class RotateExternalSecretResponse(unittest.TestCase):
    """The weak half: these assert the SDK does not strip a response field."""

    def test_activates_at_reaches_the_caller_when_deferred(self) -> None:
        client, _, _ = build_client(
            [
                json_response(
                    {"signingSecret": "whsec_x", "activatesAt": "2026-10-16T09:00:00.000Z"},
                    status=201,
                )
            ]
        )
        result = client.bots.rotate_external_secret(
            "b_1", activate_at="2026-10-16T09:00:00.000Z"
        )
        self.assertEqual(result["signingSecret"], "whsec_x")
        self.assertEqual(result["activatesAt"], "2026-10-16T09:00:00.000Z")

    def test_activates_at_is_none_on_a_hard_cut(self) -> None:
        client, _, _ = build_client(
            [json_response({"signingSecret": "whsec_x", "activatesAt": None}, status=201)]
        )
        result = client.bots.rotate_external_secret("b_1")
        self.assertIn("activatesAt", result)
        self.assertIsNone(result["activatesAt"])


if __name__ == "__main__":
    unittest.main()
