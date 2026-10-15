"""Which outbound surfaces Chatly signs, and what each one signs.

Split out of :mod:`chatly.signatures` (the repository's 650-line ceiling) so
the data and the verifier can each be read on its own, mirroring
``signature-table.ts`` in the Node SDK. Everything here is re-exported from
:mod:`chatly.signatures` and from the package root.

  ========================= ============================ ============================== ========
  surface                   header(s)                    base string                    ``t``
  ========================= ============================ ============================== ========
  ``unified_v2``            ``x-chatly-signature-v2``    ``<t>.<METHOD>.<path>.<body>`` seconds
  ``agent_delivery``        ``x-chatly-signature``       ``<t>.<body>``                 seconds
  ``event_webhook``         ``x-livechat-signature``     ``<t>.<body>``                 seconds
  ``ai_tool_call``          ``x-chatly-signature``       ``<t>.<METHOD>.<path>.<body>`` seconds
  ``canvas_step``           ``x-chatly-canvas-signature`` ``<ts>.<body>``               **ms**
                            + ``x-chatly-canvas-ts``
  ``customer_card``         ``x-chatly-signature``       ``<ts>.<body>``                **ms**
                            + ``x-chatly-timestamp``
  ``workflow_webhook``      ``x-chatly-signature-v2``    ``<t>.<body>``                 seconds
  ``workflow_webhook_legacy`` ``x-chatly-signature``     ``<body>`` — no timestamp      n/a
  ========================= ============================ ============================== ========

The unit trap: a millisecond timestamp read as seconds lands around the year
55,000, so the tolerance check rejects every genuine request and the failure
looks like a wrong secret. The unit is therefore a property of the SURFACE
here, never something inferred from the value.

**Three surfaces send ``x-chatly-signature`` and they sign three different
strings.** Agent delivery signs ``<t>.<body>`` under a ``t=…,v1=…`` value; a
tool call signs ``<t>.<METHOD>.<path>.<body>`` under the same-looking value;
a customer-card fetch signs ``<ts>.<body>`` with the timestamp in a SEPARATE
header and the value prefixed ``sha256=``. Keying on the header name would
pick the wrong construction while looking correct, which is why ``surface``
is required and is not inferred.

The unit trap, which this repository has paid for twice: two surfaces send
MILLISECONDS. A millisecond timestamp read as seconds lands around the year
55,000, so the tolerance check rejects every genuine request and the failure
looks like a wrong secret. The unit is therefore a property of the SURFACE,
never something inferred from the value.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

#: Five minutes, matching ``SIGNATURE_TOLERANCE_SECONDS`` on the producing
#: side. Equal in value to :data:`chatly.DEFAULT_TOLERANCE_SECONDS`, but a
#: separate name so the two verifiers can be reasoned about independently.
CHATLY_SIGNATURE_TOLERANCE_SECONDS = 300

#: The header the unified construction travels in, on every surface.
CHATLY_V2_SIGNATURE_HEADER = "x-chatly-signature-v2"

#: Not a header name: the timestamp is the digest header's own ``t=`` field.
#: A sentinel rather than a bool, so a surface that moves its timestamp into a
#: header of its own needs only a table edit.
IN_SIGNATURE = "in-signature"

#: Why a verification failed. Stable strings, safe to branch on — the same
#: eleven in every Chatly SDK.
CHATLY_SIGNATURE_FAILURES: Tuple[str, ...] = (
    "unknown_surface",
    "missing_secret",
    "missing_signature_header",
    "duplicate_signature_header",
    "malformed_signature_header",
    "missing_timestamp",
    "malformed_timestamp",
    "timestamp_outside_tolerance",
    "missing_request_target",
    "replay_unprotected",
    "signature_mismatch",
)


@dataclass(frozen=True)
class SurfaceSpec:
    """What one surface signs. See the table in this module's docstring."""

    #: The header carrying the digest.
    signature_header: str
    #: The header carrying the timestamp on its own, :data:`IN_SIGNATURE`
    #: when it is the digest header's ``t=`` field, or ``None`` when the
    #: surface sends no timestamp at all.
    timestamp_from: Optional[str]
    #: ``"tv1"`` (``t=…,v1=<hex>``) or ``"sha256"`` (``sha256=<hex>``).
    format: str
    #: ``"seconds"``, ``"milliseconds"``, or ``None`` with no timestamp.
    unit: Optional[str]
    #: ``"body"`` → ``<t>.<body>``; ``"target"`` → ``<t>.<METHOD>.<path>.<body>``;
    #: ``"body_only"`` → ``<body>`` with no timestamp — unbounded replay.
    base: str
    #: One line, for an error message and for documentation.
    describe: str
    #: True only on ``workflow_webhook``, which sent the v2 header before the
    #: base gained the method and path, and so accepts the unified base too.
    also_accepts_target_base: bool = False


#: The table, as data — the thing to read when a verification fails. Read-only
#: (a ``MappingProxyType``) because a caller mutating it would silently change
#: what every later call in the process accepts. ``list(...)`` of it is the
#: list of surface names, in the canonical order.
CHATLY_SIGNATURE_SURFACES: Mapping[str, SurfaceSpec] = MappingProxyType(
    {
        "unified_v2": SurfaceSpec(
            CHATLY_V2_SIGNATURE_HEADER, IN_SIGNATURE, "tv1", "seconds", "target",
            "the unified v2 signature, sent alongside every surface’s legacy "
            "header, over t.METHOD.path.body",
        ),
        "agent_delivery": SurfaceSpec(
            "x-chatly-signature", IN_SIGNATURE, "tv1", "seconds", "body",
            "external-agent push delivery, signed with the bot's signingSecret",
        ),
        "event_webhook": SurfaceSpec(
            "x-livechat-signature", IN_SIGNATURE, "tv1", "seconds", "body",
            "event webhook, signed with that subscription's whsec_ secret",
        ),
        "ai_tool_call": SurfaceSpec(
            "x-chatly-signature", IN_SIGNATURE, "tv1", "seconds", "target",
            "custom AI tool call, signed with that tool's secret over t.METHOD.path.body",
        ),
        "canvas_step": SurfaceSpec(
            "x-chatly-canvas-signature", "x-chatly-canvas-ts", "sha256", "milliseconds",
            "body", "canvas / interactive-step callback, timestamp in MILLISECONDS",
        ),
        "customer_card": SurfaceSpec(
            "x-chatly-signature", "x-chatly-timestamp", "sha256", "milliseconds",
            "body", "customer-card fetch, timestamp in MILLISECONDS",
        ),
        "workflow_webhook": SurfaceSpec(
            CHATLY_V2_SIGNATURE_HEADER, IN_SIGNATURE, "tv1", "seconds", "body",
            'workflow "call a webhook" action, replay-bounded v2 header',
            also_accepts_target_base=True,
        ),
        "workflow_webhook_legacy": SurfaceSpec(
            "x-chatly-signature", None, "sha256", None, "body_only",
            "workflow action, LEGACY header over the body alone — no replay protection",
        ),
    }
)


__all__ = [
    "CHATLY_SIGNATURE_FAILURES",
    "CHATLY_SIGNATURE_SURFACES",
    "CHATLY_SIGNATURE_TOLERANCE_SECONDS",
    "CHATLY_V2_SIGNATURE_HEADER",
    "IN_SIGNATURE",
    "SurfaceSpec",
]
