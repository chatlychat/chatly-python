"""CONTRACT.md §10, items 1-5: the client talking to the API.

The default base URL, the ``Authorization`` header, idempotency keys, the
typed error per status, and what is and is not retried. Items 6-9 —
pagination and the two offline helpers — are in
``test_contract_helpers.py``; the split is the contract's own seam, and it
keeps both files under the 650-line ceiling §9 sets.

One test class per numbered item, named so a failure says which clause of the
contract broke. Nothing here touches the network.
"""

from __future__ import annotations

import unittest

from support import (
    FakeTransport,
    build_client,
    error_response,
    json_response,
)

import chatly
from chatly import (
    APIError,
    AuthenticationError,
    ChatlyClient,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    TransportError,
    ValidationError,
)
from chatly.retry import NO_RETRIES, RetryPolicy


class Item1DefaultBaseUrl(unittest.TestCase):
    """§10.1 — the default base URL is the production host.

    This is the one test in the package that must NOT pass an explicit URL.
    Four SDKs shipped defaulting to a host that resolves nowhere
    (``api.livechat.local``, ``api.chatly.example``) and no test caught it,
    because every test passed a URL. A customer found it.
    """

    def test_constant_is_production(self) -> None:
        self.assertEqual(chatly.DEFAULT_API_URL, "https://api.chatlychat.com")

    def test_client_with_no_url_calls_production(self) -> None:
        transport = FakeTransport()
        client = ChatlyClient("ck_test_key", transport=transport)
        client.whoami()
        self.assertEqual(
            transport.last.url, "https://api.chatlychat.com/v1/api-keys/whoami"
        )

    def test_no_shipped_url_literal_points_somewhere_undeployable(self) -> None:
        """No URL-shaped literal in the package names a dev or example host.

        Checked over the AST's string constants rather than the raw text:
        the first version of this test grepped for the hostnames and failed
        on the comment in ``_transport.py`` that *documents* the four SDKs
        that shipped them. A gate that cannot tell a default from a warning
        about that default would push the warning out of the source, which
        is backwards.

        Only ``http(s)://`` literals are considered, so prose may name
        ``api.livechat.local`` and a real default may not.
        """
        import ast
        import pathlib

        banned = ("livechat.local", "chatly.example", "localhost", "127.0.0.1", "0.0.0.0")
        src = pathlib.Path(chatly.__file__).resolve().parent
        offenders = []
        checked = 0
        for path in sorted(src.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if not node.value.startswith(("http://", "https://")):
                    continue
                checked += 1
                for needle in banned:
                    if needle in node.value:
                        offenders.append(f"{path.name}:{node.lineno} {node.value}")
        self.assertEqual(offenders, [], f"undeployable host in a shipped URL literal: {offenders}")
        # A gate that checked nothing would also report no offenders. The
        # package contains at least the production default and the four
        # project URLs in the docstrings, so a zero here means the walk
        # broke rather than that the source is clean.
        self.assertGreaterEqual(checked, 1, "no URL literals were examined at all")

    def test_self_hosted_override_still_works(self) -> None:
        client, transport, _ = build_client(api_url="https://chat.internal.example.org/")
        client.whoami()
        # Note the trailing slash is stripped rather than doubling up.
        self.assertEqual(
            transport.last.url, "https://chat.internal.example.org/v1/api-keys/whoami"
        )

    def test_empty_key_is_rejected_at_construction(self) -> None:
        """§1 — not at the first call."""
        for bad in ("", "   "):
            with self.subTest(key=bad):
                with self.assertRaises(InvalidArgumentError):
                    ChatlyClient(bad, transport=FakeTransport())
        # And it is a ValueError too, so ordinary Python handling catches it.
        with self.assertRaises(ValueError):
            ChatlyClient("", transport=FakeTransport())


class Item2Authorization(unittest.TestCase):
    """§10.2 — ``Authorization`` carries the key."""

    def test_bearer_header_and_friends(self) -> None:
        client, transport, _ = build_client(api_key="ck_live_abc123")
        client.contacts.list()
        headers = transport.last.headers
        self.assertEqual(headers["authorization"], "Bearer ck_live_abc123")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "chatly-sdk-python/0.1.0")
        # No body on a GET, so no content-type on a GET.
        self.assertNotIn("content-type", headers)
        self.assertIsNone(transport.last.body)

    def test_content_type_on_a_body(self) -> None:
        client, transport, _ = build_client()
        client.contacts.upsert(email="a@example.com")
        self.assertEqual(transport.last.headers["content-type"], "application/json")
        self.assertEqual(transport.last.body, b'{"email":"a@example.com"}')

    def test_repr_does_not_leak_the_key(self) -> None:
        client, _, _ = build_client(api_key="ck_live_secret_value")
        self.assertNotIn("secret_value", repr(client))


