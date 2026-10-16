"""``sign_chatly_v2`` — against the reference's bytes, and round-tripped.

Three claims, and only the first two are worth much on their own:

1. The base string is the documented one. Pinned as a literal, computed
   nowhere in this file, because a test that derives the expected string the
   same way the code does agrees with the code's mistakes. The pins are the
   ones ``packages/shared/src/webhook-signature/v2.spec.ts`` and the public
   docs carry.
2. The value this mints verifies through this SDK's own
   ``verify_chatly_signature``, and a one-byte change to the body, the path,
   the method or the timestamp makes it stop verifying. Round-tripping alone
   proves only that the two halves of this package agree — which they would
   if both were wrong the same way — so (1) is what anchors it.
3. The workflow action's DUAL-DIGEST value, ``t=<T>,v1=<target>,v1=<body>``
   with NO marker, verifies both ways. That is the shape production sends
   today (``WORKFLOW_WEBHOOK_V2_PHASE = 'dual'``), it is in the published
   docs, and the cross-SDK corpus has no vector for it — so without this test
   nothing in this SDK covers the one wire value a workflow-webhook
   integrator actually receives.
"""

from __future__ import annotations

import unittest

import support  # noqa: F401 - puts src/ on sys.path

import chatly
from chatly import chatly_v2_base_string, sign_chatly_v2, verify_chatly_signature

SECRET = "whsec_mint_secret"
BODY = '{"id":"evt_1","type":"message.created"}'
T = 1760000000
NOW_MS = 1760000000000
METHOD = "POST"
PATH = "/hooks/chatly?tenant=42"


def _digest_of(value: str) -> str:
    """The ``v1=`` field out of a minted value.

    The producer does exactly this to build the dual-digest value —
    ``digestOf`` in ``apps/worker/src/handlers/action-handlers/fire-webhook.ts``
    — so the dual case below is assembled the way the bytes on the wire are.
    """
    for part in value.split(","):
        if part.startswith("v1="):
            return part[len("v1=") :]
    raise AssertionError(f"no v1 field in {value!r}")


class BaseString(unittest.TestCase):
    def test_the_target_base_is_t_method_path_body(self) -> None:
        self.assertEqual(
            chatly_v2_base_string(
                base="target", timestamp_seconds=T, body=BODY, method=METHOD, path=PATH
            ),
            b'1760000000.POST./hooks/chatly?tenant=42.{"id":"evt_1","type":"message.created"}',
        )

    def test_the_body_base_is_t_body(self) -> None:
        self.assertEqual(
            chatly_v2_base_string(base="body", timestamp_seconds=T, body=BODY),
            b'1760000000.{"id":"evt_1","type":"message.created"}',
        )

    def test_the_method_is_upper_cased_and_the_path_is_not(self) -> None:
        # The verifier upper-cases the method and leaves the path alone, so a
        # mint that normalised the path would produce a value nothing verifies.
        self.assertEqual(
            chatly_v2_base_string(
                base="target", timestamp_seconds=T, body="", method="get", path="/Mixed/Case?A=1"
            ),
            b"1760000000.GET./Mixed/Case?A=1.",
        )

    def test_a_bytes_body_is_signed_as_given(self) -> None:
        # Not every body is valid UTF-8 text, and the MAC is over bytes. For a
        # str body this is the reference's string, encoded.
        self.assertEqual(
            chatly_v2_base_string(base="body", timestamp_seconds=T, body=b"\xff\xfe"),
            b"1760000000.\xff\xfe",
        )

    def test_the_pinned_digest_matches_the_shared_producer(self) -> None:
        # The FROZEN vector from `packages/shared/src/webhook-signature/
        # v2.spec.ts` ("matches a frozen vector, byte for byte"), minted here.
        # Two independent implementations of one construction (ADR 0056) held
        # against the same bytes — field order, separators, digest case and
        # marker letter all included, which is why it is a whole value and not
        # just a digest.
        self.assertEqual(
            sign_chatly_v2(
                base="target",
                secret="whsec_frozen",
                timestamp_seconds=1700000000,
                method="POST",
                path="/x",
                body='{"a":1}',
            ),
            "t=1700000000,v1=a22f16be6cc2f88da16b175e5057406cbe820e116b9e74375a0020f1c94f5975,b=t",
        )


