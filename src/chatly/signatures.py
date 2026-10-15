"""One verifier for every signature Chatly puts on an outbound request.

A port of ``verifyChatlySignature`` from the Node SDK
(``packages/sdk-node/src/signatures.ts`` and ``signature-table.ts`` in the
monorepo). The two are held to the same behaviour by a shared corpus of
vectors, ``tests/signature_vectors.json``, which every SDK runs verbatim — so
when this file and the TypeScript disagree about an input, that corpus is the
referee, and a vector it does not yet have is the thing to add.

Why it takes a ``surface``
--------------------------

Because the header name does not determine the construction. Three surfaces
send ``x-chatly-signature`` and sign three different strings, and two of the
eight send MILLISECONDS. The caller knows which route they are terminating;
this function cannot, and a verifier that guessed from the header could be
pointed at the wrong construction while looking completely correct.

The table — which header, which base string, which unit — is
:mod:`chatly.signature_table`, re-exported here, along with the unit trap
it exists to prevent.

The unified v2 construction
---------------------------

``x-chatly-signature-v2: t=<unix seconds>,v1=<hex>[,b=t]`` over
``<t>.<METHOD>.<path>.<rawBody>`` is where every surface is going, sent
alongside each one's legacy header. ``v2=`` chooses how much to insist on it:

* ``"prefer"`` (default) — if the v2 header is present AND ``method`` and
  ``path`` were supplied, verify THAT and nothing else; otherwise verify the
  surface's own legacy construction. A receiver that passes its method and
  path gets the stronger check the day the sender starts emitting v2, with no
  code change.
* ``"require"`` — refuse unless the v2 header is there.
* ``"ignore"`` — the surface's own construction only.

``prefer`` never cross-falls-back: once v2 is chosen, a bad v2 digest is a
refusal, not a reason to try the legacy header. Both headers are minted from
the same secret, so a good legacy digest beside a bad v2 one is either
tampering or a sender bug, and accepting it would hide both.

``workflow_webhook`` is the one collision: it ALREADY sends
``x-chatly-signature-v2``, over ``<t>.<body>`` — the header predates the
unified base. So it accepts both bases, and the value's ``b=`` marker (``t``
for target, ``b`` for body, absent meaning "minted before the marker
existed") NARROWS the candidates. A marker never widens them, because anyone
on the wire can write one.

Why it returns a reason instead of a bool
-----------------------------------------

:func:`chatly.verify_webhook_signature` returns ``False`` for nine distinct
failures, and an integrator debugging a rejected delivery cannot tell "your
clock is wrong" from "your secret is wrong" from "you passed the parsed
body". Each of those is a support ticket. This returns a
:class:`ChatlySignatureResult` with a stable ``reason`` to branch on and a
``message`` written to be printed.

Why it never raises
-------------------

CONTRACT.md §6: a verifier that raises is an accepted webhook in a handler
that forgot to catch. Every input — a missing header, a duplicated header, a
non-hex digest, an unknown surface, ``secret=None``, a parsed ``dict`` where
the raw body belongs — comes back ``ok=False``. There is a catch-all as a
last line of defence, mapped to ``signature_mismatch``; if it ever fires,
that is a bug in this module.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Union

from .signature_table import (
    CHATLY_SIGNATURE_FAILURES,
    CHATLY_SIGNATURE_SURFACES,
    CHATLY_SIGNATURE_TOLERANCE_SECONDS,
    CHATLY_V2_SIGNATURE_HEADER,
    IN_SIGNATURE,
    SurfaceSpec,
)
from ._signature_text import (
    _DIGITS,
    _HEX_SHA256,
    _MAX_SAFE_INTEGER,
    _has_target,
    _header_values,
    _parse_tv1,
    _preview,
    _secrets_from,
    _trim,
    _utf8,
)


@dataclass(frozen=True)
class ChatlySignatureResult:
    """The answer from :func:`verify_chatly_signature`.

    On success ``ok`` is True and ``timestamp_ms``, ``base`` and
    ``secret_index`` are set; ``reason`` and ``message`` are ``None``. On
    failure ``ok`` is False, ``reason`` is one of
    :data:`CHATLY_SIGNATURE_FAILURES` and ``message`` is a sentence written to
    be printed to whoever has to fix it.

    ``surface`` is what actually verified (or was being verified when it
    failed) — ``"unified_v2"`` when the v2 header was preferred over the
    surface asked for.

    The result is truthy exactly when ``ok`` is. A frozen dataclass is
    otherwise ALWAYS truthy, and the obvious migration from
    :func:`verify_webhook_signature`, which returns a bool, is
    ``if not chatly.verify_chatly_signature(...): return 401`` — which would
    have accepted every forgery. ``__bool__`` makes that line correct.
    """

    ok: bool
    surface: str
    reason: Optional[str] = None
    message: Optional[str] = None
    #: When the sender says it signed, in unix MILLISECONDS — normalised, so a
    #: seconds surface and a milliseconds surface are comparable. ``None`` on
    #: ``workflow_webhook_legacy``, which sends no timestamp.
    timestamp_ms: Optional[int] = None
    #: Which string the matching MAC was taken over.
    base: Optional[str] = None
    #: Index into the ``secret`` list the CALLER passed (``0`` for a single
    #: secret). During a rotation this is how you learn the old secret is no
    #: longer in use.
    secret_index: Optional[int] = None

    def __bool__(self) -> bool:
        return self.ok


Body = Union[str, bytes, bytearray, memoryview]
HeaderValue = Union[str, Sequence[str], None]
Secret = Union[str, Sequence[str]]

def _fail(surface: str, reason: str, message: str) -> ChatlySignatureResult:
    return ChatlySignatureResult(ok=False, surface=surface, reason=reason, message=message)



@dataclass(frozen=True)
class _Input:
    """The arguments, carried together so the v2 delegation can copy them.

    Every field is ``Any`` on purpose (this file's one use of it): the public
    signature states what a caller SHOULD pass, but this function is called
    from untyped webhook glue and must survive whatever actually arrives, so
    each field is type-checked at runtime where it is read, not trusted here.
    """

    surface: Any
    body: Any
    headers: Any
    secret: Any
    tolerance_seconds: Any
    method: Any
    path: Any
    v2: Any
    allow_unprotected_replay: Any
    now_ms: Any


def _apply_v2_policy(inp: _Input) -> Optional[ChatlySignatureResult]:
    """The v2 decision, taken before anything is parsed.

    Returns a result when it has answered the whole question — by delegating
    to ``unified_v2`` or by refusing — and ``None`` when verification should
    continue on the surface asked for.
    """
    surface: str = inp.surface
    spec = CHATLY_SIGNATURE_SURFACES[surface]
    policy = inp.v2 if inp.v2 is not None else "prefer"
    if policy == "ignore" or surface == "unified_v2":
        return None
    # A surface whose OWN header is the v2 header handles the two bases in
    # its candidate list instead; there is nothing to delegate to.
    if spec.signature_header == CHATLY_V2_SIGNATURE_HEADER:
        return None

    present = len(_header_values(inp.headers, CHATLY_V2_SIGNATURE_HEADER)) > 0
    if policy == "require" and not present:
        return _fail(
            surface,
            "missing_signature_header",
            f'v2="require" was asked for and this request carries no '
            f"{CHATLY_V2_SIGNATURE_HEADER} header. {spec.signature_header} alone means "
            "the sender has not moved to the unified construction yet — use the "
            'default v2="prefer" until it has.',
        )
    if not present:
        return None
    if not _has_target(inp.method, inp.path):
        if policy == "require":
            return _fail(
                surface,
                "missing_request_target",
                f"The unified {CHATLY_V2_SIGNATURE_HEADER} signs "
                "<t>.<METHOD>.<path>.<rawBody>, so both method and path are required "
                "to verify it. path is pathname + query of the request as it arrived "
                "— not the host, not the scheme.",
            )
        # `prefer` with no target to verify against: the legacy header is
        # still being sent beside it, so fall through rather than refuse a
        # request the caller CAN verify.
        return None

    result = _verify(dataclasses.replace(inp, surface="unified_v2", v2="ignore"))
    if result.ok:
        return result
    return _fail(
        "unified_v2",
        result.reason or "signature_mismatch",
        f"{result.message} (This request carried {CHATLY_V2_SIGNATURE_HEADER}, so it "
        f"was verified as the unified v2 construction rather than as {surface}. Pass "
        f'v2="ignore" to verify {spec.signature_header} instead.)',
    )


def _candidate_bases(
    inp: _Input, spec: SurfaceSpec, marker: Optional[str]
) -> Union[List[str], ChatlySignatureResult]:
    """Which strings the MAC may have been taken over, most specific first.

    More than one only on ``workflow_webhook``. The ``b=`` marker is read
    only off the v2 header (no legacy header carries one) and only ever
    NARROWS: an absent or unrecognised marker changes nothing, because every
    v2 value minted before the marker existed has none. What it buys is the
    error — the day the workflow sender moves to ``b=t``, a receiver passing
    no method/path gets ``missing_request_target``, not a mismatch that sends
    them hunting their secret.
    """
    surface: str = inp.surface
    policy = inp.v2 if inp.v2 is not None else "prefer"
    from_v2 = spec.signature_header == CHATLY_V2_SIGNATURE_HEADER
    if from_v2 and marker == "b" and (spec.base == "target" or policy == "require"):
        if surface == "unified_v2":
            tail = (
                'unified_v2 accepts only b=t. Verify it with surface "workflow_webhook", '
                "which accepts both."
            )
        else:
            tail = 'v2="require" accepts only the unified base (b=t).'
        return _fail(
            surface,
            "signature_mismatch",
            f"This {CHATLY_V2_SIGNATURE_HEADER} is marked b=b: it was signed over "
            "<t>.<rawBody>, the workflow action's pre-unified base. " + tail,
        )
    if not spec.also_accepts_target_base or policy == "ignore":
        return [spec.base]
    if marker == "t":
        return ["target"]
    if marker == "b" or not _has_target(inp.method, inp.path):
        return [spec.base]
    # `require` on this surface means the unified base and nothing else.
    return ["target"] if policy == "require" else ["target", spec.base]


def _verify(inp: _Input) -> ChatlySignatureResult:
    raw_surface = inp.surface
    # A non-str surface (None, a list) is refused before the dict lookup,
    # where an unhashable one would raise.
    spec = (
        CHATLY_SIGNATURE_SURFACES.get(raw_surface) if isinstance(raw_surface, str) else None
    )
    if spec is None:
        return _fail(
            str(raw_surface),
            "unknown_surface",
            f'"{raw_surface}" is not a Chatly signature surface. One of: '
            f"{', '.join(CHATLY_SIGNATURE_SURFACES)}.",
        )
    surface: str = raw_surface

    secrets = _secrets_from(inp.secret)
    if not secrets:
        return _fail(
            surface,
            "missing_secret",
            f"No secret given for {surface}. Each surface has its own secret — "
            f"{spec.describe}. A secret from another surface will never verify.",
        )

    # `is not True`, not truthiness: accepting an unbounded replay has to be
    # a deliberate `True`, not whatever non-empty string a config loader
    # happened to produce.
    if surface == "workflow_webhook_legacy" and inp.allow_unprotected_replay is not True:
        return _fail(
            surface,
            "replay_unprotected",
            "The legacy workflow header signs the body with no timestamp, so a captured "
            "request verifies forever and nothing here can bound a replay. The same call "
            'also sends x-chatly-signature-v2 — verify that instead, with surface '
            '"workflow_webhook". If you must accept the legacy header, pass '
            "allow_unprotected_replay=True and make the endpoint idempotent.",
        )

    via_v2 = _apply_v2_policy(inp)
    if via_v2 is not None:
        return via_v2

    # -- The digest header ---------------------------------------------------
    sig_headers = _header_values(inp.headers, spec.signature_header)
    if not sig_headers:
        return _fail(
            surface,
            "missing_signature_header",
            f"No {spec.signature_header} header. {spec.describe[:1].upper()}"
            f"{spec.describe[1:]} always sends one; if the request carries a differently "
            "named signature header, you have the wrong surface.",
        )
    if len(sig_headers) > 1:
        # Two values means something between Chatly and you merged or
        # injected one, and picking either is a guess. Refuse rather than
        # trial-verify both — trial-verifying lets an attacker who can add a
        # header ride on the genuine one.
        return _fail(
            surface,
            "duplicate_signature_header",
            f"{len(sig_headers)} {spec.signature_header} headers arrived. Chatly sends "
            "exactly one; a proxy merged or added one, and choosing between them would "
            "be a guess.",
        )
    if not isinstance(sig_headers[0], str):
        return _fail(
            surface,
            "malformed_signature_header",
            f"{spec.signature_header} is not a string (got {type(sig_headers[0]).__name__}).",
        )
    raw_signature = _trim(sig_headers[0])

    raw_timestamp: Optional[str] = None
    marker: Optional[str] = None
    if spec.format == "tv1":
        parsed = _parse_tv1(raw_signature)
        if parsed is None:
            return _fail(
                surface,
                "malformed_signature_header",
                f'{spec.signature_header} should be "t=<unix seconds>,v1=<hex>" on '
                f'{surface}; got "{_preview(raw_signature)}".',
            )
        raw_timestamp, digests_hex, marker = parsed
    else:
        if not raw_signature.startswith("sha256="):
            return _fail(
                surface,
                "malformed_signature_header",
                f'{spec.signature_header} should be "sha256=<hex>" on {surface}; got '
                f'"{_preview(raw_signature)}". A "t=…,v1=…" value here means you '
                "have the wrong surface — that is the other signature family.",
            )
        digests_hex = [_trim(raw_signature[len("sha256=") :])]

    for digest_hex in digests_hex:
        # Shape-checked BEFORE decoding, so a garbage digest is reported as
        # malformed rather than reaching the compare and reading as a wrong
        # secret. (`bytes.fromhex` would raise rather than truncate the way
        # Node's decoder does, but the reason has to match across SDKs.)
        if not _HEX_SHA256.fullmatch(digest_hex):
            extra = (
                f" {len(digests_hex)} v1 values arrived; every one has to be well formed."
                if len(digests_hex) > 1
                else ""
            )
            return _fail(
                surface,
                "malformed_signature_header",
                f"A digest in {spec.signature_header} is not 64 hex characters "
                f"(got {len(digest_hex)}).{extra}",
            )

    # -- The timestamp, and its unit -----------------------------------------
    timestamp_ms: Optional[int] = None
    if spec.unit is not None:
        if spec.timestamp_from is not None and spec.timestamp_from != IN_SIGNATURE:
            ts_headers = _header_values(inp.headers, spec.timestamp_from)
            if not ts_headers:
                return _fail(
                    surface,
                    "missing_timestamp",
                    f"No {spec.timestamp_from} header. On {surface} the timestamp travels "
                    "in its own header and is part of the signed string, so it cannot be "
                    "reconstructed.",
                )
            first = ts_headers[0]
            if not isinstance(first, str):
                return _fail(
                    surface,
                    "malformed_timestamp",
                    f"{spec.timestamp_from} is not a string (got {type(first).__name__}).",
                )
            raw_timestamp = _trim(first)
        if raw_timestamp is None or raw_timestamp == "":
            return _fail(surface, "missing_timestamp", f"No timestamp found for {surface}.")
        # `int()` alone would accept "+17", " 17", "1_700" and Arabic-Indic
        # digits. A timestamp is ASCII digits.
        if not _DIGITS.fullmatch(raw_timestamp):
            return _fail(
                surface,
                "malformed_timestamp",
                f'The timestamp on {surface} is not a run of digits: "{_preview(raw_timestamp)}".',
            )
        # Python ints never overflow, so "does not fit the numeric type" is
        # a bound chosen here rather than one the language imposes — and it
        # is the reference's bound, JavaScript's Number.MAX_SAFE_INTEGER, so a
        # 20-digit `t` is malformed in every SDK instead of being "outside
        # tolerance" in this one and "malformed" in the int64 ones. The length
        # check comes first: 3.11+ refuses to parse a string of more than
        # 4,300 digits, and anything over 16 SIGNIFICANT digits is past the
        # bound anyway. Leading zeros are stripped for that count only — the
        # reference's Number("0001760000000") is 1760000000, and the signed
        # string still uses the raw text, zeros and all.
        significant = raw_timestamp.lstrip("0") or "0"
        as_int = int(significant) if len(significant) <= 16 else _MAX_SAFE_INTEGER + 1
        if as_int > _MAX_SAFE_INTEGER:
            return _fail(
                surface,
                "malformed_timestamp",
                f'The timestamp on {surface} is too large to be one: "{_preview(raw_timestamp)}".',
            )
        timestamp_ms = as_int * 1000 if spec.unit == "seconds" else as_int

        tolerance = inp.tolerance_seconds
        if tolerance is None:
            tolerance = CHATLY_SIGNATURE_TOLERANCE_SECONDS
        now_ms = inp.now_ms
        if now_ms is None:
            now_ms = time.time_ns() // 1_000_000
        drift_ms = abs(now_ms - timestamp_ms)
        # `not <=` rather than `>`: exactly the tolerance is inside the window,
        # on every SDK, AND a NaN tolerance refuses — `drift > nan` is False,
        # so a tolerance parsed from an unset setting used to turn the check
        # off. Both directions are refused, and the message says which.
        if not drift_ms <= tolerance * 1000:
            # A stale timestamp is a replay or a slow queue; a FAR-FUTURE one
            # is a sender clock or — far more often — the wrong unit, which
            # lands thousands of years out and reads as "expired" unless
            # something says so.
            drift_years = drift_ms / (1000 * 60 * 60 * 24 * 365)
            unit_hint = (
                f" That is {drift_years:.0f} year(s) out, which is what a wrong UNIT "
                f"looks like: {surface} sends {spec.unit}."
                if drift_years > 1
                else ""
            )
            direction = "in the FUTURE" if timestamp_ms > now_ms else "in the past"
            return _fail(
                surface,
                "timestamp_outside_tolerance",
                f"The timestamp on {surface} is {round(drift_ms / 1000)}s {direction}, "
                f"outside the {tolerance}s tolerance.{unit_hint}",
            )

    # -- The base string, and the compare ------------------------------------
    bases = _candidate_bases(inp, spec, marker)
    if isinstance(bases, ChatlySignatureResult):
        return bases
    method = inp.method
    path = inp.path
    if "target" in bases and not _has_target(method, path):
        return _fail(
            surface,
            "missing_request_target",
            f"{surface} signs <t>.<METHOD>.<path>.<rawBody>, so both method and path are "
            "required. path is pathname + query of the request as Chatly rendered it "
            "— not the host, not the scheme.",
        )

    # The body is checked LAST, after every header-shaped refusal, so the
    # reason for a request that is wrong in two ways is the same reason the
    # other SDKs give. A parsed dict is the likeliest wrong argument here.
    body = inp.body
    if isinstance(body, str):
        body_bytes = _utf8(body)
    elif isinstance(body, (bytes, bytearray, memoryview)):
        body_bytes = bytes(body)
    else:
        return _fail(
            surface,
            "signature_mismatch",
            f"The body is a {type(body).__name__}, not the raw request bytes. Pass the "
            "body exactly as received (Flask: request.get_data(); Django: request.body; "
            "FastAPI: await request.body()) — a parsed and re-serialised body will "
            "never match.",
        )

    given = [bytes.fromhex(h) for h in digests_hex]
    for base in bases:
        if base == "body_only":
            prefix = b""
        elif base == "body":
            # The RAW timestamp text, exactly as received — never re-formatted
            # from the parsed integer, which would drop a leading zero.
            prefix = _utf8(raw_timestamp or "") + b"."
        else:
            prefix = (
                _utf8(raw_timestamp or "") + b"." + _utf8(method.upper()) + b"."
                + _utf8(path) + b"."
            )
        for secret, index in secrets:
            expected = hmac.new(_utf8(secret), prefix + body_bytes, hashlib.sha256).digest()
            for candidate in given:
                # Length first, then a constant-time compare of the decoded
                # bytes. After the shape check every candidate is 32 bytes,
                # so this is belt and braces — kept so a future format with
                # another length cannot turn into an exception.
                if len(candidate) == len(expected) and hmac.compare_digest(candidate, expected):
                    return ChatlySignatureResult(
                        ok=True,
                        surface=surface,
                        timestamp_ms=timestamp_ms,
                        base=base,
                        secret_index=index,
                    )

    many = f" None of the {len(secrets)} secrets matched." if len(secrets) > 1 else ""
    return _fail(
        surface,
        "signature_mismatch",
        f"The digest does not match for {surface}. The three usual causes, in order: a "
        "re-serialised body (pass the RAW bytes, not json.dumps of the parsed object), "
        f"the secret from a different surface, or the wrong surface — "
        f"{spec.describe}.{many}",
    )


def verify_chatly_signature(
    surface: str,
    body: Body,
    headers: Mapping[str, HeaderValue],
    secret: Secret,
    *,
    tolerance_seconds: Optional[float] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    v2: str = "prefer",
    allow_unprotected_replay: bool = False,
    now_ms: Optional[int] = None,
) -> ChatlySignatureResult:
    """Verify one signed request from Chatly. Never raises.

    .. code-block:: python

        result = chatly.verify_chatly_signature(
            "event_webhook",
            request.get_data(),            # the RAW bytes
            request.headers,
            os.environ["CHATLY_WEBHOOK_SECRET"],
            method=request.method,
            path=request.full_path.rstrip("?"),
        )
        if not result.ok:
            log.warning("%s: %s", result.reason, result.message)
            return "", 400

    Args:
        surface: which route this request came from — one of
            :data:`CHATLY_SIGNATURE_SURFACES`. Required, never inferred.
        body: **the exact bytes received**, before any JSON parsing. A ``str``
            is encoded as UTF-8; the MAC is over bytes.
        headers: the request's headers — a dict, or anything with
            ``.items()``. Names match case-insensitively, and the same name
            under two casings counts as two values.
        secret: the secret for THIS surface, or a list of every secret live
            on it during a rotation. Empty strings are skipped.
        tolerance_seconds: freshness window in SECONDS whatever the surface's
            unit, both directions. Default
            :data:`CHATLY_SIGNATURE_TOLERANCE_SECONDS`. ``float("inf")`` only
            when re-verifying an archive.
        method, path: the request's HTTP method and ``pathname + query``
            (never scheme or host). Inside the signed string on
            ``unified_v2`` and ``ai_tool_call``; passing them on any surface
            is what lets ``v2="prefer"`` pick up the v2 header when it
            appears.
        v2: ``"prefer"`` (default), ``"require"`` or ``"ignore"`` — see the
            module docstring.
        allow_unprotected_replay: ``workflow_webhook_legacy`` only, and
            required there: that surface signs no timestamp, so a captured
            request verifies forever. Must be exactly ``True``.
        now_ms: unix MILLISECONDS, for tests. Defaults to the system clock.
    """
    surface_for_errors = surface if isinstance(surface, str) else str(surface)
    try:
        return _verify(
            _Input(
                surface=surface,
                body=body,
                headers=headers,
                secret=secret,
                tolerance_seconds=tolerance_seconds,
                method=method,
                path=path,
                v2=v2,
                allow_unprotected_replay=allow_unprotected_replay,
                now_ms=now_ms,
            )
        )
    except Exception as exc:  # noqa: BLE001 - the never-raises guarantee is the point
        # Reached only by an input nobody anticipated (a `now_ms` that is a
        # string, a headers object whose `.items()` raises). Refusing is the
        # safe direction; raising would be an accepted webhook.
        return _fail(
            surface_for_errors,
            "signature_mismatch",
            f"The request could not be verified: {type(exc).__name__} while checking it. "
            "This is a refusal, not an error to retry.",
        )


__all__ = [
    "CHATLY_SIGNATURE_FAILURES",
    "CHATLY_SIGNATURE_SURFACES",
    "CHATLY_SIGNATURE_TOLERANCE_SECONDS",
    "CHATLY_V2_SIGNATURE_HEADER",
    "IN_SIGNATURE",
    "ChatlySignatureResult",
    "SurfaceSpec",
    "verify_chatly_signature",
]
