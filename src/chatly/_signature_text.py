"""Text helpers for :mod:`chatly.signatures` — parsing untrusted header values.

Split out of ``signatures.py`` to keep it under this repository's 650-line
ceiling (``scripts/check-file-size.mjs`` counts ``.py`` too). Private: nothing
here is part of the public API, and every function is total — none raises on
any input, because the verifier that calls them may not.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple


# `re.fullmatch` with explicit ASCII classes rather than `^…$` and `\d`: in
# Python `$` also matches before a trailing newline, and `\d` matches every
# Unicode digit — "١٧٦٠" is `\d+` and `int()` accepts it. JavaScript's `\d`
# is ASCII-only and its `$` is the end, so these are what the reference means.
_HEX_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_DIGITS = re.compile(r"[0-9]+")

#: 2**53 - 1, JavaScript's ``Number.MAX_SAFE_INTEGER`` — the largest
#: timestamp the reference implementation accepts. See where it is used.
_MAX_SAFE_INTEGER = 9007199254740991

# JavaScript's String.prototype.trim set (WhiteSpace + LineTerminator).
# Python's `str.strip()` is close but not equal — it also strips \x1c-\x1f
# and \x85, and does NOT strip U+FEFF — and a header value is untrusted, so
# "close" is a cross-SDK divergence an attacker can choose to exercise.
_JS_WHITESPACE = (
    "\t\n\v\f\r          "
    "        　﻿"
)


def _trim(value: str) -> str:
    return value.strip(_JS_WHITESPACE)


def _utf8(value: str) -> bytes:
    """UTF-8, with a lone surrogate written as U+FFFD — what Node does.

    ``str.encode("utf-8")`` RAISES on a lone surrogate (which a JSON decoder
    will happily produce from ``"\\ud800"``), and raising is the one thing
    this module may not do. ``errors="replace"`` would write ``?`` instead,
    which is a different HMAC from every other SDK's. The UTF-16 round trip
    turns each lone surrogate into U+FFFD, the WHATWG encoding Node's
    ``Buffer.from(s, 'utf8')`` and ``hmac.update(s)`` both use.
    """
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        return (
            value.encode("utf-16-le", "surrogatepass")
            .decode("utf-16-le", "replace")
            .encode("utf-8")
        )


def _header_values(headers: object, name: str) -> List[object]:
    """Every value for ``name``, across every key that matches case-insensitively.

    ``{"x-a": v, "X-A": w}`` is TWO values, not a lookup that picks one:
    two casings of one header is exactly what a proxy that merges or injects
    a header produces, and the caller refuses duplicates.

    Anything with ``.items()`` works — a plain dict, Werkzeug's ``Headers``
    (whose ``items()`` repeats a key per value), Django's ``request.headers``,
    ``email.message.Message``. A value that is a list or tuple contributes
    each element; ``None`` contributes nothing. A value of any other type is
    kept as-is so it still COUNTS — a garbage second value must still make a
    header a duplicate — and is refused as malformed where it is read.
    """
    wanted = name.lower()
    found: List[object] = []
    items = getattr(headers, "items", None)
    if not callable(items):
        return found
    for key, value in items():
        if not isinstance(key, str) or key.lower() != wanted or value is None:
            continue
        if isinstance(value, (list, tuple)):
            found.extend(v for v in value if v is not None)
        else:
            found.append(value)
    return found


def _parse_tv1(raw: str) -> Optional[Tuple[str, List[str], Optional[str]]]:
    """Parse ``t=…,v1=…[,b=…]``, collecting EVERY ``v1``.

    Tolerates spaces and unknown fields — a future ``v3`` field must not break
    a ``v1`` verifier — and keeps the FIRST ``t`` and the FIRST ``b``, so an
    appended second one cannot move the window or the base.
    """
    t: Optional[str] = None
    b: Optional[str] = None
    v1: List[str] = []
    for part in raw.split(","):
        eq = part.find("=")
        if eq <= 0:
            continue
        key = _trim(part[:eq])
        value = _trim(part[eq + 1 :])
        if key == "t":
            if t is None:
                t = value
        elif key == "b":
            if b is None:
                b = value
        elif key == "v1":
            v1.append(value)
    if t is None or not v1:
        return None
    return t, v1, b


def _secrets_from(secret: object) -> List[Tuple[str, int]]:
    """Every non-empty string secret, paired with its index in what was PASSED.

    The caller's index survives the filter: ``["", s]`` verifying with ``s``
    reports 1, because the index is how a caller mid-rotation finds out
    which of THEIR secrets is still in use, and an index into a list they
    never saw answers a different question. Only ``list`` and ``tuple`` count
    as a list of secrets — a ``str`` is iterable too, and iterating one would
    make each character a secret.
    """
    if isinstance(secret, str):
        candidates: Sequence[object] = [secret]
    elif isinstance(secret, (list, tuple)):
        candidates = secret
    else:
        candidates = []
    return [(s, i) for i, s in enumerate(candidates) if isinstance(s, str) and s != ""]


def _has_target(method: object, path: object) -> bool:
    return isinstance(method, str) and method != "" and isinstance(path, str) and path != ""


def _preview(value: str) -> str:
    """Clip an untrusted header value so an error message stays one line."""
    return value[:47] + "…" if len(value) > 48 else value