class Markers(unittest.TestCase):
    def test_the_marker_says_which_base(self) -> None:
        target = sign_chatly_v2(
            base="target", secret=SECRET, timestamp_seconds=T, body=BODY, method=METHOD, path=PATH
        )
        body = sign_chatly_v2(base="body", secret=SECRET, timestamp_seconds=T, body=BODY)
        self.assertTrue(target.endswith(",b=t"), target)
        self.assertTrue(body.endswith(",b=b"), body)
        # Different bases must be different digests, or the marker is the only
        # thing distinguishing them and `b=` would be free to forge.
        self.assertNotEqual(_digest_of(target), _digest_of(body))

    def test_there_is_no_default_base(self) -> None:
        with self.assertRaises(TypeError):
            sign_chatly_v2(secret=SECRET, timestamp_seconds=T, body=BODY)  # type: ignore[call-arg]
        with self.assertRaises(ValueError):
            sign_chatly_v2(base="unified", secret=SECRET, timestamp_seconds=T, body=BODY)


class Refusals(unittest.TestCase):
    """Minting refuses rather than signing a string nothing can reproduce."""

    def test_the_target_base_requires_a_method_and_a_path(self) -> None:
        for kwargs in ({}, {"method": METHOD}, {"path": PATH}, {"method": "", "path": ""}):
            with self.subTest(sorted(kwargs)):
                with self.assertRaises(ValueError):
                    sign_chatly_v2(
                        base="target",
                        secret=SECRET,
                        timestamp_seconds=T,
                        body=BODY,
                        **kwargs,  # type: ignore[arg-type]
                    )

    def test_an_empty_secret_is_refused(self) -> None:
        # An empty string is a valid HMAC key, which is the problem: the
        # likeliest cause is an env var that never got set.
        for secret in ("", b""):
            with self.subTest(repr(secret)):
                with self.assertRaises(ValueError):
                    sign_chatly_v2(
                        base="body", secret=secret, timestamp_seconds=T, body=BODY
                    )

    def test_a_non_integer_timestamp_is_refused(self) -> None:
        # `str(1760000000.0)` is "1760000000.0" and the verifier's `t` is a run
        # of digits, so a float would sign text nothing can verify. `True` is
        # an int in Python and would sign "1".
        for ts in (1760000000.0, "1760000000", True, None):
            with self.subTest(repr(ts)):
                with self.assertRaises(TypeError):
                    sign_chatly_v2(
                        base="body", secret=SECRET, timestamp_seconds=ts, body=BODY  # type: ignore[arg-type]
                    )

    def test_a_parsed_body_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            sign_chatly_v2(
                base="body", secret=SECRET, timestamp_seconds=T, body={"id": "evt_1"}  # type: ignore[arg-type]
            )


class RoundTrip(unittest.TestCase):
    def _mint(self, **overrides: object) -> str:
        kwargs: dict = {
            "base": "target",
            "secret": SECRET,
            "timestamp_seconds": T,
            "body": BODY,
            "method": METHOD,
            "path": PATH,
        }
        kwargs.update(overrides)
        return sign_chatly_v2(**kwargs)  # type: ignore[arg-type]

    def _verify(self, header: str, **overrides: object) -> chatly.ChatlySignatureResult:
        kwargs: dict = {"method": METHOD, "path": PATH, "now_ms": NOW_MS}
        kwargs.update(overrides)
        return verify_chatly_signature(
            "unified_v2", BODY, {"x-chatly-signature-v2": header}, SECRET, **kwargs
        )

    def test_a_minted_target_value_verifies_as_unified_v2(self) -> None:
        result = self._verify(self._mint())
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.base, "target")
        self.assertEqual(result.timestamp_ms, NOW_MS)

    def test_a_minted_body_value_verifies_as_workflow_webhook(self) -> None:
        header = self._mint(base="body", method=None, path=None)
        result = verify_chatly_signature(
            "workflow_webhook", BODY, {"x-chatly-signature-v2": header}, SECRET, now_ms=NOW_MS
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.base, "body")

    def test_one_changed_byte_stops_it_verifying(self) -> None:
        # Each row changes exactly ONE thing between the mint and the verify.
        # Without these, "it verifies" could be an unconditional yes.
        header = self._mint()
        self.assertEqual(
            self._verify(header, path=PATH + "0").reason, "signature_mismatch", "path"
        )
        self.assertEqual(self._verify(header, method="PUT").reason, "signature_mismatch", "method")
        self.assertEqual(
            verify_chatly_signature(
                "unified_v2",
                BODY + " ",
                {"x-chatly-signature-v2": header},
                SECRET,
                method=METHOD,
                path=PATH,
                now_ms=NOW_MS,
            ).reason,
            "signature_mismatch",
            "body",
        )
        self.assertEqual(
            verify_chatly_signature(
                "unified_v2",
                BODY,
                {"x-chatly-signature-v2": header},
                "whsec_other",
                method=METHOD,
                path=PATH,
                now_ms=NOW_MS,
            ).reason,
            "signature_mismatch",
            "secret",
        )
        self.assertEqual(
            self._verify(self._mint(timestamp_seconds=T - 301)).reason,
            "timestamp_outside_tolerance",
            "a t 301s old",
        )

    def test_a_forged_marker_cannot_move_the_base(self) -> None:
        # `b=` is something anyone on the wire can write, so re-labelling a
        # body digest as the target base must not make it verify.
        body_value = self._mint(base="body", method=None, path=None)
        forged = body_value[: -len(",b=b")] + ",b=t"
        self.assertEqual(self._verify(forged).reason, "signature_mismatch")