class Item3IdempotencyKeys(unittest.TestCase):
    """§10.3 — a write sends one, two writes differ, a pinned key repeats."""

    def test_write_sends_an_idempotency_key(self) -> None:
        client, transport, _ = build_client()
        client.conversations.send("c1", "hello")
        key = transport.last.headers.get("idempotency-key")
        self.assertIsNotNone(key)
        import uuid

        uuid.UUID(str(key))  # a fresh v4; raises if it is not a UUID at all

    def test_every_write_verb_sends_one(self) -> None:
        client, transport, _ = build_client()
        client.contacts.upsert(email="a@example.com")           # POST
        client.macros.update("m1", name="x")                    # PATCH
        client.conversations.set_agent_handling("c1", "handled")  # PUT
        client.macros.delete("m1")                              # DELETE
        self.assertEqual(
            [r.method for r in transport.requests], ["POST", "PATCH", "PUT", "DELETE"]
        )
        for request in transport.requests:
            self.assertIn("idempotency-key", request.headers, request.method)

    def test_a_read_sends_none(self) -> None:
        client, transport, _ = build_client()
        client.contacts.list()
        self.assertNotIn("idempotency-key", transport.last.headers)

    def test_two_writes_send_different_keys(self) -> None:
        client, transport, _ = build_client()
        client.conversations.send("c1", "one")
        client.conversations.send("c1", "two")
        first, second = transport.idempotency_keys()
        self.assertIsNotNone(first)
        self.assertNotEqual(first, second)

    def test_a_pinned_key_is_sent_twice(self) -> None:
        client, transport, _ = build_client()
        pinned = client.with_idempotency_key("3f1a5c4e-0000-4000-8000-000000000001")
        pinned.conversations.send("c1", "one")
        pinned.conversations.send("c1", "two")
        keys = transport.idempotency_keys()
        self.assertEqual(keys[0], "3f1a5c4e-0000-4000-8000-000000000001")
        self.assertEqual(keys[0], keys[1])

    def test_pinning_does_not_mutate_the_original(self) -> None:
        client, transport, _ = build_client()
        pinned = client.with_idempotency_key("3f1a5c4e-0000-4000-8000-000000000001")
        self.assertIsNone(client.idempotency_key)
        self.assertEqual(pinned.idempotency_key, "3f1a5c4e-0000-4000-8000-000000000001")
        client.conversations.send("c1", "unpinned")
        self.assertNotEqual(
            transport.last.headers["idempotency-key"],
            "3f1a5c4e-0000-4000-8000-000000000001",
        )

    def test_every_namespace_on_a_pinned_client_is_pinned(self) -> None:
        """The Node SDK rebound namespaces one by one and missed ``search``.

        A derived client whose namespaces point at the parent's requester is
        exactly that bug, so check all twelve rather than the one the
        previous test happened to use.
        """
        client, transport, _ = build_client()
        pinned = client.with_idempotency_key("f0f0f0f0-0000-4000-8000-00000000000a")
        for name in (
            "contacts",
            "conversations",
            "tickets",
            "macros",
            "kb",
            "search",
            "events",
            "webhooks",
            "reports",
            "channels",
            "billing",
            "workspace",
        ):
            with self.subTest(namespace=name):
                namespace = getattr(pinned, name)
                self.assertIs(
                    namespace._requester,
                    pinned._requester,
                    f"{name} is wired to the wrong requester",
                )
                self.assertEqual(
                    namespace._requester.pinned_idempotency_key,
                    "f0f0f0f0-0000-4000-8000-00000000000a",
                )

    def test_a_generated_pin_is_accepted_and_a_short_one_is_not(self) -> None:
        client, _, _ = build_client()
        self.assertIsNotNone(client.with_idempotency_key().idempotency_key)
        with self.assertRaises(InvalidArgumentError):
            client.with_idempotency_key("too-short")

    def test_a_retried_write_reuses_its_key(self) -> None:
        """§4 — the whole reason the header exists."""
        client, transport, _ = build_client(
            [error_response(503, "unavailable", "try later"), json_response({"id": "m1"})]
        )
        client.conversations.send("c1", "hello")
        keys = transport.idempotency_keys()
        self.assertEqual(transport.count, 2)
        self.assertEqual(keys[0], keys[1], "a retry minted a new key and would double-write")


