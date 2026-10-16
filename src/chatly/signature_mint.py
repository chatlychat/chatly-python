"""Minting a v2 signature — the other direction from :mod:`chatly.signatures`.

A port of ``signChatlyV2`` / ``chatlyV2BaseString`` from the Node SDK
(``packages/sdk-node/src/signature-mint.ts`` in the monorepo), which is the
reference: where this file and that one disagree about the bytes, that one is
right and this one has a bug.

Verifying is what a customer's handler does, and it lives next door. Minting
is what a TEST does — standing up a fake Chatly and firing a signed request at
your own endpoint — and until this module existed a Python integrator writing
that test had to re-derive ``<t>.<METHOD>.<path>.<rawBody>`` by hand from the
documentation. A hand-derived base string is the one thing a signature test
must not have: get it wrong in the same way in both the test and nothing else,
and the test passes while production refuses every delivery. That is not
hypothetical — ``packages/shared`` shipped the mirror image of it once, a
header in milliseconds over a seconds value, and a verifier following our own
published docs refused 100% of real traffic.

Its own module because :mod:`chatly.signatures` is 630 lines of the
repository's 650-line ceiling, which is the same reason the Node reference
split it out.

**It is deliberately not exported for signing real outbound traffic.** Nothing
in this package sends a signed request to a customer; Chatly's own producers
are ``packages/shared/src/webhook-signature/v2.ts``. This is here so a test
can mint what Chatly would send.

The marker, which is the whole reason ``base`` has no default
------------------------------------------------------------

``sign_chatly_v2`` emits ``b=t`` for the unified base and ``b=b`` for the body
base, and there is no default: the two constructions are indistinguishable
from the value alone, which is precisely why the marker exists, so a caller
has to say which one it means. An ABSENT marker means the BODY base — every
v2 signature Chatly minted before the marker existed was ``<t>.<rawBody>`` —
and this function never emits an absent one.

The one wire value it cannot produce on its own is the workflow action's
current dual-digest form, ``t=<T>,v1=<target>,v1=<body>`` with no marker. That
is built from two mints by taking the ``v1=`` field out of each, which is
exactly what the producer does
(``digestOf`` in ``apps/worker/src/handlers/action-handlers/fire-webhook.ts``);
``tests/test_signature_mint.py`` does the same and verifies the result.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional, Union

from ._signature_text import _utf8

#: Which string a v2 signature was taken over. ``"target"`` is the unified
#: base ``<t>.<METHOD>.<path>.<rawBody>``; ``"body"`` is ``<t>.<rawBody>``.
CHATLY_V2_MINT_BASES = ("target", "body")

Body = Union[str, bytes, bytearray, memoryview]


def _body_bytes(body: Body) -> bytes:
    if isinstance(body, str):
        return _utf8(body)
    if isinstance(body, (bytes, bytearray, memoryview)):
        return bytes(body)
    raise TypeError(
        f"body must be str or bytes, not {type(body).__name__} — pass the exact bytes "
        "that will be sent, not a parsed object"
    )


def _checked_timestamp(timestamp_seconds: int) -> str:
    # `bool` is an `int` in Python and `True` would sign "1". A float is
    # refused rather than rendered, because `str(1760000000.0)` is
    # "1760000000.0" and the receiver's `t` is a run of digits: the digest
    # would be over text no verifier can reproduce, and it would arrive as
    # "signature mismatch" with nothing pointing at the cause.
    if isinstance(timestamp_seconds, bool) or not isinstance(timestamp_seconds, int):
        raise TypeError(
            "timestamp_seconds must be an int of unix SECONDS, not "
            f"{type(timestamp_seconds).__name__}"
        )
    if timestamp_seconds < 0:
        raise ValueError("timestamp_seconds must not be negative")
    return str(timestamp_seconds)


def chatly_v2_base_string(
    *,
    base: str,
    timestamp_seconds: int,
    body: Body,
    method: Optional[str] = None,
    path: Optional[str] = None,
) -> bytes:
    """The exact bytes the MAC is taken over, so a test can pin them.

    ``base="target"`` gives ``<t>.<METHOD>.<path>.<rawBody>`` and
    ``base="body"`` gives ``<t>.<rawBody>``. The method is upper-cased, as the
    verifier upper-cases it; ``path`` is ``pathname + query`` of the request
    line and never the scheme or host.

    It returns **bytes** where the Node reference returns a string, because
    the MAC is over bytes and a body is not always valid UTF-8 text. For a
    ``str`` body the two are the same thing: this is
    ``chatlyV2BaseString(...).encode("utf-8")``.

    Raises:
        ValueError: if ``base`` is not one of :data:`CHATLY_V2_MINT_BASES`, or
            if ``base="target"`` and either ``method`` or ``path`` is missing
            or empty. Both are refusals rather than a guess: an empty method
            or path signs a string the receiver cannot reproduce, which
            reaches them as "signature mismatch" and sends them hunting their
            own secret. TypeScript's types make the first unreachable in the
            reference, and every production caller there refuses before
            minting — ``chatlyV2SigningPath`` returns ``None`` on a URL that
            will not parse and the CLI stops — so this raises where the
            reference merely never gets the chance to.
        TypeError: if ``timestamp_seconds`` is not an int, or ``body`` is
            neither ``str`` nor bytes.
    """
    if base not in CHATLY_V2_MINT_BASES:
        raise ValueError(
            f'base must be "target" or "body", not {base!r}. There is no default: the two '
            "constructions are indistinguishable without the marker this emits."
        )
    t = _checked_timestamp(timestamp_seconds)
    raw = _body_bytes(body)
    if base == "body":
        return _utf8(t) + b"." + raw
    if not isinstance(method, str) or method == "":
        raise ValueError('base="target" signs the METHOD, so method is required')
    if not isinstance(path, str) or path == "":
        raise ValueError(
            'base="target" signs the path, so path is required — pathname + query of the '
            "request line, not the scheme or host"
        )
    return _utf8(t) + b"." + _utf8(method.upper()) + b"." + _utf8(path) + b"." + raw


def sign_chatly_v2(
    *,
    base: str,
    secret: Union[str, bytes],
    timestamp_seconds: int,
    body: Body,
    method: Optional[str] = None,
    path: Optional[str] = None,
) -> str:
    """The ``x-chatly-signature-v2`` value for one request: ``t=…,v1=…,b=…``.

    .. code-block:: python

        header = chatly.sign_chatly_v2(
            base="target",
            secret=SECRET,
            timestamp_seconds=1760000000,
            method="POST",
            path="/hooks/chatly",
            body=raw,
        )
        # t=1760000000,v1=<64 hex>,b=t

        result = chatly.verify_chatly_signature(
            "unified_v2", raw, {"x-chatly-signature-v2": header}, SECRET,
            method="POST", path="/hooks/chatly",
        )
        assert result.ok

    Args:
        base: ``"target"`` for the unified base, ``"body"`` for ``<t>.<body>``.
            No default — see the module docstring.
        secret: the surface's signing secret. ``bytes`` is accepted because
            HMAC keys are bytes; a ``str`` is encoded as UTF-8, matching the
            verifier.
        timestamp_seconds: unix **seconds**, never milliseconds. Two surfaces
            send millisecond timestamps in their LEGACY headers; the v2 header
            is seconds on every one of them.
        body: the exact bytes that will be sent.
        method, path: required for ``base="target"``.

    Raises:
        ValueError, TypeError: see :func:`chatly_v2_base_string`. An empty
            secret is refused too — an empty string is a perfectly valid HMAC
            key, which is the problem, and the likeliest cause is an
            environment variable that never got set.
    """
    key = _utf8(secret) if isinstance(secret, str) else bytes(secret)
    if key == b"":
        raise ValueError("secret must not be empty")
    message = chatly_v2_base_string(
        base=base, timestamp_seconds=timestamp_seconds, body=body, method=method, path=path
    )
    digest = hmac.new(key, message, hashlib.sha256).hexdigest()
    marker = "t" if base == "target" else "b"
    return f"t={timestamp_seconds},v1={digest},b={marker}"


__all__ = [
    "CHATLY_V2_MINT_BASES",
    "chatly_v2_base_string",
    "sign_chatly_v2",
]