class DualDigest(unittest.TestCase):
    """The workflow action's value TODAY: two digests, one value, no marker.

    ``WORKFLOW_WEBHOOK_V2_PHASE = 'dual'`` in
    ``apps/worker/src/handlers/action-handlers/fire-webhook.ts``, and
    documented on ``/docs/api-external-agents``. The cross-SDK corpus has no
    vector for it, so this is the only thing in this SDK that covers it.
    """

    def _dual(self) -> str:
        target = sign_chatly_v2(
            base="target", secret=SECRET, timestamp_seconds=T, body=BODY, method=METHOD, path=PATH
        )
        body = sign_chatly_v2(base="body", secret=SECRET, timestamp_seconds=T, body=BODY)
        # Unified first, body last, and NO marker — the order and the absence
        # are both load-bearing. A `b=b` would make `unified_v2` refuse the
        # value outright; a `b=t` would send a verifier that keeps only the
        # last `v1` to compare the target base against the body digest.
        return f"t={T},v1={_digest_of(target)},v1={_digest_of(body)}"

    def test_the_shape_is_two_v1_fields_and_no_marker(self) -> None:
        value = self._dual()
        self.assertEqual(value.count(",v1="), 2, value)
        self.assertNotIn("b=", value)

    def test_it_verifies_as_unified_v2_with_a_target(self) -> None:
        result = verify_chatly_signature(
            "unified_v2",
            BODY,
            {"x-chatly-signature-v2": self._dual()},
            SECRET,
            method=METHOD,
            path=PATH,
            now_ms=NOW_MS,
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.base, "target")

    def test_it_verifies_as_workflow_webhook_either_way(self) -> None:
        # With a target it takes the unified digest; without one it falls to
        # the body digest, which is the receiver that has not migrated. Both
        # must pass, or the migration this shape exists to enable is broken
        # in one direction.
        with_target = verify_chatly_signature(
            "workflow_webhook",
            BODY,
            {"x-chatly-signature-v2": self._dual()},
            SECRET,
            method=METHOD,
            path=PATH,
            now_ms=NOW_MS,
        )
        self.assertTrue(with_target.ok, with_target.message)
        self.assertEqual(with_target.base, "target")

        without = verify_chatly_signature(
            "workflow_webhook",
            BODY,
            {"x-chatly-signature-v2": self._dual()},
            SECRET,
            now_ms=NOW_MS,
        )
        self.assertTrue(without.ok, without.message)
        self.assertEqual(without.base, "body")

    def test_a_tampered_body_fails_both_digests(self) -> None:
        # Two valid digests must not mean two chances at a forgery.
        for kwargs in ({"method": METHOD, "path": PATH}, {}):
            with self.subTest(sorted(kwargs)):
                result = verify_chatly_signature(
                    "workflow_webhook",
                    BODY + "x",
                    {"x-chatly-signature-v2": self._dual()},
                    SECRET,
                    now_ms=NOW_MS,
                    **kwargs,  # type: ignore[arg-type]
                )
                self.assertEqual(result.reason, "signature_mismatch")


class PublicSurface(unittest.TestCase):
    def test_exports(self) -> None:
        for name in ("sign_chatly_v2", "chatly_v2_base_string", "CHATLY_V2_MINT_BASES"):
            self.assertIn(name, chatly.__all__)
            self.assertTrue(hasattr(chatly, name))
        self.assertEqual(chatly.CHATLY_V2_MINT_BASES, ("target", "body"))


if __name__ == "__main__":
    unittest.main()