class Item4TypedErrors(unittest.TestCase):
    """§10.4 — 404/422/429 raise their types and carry ``request_id``."""

    def test_404_raises_not_found(self) -> None:
        client, _, _ = build_client(
            [error_response(404, "not_found", "Contact not found", headers={"x-request-id": "req_404"})]
        )
        with self.assertRaises(NotFoundError) as caught:
            client.contacts.get("missing")
        err = caught.exception
        self.assertEqual(err.status, 404)
        self.assertEqual(err.code, "not_found")
        self.assertEqual(err.message, "Contact not found")
        self.assertEqual(err.request_id, "req_404")
        self.assertIn("not_found", err.body)
        self.assertIn("req_404", str(err))

    def test_422_raises_validation(self) -> None:
        client, _, _ = build_client(
            [
                error_response(
                    422,
                    "unprocessable",
                    "Invalid request body",
                    details={"issues": [{"path": ["email"]}]},
                    headers={"x-request-id": "req_422"},
                )
            ]
        )
        with self.assertRaises(ValidationError) as caught:
            client.contacts.upsert(email="nope")
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.request_id, "req_422")
        self.assertEqual(caught.exception.details["issues"][0]["path"], ["email"])

    def test_400_validation_failed_also_raises_validation(self) -> None:
        """What this API actually sends.

        ``ValidationError`` in ``packages/shared/src/errors`` is **400** with
        code ``validation_failed``, and the exception filter maps a raw
        ``ZodError`` the same way. Nothing in the platform returns 422 for a
        validation failure today, so a client that only mapped 422 would
        hand every real validation error back as a generic 400.
        """
        client, _, _ = build_client(
            [
                error_response(
                    400,
                    "validation_failed",
                    "Invalid request body",
                    details={"issues": [{"path": ["contacts"]}]},
                    headers={"x-request-id": "req_400"},
                )
            ]
        )
        with self.assertRaises(ValidationError) as caught:
            client.contacts.bulk_upsert([{"email": "a@example.com"}])
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.code, "validation_failed")
        self.assertEqual(caught.exception.request_id, "req_400")

    def test_a_plain_400_is_not_a_validation_error(self) -> None:
        client, _, _ = build_client([error_response(400, "bad_request", "nope")])
        with self.assertRaises(APIError) as caught:
            client.contacts.list()
        self.assertNotIsInstance(caught.exception, ValidationError)
        self.assertIsInstance(caught.exception, chatly.BadRequestError)

    def test_429_raises_rate_limit_with_retry_after_from_the_header(self) -> None:
        client, _, _ = build_client(
            [
                error_response(
                    429,
                    "rate_limited",
                    "Too many requests",
                    headers={"retry-after": "7", "x-request-id": "req_429"},
                )
            ],
            retry=NO_RETRIES,
        )
        with self.assertRaises(RateLimitError) as caught:
            client.contacts.list()
        self.assertEqual(caught.exception.retry_after, 7.0)
        self.assertEqual(caught.exception.request_id, "req_429")

    def test_429_retry_after_from_the_body_when_there_is_no_header(self) -> None:
        """The API puts it in ``details.retryAfterSeconds``, not a header.

        ``RateLimitedError`` carries ``details: { retryAfterSeconds }`` and
        nothing in ``apps/api`` sets a ``Retry-After`` header, so a client
        that only read the header would report ``None`` for every real rate
        limit this platform produces.
        """
        client, _, _ = build_client(
            [
                error_response(
                    429, "rate_limited", "Too many requests", details={"retryAfterSeconds": 12}
                )
            ],
            retry=NO_RETRIES,
        )
        with self.assertRaises(RateLimitError) as caught:
            client.contacts.list()
        self.assertEqual(caught.exception.retry_after, 12.0)

    def test_401_and_403_are_distinguishable(self) -> None:
        """§3 — "my key is wrong" vs "my key lacks a scope", without a string."""
        client, _, _ = build_client([error_response(401, "unauthenticated", "no")])
        with self.assertRaises(AuthenticationError):
            client.contacts.list()

        client, _, _ = build_client([error_response(403, "forbidden", "no scope")])
        with self.assertRaises(PermissionDeniedError) as caught:
            client.contacts.list()
        self.assertNotIsInstance(caught.exception, AuthenticationError)

    def test_409_idempotency_conflict_is_flagged(self) -> None:
        client, _, _ = build_client(
            [
                error_response(
                    409,
                    "idempotency_conflict",
                    "Idempotency key already used with a different payload",
                )
            ]
        )
        with self.assertRaises(ConflictError) as caught:
            client.with_idempotency_key(
                "11111111-2222-4333-8444-555555555555"
            ).conversations.send("c1", "hi")
        self.assertTrue(caught.exception.is_idempotency_conflict)

    def test_409_plain_conflict_is_not_flagged(self) -> None:
        client, _, _ = build_client([error_response(409, "conflict", "in flight")])
        with self.assertRaises(ConflictError) as caught:
            client.contacts.merge("a", "b")
        self.assertFalse(caught.exception.is_idempotency_conflict)

    def test_5xx_raises_server_error(self) -> None:
        client, _, _ = build_client(
            [error_response(500, "unknown", "Internal server error")], retry=NO_RETRIES
        )
        with self.assertRaises(ServerError):
            client.contacts.list()

    def test_the_nested_envelope_is_what_is_parsed(self) -> None:
        """``{"error": {...}}`` — the shape the API's filter really sends.

        A client that read ``code`` at the top level got ``None`` for every
        response; that shipped in the widget and broke session recovery. A
        flat body is still parsed, for a proxy that answers without going
        through the filter.
        """
        from chatly._transport import HTTPResponse
        from chatly.errors import error_from_response

        nested = error_from_response(
            status=404,
            headers={},
            body='{"error":{"code":"not_found","message":"gone"}}',
        )
        self.assertEqual((nested.code, nested.message), ("not_found", "gone"))

        flat = error_from_response(
            status=404, headers={}, body='{"code":"not_found","message":"gone"}'
        )
        self.assertEqual((flat.code, flat.message), ("not_found", "gone"))

        self.assertIsInstance(HTTPResponse(404), HTTPResponse)

    def test_an_unparseable_error_body_still_raises_a_typed_error(self) -> None:
        from chatly._transport import HTTPResponse

        client, _, _ = build_client(
            [HTTPResponse(status=404, headers={"content-type": "text/html"}, body=b"<html>502</html>")]
        )
        with self.assertRaises(NotFoundError) as caught:
            client.contacts.get("x")
        self.assertEqual(caught.exception.code, "http_404")
        self.assertEqual(caught.exception.body, "<html>502</html>")

    def test_transport_failure_is_its_own_type(self) -> None:
        """§3 — distinct from any HTTP status."""
        client, _, _ = build_client(
            [TransportError("dns failure"), TransportError("dns failure"), TransportError("dns failure")]
        )
        with self.assertRaises(TransportError) as caught:
            client.contacts.list()
        self.assertNotIsInstance(caught.exception, APIError)


