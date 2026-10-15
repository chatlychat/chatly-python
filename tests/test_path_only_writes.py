"""Writes whose only input is a path parameter, and what they must NOT send.

Split out of `test_transport.py` when that file reached 848 lines against
this repository's 650-line ceiling — a ceiling `check-file-size` only began
applying to `.py` on 2026-10-14, having scanned three of the eleven
languages here until then.

The seam is the subject rather than a line count: both classes below are
about the seven routes whose entire input is a path parameter. One asserts
what every one of them sends — the verb, the interpolated path, an
`Idempotency-Key`, and no body — and the other covers the refusals of the
newest of them. `unittest discover` finds `test_*.py`, so nothing had to be
registered.
"""

from __future__ import annotations

import json
import unittest
from urllib.parse import urlsplit

import support
from support import build_client, error_response, json_response

import chatly
from chatly import ChatlyClient, InvalidArgumentError


class WritesWhoseOnlyInputIsAPathParameter(unittest.TestCase):
    """Seven POSTs take no body and no query at all. Asserted on the REQUEST.

    Every assertion here reads :attr:`FakeTransport.last` — what the SDK
    *sent* — rather than what came back. The fallback body a fake transport
    serves is the SDK's own idea of a reply, so a test that asserts on the
    return value agrees with whatever the method did, including putting the
    path parameter in the body or calling a near-miss URL. The surface lock
    next door pins the verb and the path TEMPLATE; this pins the two things
    the lock cannot see, namely the interpolated id and the headers.

    The body is asserted **byte-exact** as ``b"{}"``, and that is deliberate
    rather than sloppiness about "no body". This SDK's transport serialises an
    absent body on a non-DELETE write as the empty JSON object
    (``_transport.py``: ``if verb in WRITE_METHODS and verb != "DELETE" and
    body is None``), because several of these routes are parsed as JSON
    objects by the API. So the thing worth pinning is that **the method
    contributes nothing of its own**: ``b"{}"`` is two bytes and no field can
    hide inside it, so the moment anyone passes ``{"contactId": ...}`` — the
    exact mistake that would make the path parameter redundant — this fails.
    """

    #: ``(label, call, path)``. The path carries the id already interpolated,
    #: which is the half the manifest's ``{contactId}`` template cannot check.
    CASES = (
        (
            "ai.test_provider",
            lambda c: c.ai.test_provider("openai"),
            "/v1/ai-providers/openai/test",
        ),
        (
            "bots.rotate_external_secret",
            lambda c: c.bots.rotate_external_secret("b_1"),
            "/v1/bots/b_1/external/rotate-secret",
        ),
        (
            "channels.rotate_secret",
            lambda c: c.channels.rotate_secret("ch_1"),
            "/v1/channels/ch_1/secret/rotate",
        ),
        (
            "customer_cards.rotate_secret",
            lambda c: c.customer_cards.rotate_secret("cc_1"),
            "/v1/customer-cards/cc_1/rotate-secret",
        ),
        (
            "docs_sources.webhook",
            lambda c: c.docs_sources.webhook("ds_1"),
            "/v1/docs-sources/ds_1/webhook",
        ),
        (
            "knowledge_gaps.draft",
            lambda c: c.knowledge_gaps.draft("kg_1"),
            "/v1/knowledge-gaps/kg_1/draft",
        ),
        (
            "visitors.start_conversation",
            lambda c: c.visitors.start_conversation("cont_1"),
            "/v1/visitors/cont_1/start-conversation",
        ),
    )

    def test_each_sends_one_post_to_the_interpolated_path_with_a_key_and_no_fields(
        self,
    ) -> None:
        for label, call, path in self.CASES:
            with self.subTest(route=label):
                client, transport, _ = build_client()
                call(client)
                self.assertEqual(transport.count, 1, f"{label}: expected one request")
                request = transport.last
                self.assertEqual(request.method, "POST", f"{label}: wrong verb")
                self.assertEqual(
                    urlsplit(request.url).path, path, f"{label}: wrong path"
                )
                self.assertEqual(
                    urlsplit(request.url).query, "", f"{label}: sent query parameters"
                )
                self.assertEqual(
                    request.body,
                    b"{}",
                    f"{label}: the method contributed a body of its own",
                )
                self.assertIn(
                    "idempotency-key",
                    request.headers,
                    f"{label}: a write with no Idempotency-Key is a 428 in production",
                )

    def test_start_conversation_percent_encodes_the_contact_id(self) -> None:
        """The id reaches the URL, so a ``/`` in it must not rewrite the route."""
        client, transport, _ = build_client()
        client.visitors.start_conversation("a/b")
        self.assertEqual(
            urlsplit(transport.last.url).path,
            "/v1/visitors/a%2Fb/start-conversation",
        )

    def test_start_conversation_refuses_an_empty_contact_id_before_sending(self) -> None:
        client, transport, _ = build_client()
        with self.assertRaises(chatly.InvalidArgumentError):
            client.visitors.start_conversation("")
        self.assertEqual(transport.count, 0, "an empty id reached the network")


