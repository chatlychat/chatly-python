"""``verify_chatly_signature`` against the cross-SDK corpus, and never-raises.

``signature_vectors.json`` beside this file is a byte-identical copy of the
corpus every Chatly SDK runs; the Node SDK's suite fails if any copy drifts,
so it is never edited here. If a vector fails, this SDK is wrong and the
vector is right.

It is loaded relative to THIS file, never via ``../sdk-node`` or
``../sdk-spec``: in the public mirror the SDK directory is the repository
root, and a path that only exists in the monorepo would make the suite
unrunnable exactly where it is the only CI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List

import support  # noqa: F401 - puts src/ on sys.path

import chatly
from chatly import (
    CHATLY_SIGNATURE_FAILURES,
    CHATLY_SIGNATURE_SURFACES,
    ChatlySignatureResult,
    verify_chatly_signature,
)

CORPUS_PATH = Path(__file__).resolve().parent / "signature_vectors.json"

#: A floor, not the count: a loader that silently finds zero vectors would
#: otherwise pass by checking nothing. Raise it when the corpus grows.
#:
#: 59 -> 61 on 2026-10-16. It said "raise it when the corpus grows" and the
#: corpus had grown to 61, so this was blind to exactly the two newest
#: vectors — the ones a fresh port is most likely to mis-handle. Go, Rust,
#: Java and .NET already floored at 61; these three lagged, which made the
#: strictness of the check depend on which language you read.
MIN_VECTORS = 61


def _load_vectors() -> List[Dict[str, Any]]:
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        corpus = json.load(handle)
    assert corpus["version"] == 1, corpus.get("version")
    vectors: List[Dict[str, Any]] = corpus["vectors"]
    return vectors


def _run(vector_input: Dict[str, Any]) -> ChatlySignatureResult:
    """Map the corpus's camelCase input onto this SDK's keyword arguments.

    Only keys PRESENT in the vector are passed, so an absent ``v2`` exercises
    the real default rather than a value this harness chose.
    """
    kwargs: Dict[str, Any] = {}
    optional = {
        "method": "method",
        "path": "path",
        "v2": "v2",
        "allowUnprotectedReplay": "allow_unprotected_replay",
        "toleranceSeconds": "tolerance_seconds",
        "nowMs": "now_ms",
    }
    for camel, snake in optional.items():
        if camel in vector_input:
            kwargs[snake] = vector_input[camel]
    known = set(optional) | {"surface", "body", "headers", "secret"}
    unknown = set(vector_input) - known
    # A corpus field this harness does not map would be silently dropped, and
    # the vector would then test something other than what it says.
    assert not unknown, f"unmapped corpus input field(s): {sorted(unknown)}"
    return verify_chatly_signature(
        vector_input["surface"],
        vector_input["body"],
        vector_input["headers"],
        vector_input["secret"],
        **kwargs,
    )


class CorpusVectors(unittest.TestCase):
    def test_corpus_has_at_least_the_floor(self) -> None:
        self.assertGreaterEqual(len(_load_vectors()), MIN_VECTORS)

    def test_every_vector(self) -> None:
        vectors = _load_vectors()
        self.assertGreaterEqual(len(vectors), MIN_VECTORS)
        for vector in vectors:
            with self.subTest(vector["name"]):
                expect = vector["expect"]
                result = _run(vector["input"])
                self.assertEqual(result.ok, expect["ok"], result.message)
                self.assertEqual(bool(result), expect["ok"])
                self.assertEqual(result.surface, expect["surface"])
                if expect["ok"]:
                    self.assertEqual(result.base, expect["base"])
                    self.assertEqual(result.secret_index, expect["secretIndex"])
                    self.assertEqual(result.timestamp_ms, expect["timestampMs"])
                    self.assertIsNone(result.reason)
                    self.assertIsNone(result.message)
                else:
                    self.assertEqual(result.reason, expect["reason"], result.message)
                    self.assertIn(result.reason, CHATLY_SIGNATURE_FAILURES)
                    self.assertIsInstance(result.message, str)
                    self.assertTrue(result.message and result.message.strip())


# A known-good request, used as the base the garbage tests mutate, so each
# one changes exactly one thing.
_SECRET = "whsec_python_secret"
_BODY = '{"id":"evt_1"}'
_T = "1760000000"
_NOW_MS = 1760000000000


def _good_header(secret: str = _SECRET, body: bytes = _BODY.encode()) -> str:
    digest = hmac.new(secret.encode(), _T.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"t={_T},v1={digest}"


class NeverRaises(unittest.TestCase):
    """Garbage in, ``ok=False`` out — a verifier that raises is an accepted webhook."""

    def _check_refused(self, result: Any) -> None:
        self.assertIsInstance(result, ChatlySignatureResult)
        self.assertFalse(result.ok)
        self.assertFalse(result)
        self.assertIn(result.reason, CHATLY_SIGNATURE_FAILURES)
        self.assertTrue(result.message)

    def test_the_baseline_verifies(self) -> None:
        # Without this, every refusal below could be refusing for a reason
        # unrelated to the garbage it was handed.
        result = verify_chatly_signature(
            "event_webhook", _BODY, {"x-livechat-signature": _good_header()}, _SECRET,
            now_ms=_NOW_MS,
        )
        self.assertTrue(result.ok, result.message)
        self.assertTrue(result)

    def test_a_nan_tolerance_refuses_even_a_fresh_request(self) -> None:
        # `drift > nan` is False, so a tolerance parsed from an unset setting
        # used to switch the freshness check OFF. A fresh request, so "refuse"
        # and "accept" give different answers; sdk-node refuses too.
        for now in (_NOW_MS, _NOW_MS + 365 * 24 * 3600 * 1000):
            result = verify_chatly_signature(
                "event_webhook", _BODY, {"x-livechat-signature": _good_header()}, _SECRET,
                tolerance_seconds=float("nan"), now_ms=now,
            )
            self.assertEqual(result.reason, "timestamp_outside_tolerance")

    def test_bytes_bytearray_memoryview_bodies_verify(self) -> None:
        raw = _BODY.encode()
        for body in (raw, bytearray(raw), memoryview(raw)):
            with self.subTest(type(body).__name__):
                result = verify_chatly_signature(
                    "event_webhook", body, {"x-livechat-signature": _good_header()}, _SECRET,
                    now_ms=_NOW_MS,
                )
                self.assertTrue(result.ok, result.message)

    def test_a_parsed_dict_body_is_refused(self) -> None:
        result = verify_chatly_signature(
            "event_webhook", json.loads(_BODY), {"x-livechat-signature": _good_header()},
            _SECRET, now_ms=_NOW_MS,
        )
        self._check_refused(result)
        self.assertEqual(result.reason, "signature_mismatch")
        self.assertIn("dict", result.message or "")

    def test_none_body_is_refused(self) -> None:
        self._check_refused(
            verify_chatly_signature(
                "event_webhook", None, {"x-livechat-signature": _good_header()},  # type: ignore[arg-type]
                _SECRET, now_ms=_NOW_MS,
            )
        )

    def test_none_and_non_mapping_headers(self) -> None:
        for headers in (None, [], "x-livechat-signature: t=1", 42, object()):
            with self.subTest(repr(headers)):
                result = verify_chatly_signature(
                    "event_webhook", _BODY, headers, _SECRET, now_ms=_NOW_MS,  # type: ignore[arg-type]
                )
                self._check_refused(result)
                self.assertEqual(result.reason, "missing_signature_header")

    def test_non_string_header_values(self) -> None:
        for value in (42, b"t=1,v1=00", {"t": _T}, 1.5, True):
            with self.subTest(repr(value)):
                result = verify_chatly_signature(
                    "event_webhook", _BODY, {"x-livechat-signature": value}, _SECRET,  # type: ignore[dict-item]
                    now_ms=_NOW_MS,
                )
                self._check_refused(result)
                self.assertEqual(result.reason, "malformed_signature_header")

    def test_non_string_timestamp_header_value(self) -> None:
        result = verify_chatly_signature(
            "customer_card", _BODY,
            {"x-chatly-signature": "sha256=" + "0" * 64, "x-chatly-timestamp": 1760000000000},  # type: ignore[dict-item]
            _SECRET, now_ms=_NOW_MS,
        )
        self._check_refused(result)
        self.assertEqual(result.reason, "malformed_timestamp")

    def test_a_garbage_second_value_still_counts_as_a_duplicate(self) -> None:
        result = verify_chatly_signature(
            "event_webhook", _BODY, {"x-livechat-signature": [_good_header(), 7]},  # type: ignore[list-item]
            _SECRET, now_ms=_NOW_MS,
        )
        self._check_refused(result)
        self.assertEqual(result.reason, "duplicate_signature_header")

    def test_secret_none_and_other_non_secrets(self) -> None:
        for secret in (None, 42, b"whsec", {"k": "v"}, [], [None, 3], ("",)):
            with self.subTest(repr(secret)):
                result = verify_chatly_signature(
                    "event_webhook", _BODY, {"x-livechat-signature": _good_header()},
                    secret,  # type: ignore[arg-type]
                    now_ms=_NOW_MS,
                )
                self._check_refused(result)
                self.assertEqual(result.reason, "missing_secret")

    def test_a_tuple_of_secrets_keeps_the_callers_index(self) -> None:
        result = verify_chatly_signature(
            "event_webhook", _BODY, {"x-livechat-signature": _good_header()},
            (None, "", "nope", _SECRET),  # type: ignore[arg-type]
            now_ms=_NOW_MS,
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.secret_index, 3)

    def test_non_string_and_unhashable_surfaces(self) -> None:
        for surface in (None, 7, ["event_webhook"], {"a": 1}, "EVENT_WEBHOOK", "__class__"):
            with self.subTest(repr(surface)):
                result = verify_chatly_signature(
                    surface, _BODY, {"x-livechat-signature": _good_header()}, _SECRET,  # type: ignore[arg-type]
                    now_ms=_NOW_MS,
                )
                self._check_refused(result)
                self.assertEqual(result.reason, "unknown_surface")
                self.assertIsInstance(result.surface, str)

    def test_garbage_method_path_and_now(self) -> None:
        for kwargs in (
            {"method": 1, "path": 2},
            {"method": None, "path": ["/x"]},
            {"now_ms": "soon"},
            {"tolerance_seconds": "300"},
            {"v2": 12},
        ):
            with self.subTest(repr(kwargs)):
                result = verify_chatly_signature(
                    "unified_v2", _BODY, {"x-chatly-signature-v2": _good_header()}, _SECRET,
                    **kwargs,  # type: ignore[arg-type]
                )
                self._check_refused(result)

    def test_lone_surrogates_and_unicode_digits(self) -> None:
        # A JSON decoder produces a lone surrogate from "\\ud800", and
        # str.encode("utf-8") raises on it. Arabic-Indic digits are `\\d` in
        # Python and `int()` accepts them; they are not a timestamp.
        self._check_refused(
            verify_chatly_signature(
                "event_webhook", "\ud800", {"x-livechat-signature": _good_header()}, "\udfff",
                now_ms=_NOW_MS,
            )
        )
        result = verify_chatly_signature(
            "event_webhook", _BODY,
            {"x-livechat-signature": "t=١٧٦٠,v1=" + "0" * 64},
            _SECRET, now_ms=_NOW_MS,
        )
        self._check_refused(result)
        self.assertEqual(result.reason, "malformed_timestamp")

    def test_a_trailing_newline_does_not_sneak_past_the_digit_check(self) -> None:
        # Python's `$` matches before a final "\\n"; `fullmatch` does not. The
        # newline is inside the value (not trimmable) because it precedes ",".
        result = verify_chatly_signature(
            "event_webhook", _BODY, {"x-livechat-signature": f"t={_T}\n\u0085,v1=" + "0" * 64},
            _SECRET, now_ms=_NOW_MS,
        )
        self._check_refused(result)
        self.assertEqual(result.reason, "malformed_timestamp")

    def test_a_huge_timestamp_is_refused_not_raised(self) -> None:
        # 5,000 digits is past Python's int-max-str-digits guard, where a bare
        # int() raises ValueError.
        for digits in ("9" * 17, "9" * 40, "9" * 5000, "0" * 17 + "9007199254740992"):
            with self.subTest(len(digits)):
                result = verify_chatly_signature(
                    "event_webhook", _BODY,
                    {"x-livechat-signature": f"t={digits},v1=" + "0" * 64},
                    _SECRET, now_ms=_NOW_MS,
                )
                self._check_refused(result)
                self.assertEqual(result.reason, "malformed_timestamp")

    def test_the_bound_is_max_safe_integer_exactly(self) -> None:
        # 2**53 - 1 is a timestamp (just a very distant one); 2**53 is not.
        # The reference is JavaScript's Number.isSafeInteger, and this pins
        # the edge so the two cannot drift by one.
        def reason(t: str) -> Any:
            return verify_chatly_signature(
                "canvas_step", _BODY,
                {"x-chatly-canvas-signature": "sha256=" + "0" * 64, "x-chatly-canvas-ts": t},
                _SECRET, now_ms=_NOW_MS,
            ).reason

        self.assertEqual(reason("9007199254740991"), "timestamp_outside_tolerance")
        self.assertEqual(reason("9007199254740992"), "malformed_timestamp")

    def test_leading_zeros_do_not_count_toward_the_bound(self) -> None:
        # Padded, but a real timestamp: the reference reads its VALUE. The
        # signed string keeps the raw text, so the digest is over the zeros.
        padded = "0" * 20 + _T
        digest = hmac.new(
            _SECRET.encode(), padded.encode() + b"." + _BODY.encode(), hashlib.sha256
        ).hexdigest()
        result = verify_chatly_signature(
            "event_webhook", _BODY, {"x-livechat-signature": f"t={padded},v1={digest}"},
            _SECRET, now_ms=_NOW_MS,
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.timestamp_ms, _NOW_MS)

    def test_a_headers_object_that_raises(self) -> None:
        class Hostile:
            def items(self) -> Any:
                raise RuntimeError("boom")

        result = verify_chatly_signature("event_webhook", _BODY, Hostile(), _SECRET)  # type: ignore[arg-type]
        self._check_refused(result)
        self.assertEqual(result.reason, "signature_mismatch")


class PublicSurface(unittest.TestCase):
    def test_exports(self) -> None:
        for name in (
            "verify_chatly_signature",
            "ChatlySignatureResult",
            "SurfaceSpec",
            "CHATLY_SIGNATURE_FAILURES",
            "CHATLY_SIGNATURE_SURFACES",
            "CHATLY_SIGNATURE_TOLERANCE_SECONDS",
            "CHATLY_V2_SIGNATURE_HEADER",
        ):
            self.assertIn(name, chatly.__all__)
            self.assertTrue(hasattr(chatly, name))
        self.assertEqual(chatly.CHATLY_SIGNATURE_TOLERANCE_SECONDS, 300)
        self.assertEqual(chatly.CHATLY_V2_SIGNATURE_HEADER, "x-chatly-signature-v2")

    def test_the_surface_list_is_the_eight(self) -> None:
        self.assertEqual(
            list(CHATLY_SIGNATURE_SURFACES),
            [
                "unified_v2",
                "agent_delivery",
                "event_webhook",
                "ai_tool_call",
                "canvas_step",
                "customer_card",
                "workflow_webhook",
                "workflow_webhook_legacy",
            ],
        )
        self.assertEqual(len(CHATLY_SIGNATURE_FAILURES), 11)

    def test_the_table_is_read_only(self) -> None:
        with self.assertRaises(TypeError):
            CHATLY_SIGNATURE_SURFACES["evil"] = CHATLY_SIGNATURE_SURFACES["event_webhook"]  # type: ignore[index]

    def test_every_surface_has_a_vector_that_verifies(self) -> None:
        # A surface added to the table with no passing vector is a surface
        # nothing has ever proven works.
        verified = {
            v["expect"]["surface"] for v in _load_vectors() if v["expect"]["ok"]
        }
        self.assertEqual(verified, set(CHATLY_SIGNATURE_SURFACES))


if __name__ == "__main__":
    unittest.main()