class Item5Retries(unittest.TestCase):
    """§10.5 — a 429 is retried then succeeds; a 400 is not retried."""

    def test_429_is_retried_and_then_succeeds(self) -> None:
        client, transport, sleeper = build_client(
            [
                error_response(429, "rate_limited", "slow down", headers={"retry-after": "2"}),
                json_response({"items": [{"id": "k1"}], "nextCursor": None}),
            ]
        )
        page = client.contacts.list()
        self.assertEqual(transport.count, 2)
        self.assertEqual([i["id"] for i in page.items], ["k1"])
        self.assertEqual(sleeper.waits, [2.0], "Retry-After was not honoured")

    def test_400_is_not_retried(self) -> None:
        client, transport, sleeper = build_client(
            [error_response(400, "bad_request", "nope"), json_response({"items": []})]
        )
        with self.assertRaises(APIError):
            client.contacts.list()
        self.assertEqual(transport.count, 1, "a 400 was retried")
        self.assertEqual(sleeper.waits, [])

    def test_404_422_and_409_are_not_retried(self) -> None:
        for status, code in ((404, "not_found"), (422, "unprocessable"), (409, "conflict")):
            with self.subTest(status=status):
                client, transport, _ = build_client(
                    [error_response(status, code, "no"), json_response({})]
                )
                with self.assertRaises(APIError):
                    client.contacts.list()
                self.assertEqual(transport.count, 1)

    def test_5xx_is_retried_then_gives_up_after_three_attempts(self) -> None:
        client, transport, sleeper = build_client(
            [error_response(503, "unavailable", "no") for _ in range(4)]
        )
        with self.assertRaises(ServerError):
            client.contacts.list()
        self.assertEqual(transport.count, 3, "default policy is 3 attempts total")
        self.assertEqual(sleeper.waits, [0.5, 1.0], "exponential backoff")

    def test_a_connection_error_is_retried(self) -> None:
        client, transport, _ = build_client(
            [TransportError("connection refused"), json_response({"items": []})]
        )
        client.contacts.list()
        self.assertEqual(transport.count, 2)

    def test_retries_can_be_turned_off(self) -> None:
        client, transport, _ = build_client(
            [error_response(503, "unavailable", "no")], retry=NO_RETRIES
        )
        with self.assertRaises(ServerError):
            client.contacts.list()
        self.assertEqual(transport.count, 1)

    def test_a_servers_retry_after_is_clamped(self) -> None:
        """A proxy answering ``Retry-After: 86400`` must not park the process."""
        client, _, sleeper = build_client(
            [
                error_response(429, "rate_limited", "no", headers={"retry-after": "86400"}),
                # A page envelope, not `{}`: `contacts.list` is a paged route
                # and its decoder refuses a body that is not one.
                json_response({"items": [], "nextCursor": None}),
            ],
            retry=RetryPolicy(jitter=False, max_retry_after=30.0),
        )
        client.contacts.list()
        self.assertEqual(sleeper.waits, [30.0])

    def test_jitter_stays_within_the_computed_window(self) -> None:
        policy = RetryPolicy(initial_backoff=1.0, multiplier=2.0, jitter=True)
        for attempt in (1, 2, 3):
            for _ in range(50):
                wait = policy.backoff(attempt)
                self.assertGreaterEqual(wait, 0.0)
                self.assertLessEqual(wait, min(1.0 * 2 ** (attempt - 1), policy.max_backoff))


if __name__ == "__main__":
    unittest.main()