class ProactiveOutreachRefusals(unittest.TestCase):
    """``visitors.start_conversation``'s two refusals, which are not about scope.

    The route is gated by a workspace opt-in that is **off by default**, so
    the commonest failure an integrator meets is a 403 that has nothing to do
    with their key. The SDK cannot fix that; it must not flatten it either.
    """

    OPT_IN_REFUSAL = (
        "This workspace does not allow an API key to open conversations. "
        "An owner or admin enables it with `PATCH /v1/workspace/settings` "
        '`{ "proactiveOutreach": { "apiKeysMayStartConversations": true } }`. '
        "Nothing was sent."
    )

    def test_the_workspace_opt_in_refusal_arrives_as_permission_denied(self) -> None:
        client, transport, _ = build_client(
            [error_response(403, "forbidden", self.OPT_IN_REFUSAL)]
        )
        with self.assertRaises(chatly.PermissionDeniedError) as caught:
            client.visitors.start_conversation("cont_1")
        # The message is the only thing that distinguishes the opt-in from a
        # missing scope, so it must survive into the exception rather than be
        # replaced by a generic "forbidden".
        self.assertIn("apiKeysMayStartConversations", str(caught.exception))
        # A 403 is not retryable. Retrying an outreach refusal three times is
        # three refusals in the workspace's audit log for one mistake.
        self.assertEqual(transport.count, 1)

    def test_the_per_contact_limit_429_has_no_retry_after_header(self) -> None:
        """The REAL envelope for this route's own limit, header and all.

        Read off the server, not assumed: ``consumePerContactOutreachToken``
        (``proactive-outreach-guard.ts``) throws ``RateLimitedError(ttl)``,
        which is an ``AppError`` carrying ``details: { retryAfterSeconds }``,
        and ``app-exception.filter.ts`` sends ``wireError(...)`` and sets **no
        headers**. The only thing that synthesises a plain ``Retry-After`` is
        a Fastify ``onSend`` hook in ``main.ts`` that folds
        ``Retry-After-<bucket>`` headers emitted by ``@nestjs/throttler`` —
        and this refusal does not come from the throttler, so there are no
        bucket headers and nothing is synthesised.

        So the TTL arrives in the **body**, not a header — and this SDK
        already handles that: ``errors.py`` falls back to
        ``details.retryAfterSeconds`` when the header is absent, so
        ``retry_after`` is populated here *from the body*. That fallback is
        the thing this test pins. Remove it and ``retry_after`` goes ``None``
        on every per-contact refusal while the header-based 429 tests stay
        green, which is exactly the gap worth having a test for.

        Faking a ``retry-after`` header on this fixture would hide all of
        that: it would prove the header path (already covered) and say
        nothing about the path this route actually takes. A fixture that
        invents the server's shape agrees with the client instead of with the
        server — the trap ``wireError``'s own docstring warns about.

        The route DOES also sit behind the global throttler buckets
        (``short`` 30/s, ``login`` 100/15min), and a 429 from those carries a
        real ``Retry-After``; that path is covered by the contract suite's
        generic 429 test, not here.
        """
        client, _, _ = build_client(
            [
                error_response(
                    429,
                    "rate_limited",
                    "Too many requests",
                    details={"retryAfterSeconds": 1800},
                )
            ]
            * 3
        )
        with self.assertRaises(chatly.RateLimitError) as caught:
            client.visitors.start_conversation("cont_1")
        error = caught.exception
        self.assertEqual(error.status, 429)
        self.assertEqual(error.code, "rate_limited")
        # The response carried no Retry-After header at all...
        self.assertEqual(error.details.get("retryAfterSeconds"), 1800)
        # ...and the TTL still reached the caller, from the body.
        self.assertEqual(
            error.retry_after,
            1800.0,
            "this refusal sends no Retry-After header, so retry_after can only "
            "come from details.retryAfterSeconds — if this is None that "
            "fallback in errors.py has been removed",
        )

    def test_a_header_beats_the_body_hint_when_both_arrive(self) -> None:
        """The control for the test above: the fallback must not shadow a header.

        Without this, a fallback that ignored the header entirely would pass
        the previous test just as well.
        """
        client, _, _ = build_client(
            [
                error_response(
                    429,
                    "rate_limited",
                    "Too many requests",
                    details={"retryAfterSeconds": 1800},
                    headers={"retry-after": "7"},
                )
            ]
            * 3
        )
        with self.assertRaises(chatly.RateLimitError) as caught:
            client.visitors.start_conversation("cont_1")
        self.assertEqual(caught.exception.retry_after, 7.0)


if __name__ == "__main__":
    unittest.main()
