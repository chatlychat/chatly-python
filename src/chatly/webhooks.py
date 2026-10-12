"""Webhook signature verification. Contract §6.

The platform signs every delivery with a header::

    x-livechat-signature: t=<unix seconds>,v1=<hex>

``v1`` is HMAC-SHA256 over the exact bytes ``<t>.<raw body>``. The timestamp
is bound INTO the digest — that is what makes the replay window enforceable
at all. Signing the body alone would let anyone replay a captured delivery
forever, because nothing in the signed material says when it was sent.

Two failure modes have actually shipped, and both are designed against here:

* **An implementation that HMAC'd the body alone** rejected 100% of genuine
  deliveries. The producer has always signed ``<t>.<body>``. The test for the
  exact construction (:func:`verify_webhook_signature` against the pinned
  vector in ``tests/test_contract.py``) exists to keep that from recurring.

* **A verifier that raises** is an accepted webhook in a handler that forgot
  to catch. This function returns ``False`` for every malformed input and
  raises nothing — a missing field, a non-numeric ``t``, a header that is not
  a string, an odd-length hex digest, a stale timestamp. If it ever raises,
  that is a bug in this function.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Dict, Optional, Union

#: Default freshness window for ``t``, in seconds. Contract §6.
DEFAULT_TOLERANCE_SECONDS = 300

#: The header the platform sends. Not ``x-chatly-signature`` — a published
#: README named that one, and a customer's handler read a header that is
#: never present, so every delivery failed verification.
SIGNATURE_HEADER = "x-livechat-signature"

Body = Union[str, bytes, bytearray, memoryview]


def _as_bytes(body: object) -> Optional[bytes]:
    """Coerce a body to bytes, or ``None`` if it is not something we can sign.

    Typed as ``object`` rather than :data:`Body` on purpose: a type checker
    would call the final branch unreachable, and it is not. This function is
    called from a webhook handler, which is usually untyped glue reading a
    framework's request object, and the most likely wrong argument is the
    *parsed* body — a ``dict``. That has to come back ``False``, not raise.
    """
    if isinstance(body, str):
        return body.encode("utf-8")
    if isinstance(body, (bytes, bytearray, memoryview)):
        return bytes(body)
    return None


def parse_signature_header(header: str) -> Dict[str, str]:
    """Split ``t=…,v1=…`` into a dict. Unknown keys are kept, not an error.

    The platform may add a ``v2`` scheme beside ``v1`` one day, the way other
    products have; a parser that rejects anything it does not recognise would
    start failing on that day for no reason.
    """
    parts: Dict[str, str] = {}
    for chunk in header.split(","):
        eq = chunk.find("=")
        if eq <= 0:
            continue
        parts[chunk[:eq].strip()] = chunk[eq + 1 :].strip()
    return parts


def verify_webhook_signature(
    body: Body,
    signature_header: str,
    secret: str,
    tolerance: float = DEFAULT_TOLERANCE_SECONDS,
    *,
    now: Optional[float] = None,
) -> bool:
    """Is this delivery genuine, recent, and signed with ``secret``?

    Args:
        body: **the exact bytes you received.** Pass the raw request body.
            Re-serialising parsed JSON reorders keys and changes whitespace,
            and the digest will not match — so take the raw body from your
            framework before anything parses it (Flask:
            ``request.get_data()``; Django: ``request.body``; FastAPI:
            ``await request.body()``).
        signature_header: the value of the ``x-livechat-signature`` header.
        secret: the endpoint's ``whsec_…`` signing secret.
        tolerance: how far ``t`` may be from now, in seconds, in either
            direction. Pass ``float("inf")`` only when re-verifying an
            archived delivery, where the age is the point.
        now: unix seconds, for tests and for replaying an archive against a
            fixed clock. Defaults to the system clock.

    Returns:
        ``True`` only if the header parses, ``t`` is within ``tolerance``, and
        ``v1`` equals HMAC-SHA256(``secret``, ``f"{t}.{body}"``). ``False``
        for everything else, including every malformed input. Never raises.

    Comparison is constant-time (:func:`hmac.compare_digest`), and the lengths
    are compared first — on raw bytes a mismatched length can make a
    constant-time compare throw, and a verifier that throws is a webhook that
    gets accepted by a handler without a ``try``.
    """
    try:
        raw = _as_bytes(body)
        if raw is None:
            return False
        if not isinstance(signature_header, str) or signature_header == "":
            return False
        if not isinstance(secret, str) or secret == "":
            # Cannot verify anything without a key. Returning False rather
            # than raising keeps the never-throws guarantee; a caller who
            # forgot to configure the secret sees every delivery rejected,
            # which is the safe direction to fail.
            return False

        parts = parse_signature_header(signature_header)
        raw_ts = parts.get("t")
        tag = parts.get("v1")
        if raw_ts is None or tag is None or raw_ts == "" or tag == "":
            return False

        try:
            # int(), not float(): `t=1.7e9` and `t=nan` are not timestamps
            # this producer emits, and accepting them widens the window.
            issued_at = int(raw_ts)
        except (TypeError, ValueError):
            return False

        current = time.time() if now is None else float(now)
        if abs(current - issued_at) > float(tolerance):
            return False

        expected = hmac.new(
            secret.encode("utf-8"),
            raw_ts.encode("ascii") + b"." + raw,
            hashlib.sha256,
        ).hexdigest()

        # Compare the hex text, lowercased: `bytes.fromhex` on an attacker's
        # value is one more thing that can raise, and hex is already a
        # fixed-length encoding so comparing it leaks nothing extra.
        candidate = tag.lower()
        if len(candidate) != len(expected):
            return False
        return hmac.compare_digest(candidate, expected)
    except Exception:  # noqa: BLE001 - the never-throws guarantee is the point
        return False


__all__ = [
    "DEFAULT_TOLERANCE_SECONDS",
    "SIGNATURE_HEADER",
    "parse_signature_header",
    "verify_webhook_signature",
]
