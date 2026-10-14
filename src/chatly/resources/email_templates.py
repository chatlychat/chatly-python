"""``client.email_templates`` — per-workspace overrides of platform email."""

from __future__ import annotations

from typing import List

from .._transport import encode_path
from ..errors import InvalidArgumentError
from ._base import JsonDict, Resource, as_list

#: The five overridable email kinds. **The resource IS the kind** — there are
#: no row ids on this API.
#:
#: An unknown kind is a 400 naming the value, not a 404, and that includes
#: ``plain``, which is deliberately not overridable.
EMAIL_TEMPLATE_KINDS = (
    "workspace_invite",
    "trial_ending_reminder",
    "conversation_cap_warning",
    "hired_agent_engagement_invite",
    "hired_agent_engagement_started",
)


def _check_kind(kind: str) -> str:
    if kind not in EMAIL_TEMPLATE_KINDS:
        raise InvalidArgumentError(
            f"unknown email template kind {kind!r}; expected one of "
            f"{', '.join(EMAIL_TEMPLATE_KINDS)}"
        )
    return kind


class EmailTemplates(Resource):
    """Read the catalogue, preview a draft, override a kind, restore it.

    One override per workspace per kind, keyed by the kind itself — so
    ``PUT`` is idempotent by construction and there is no id to carry around.
    Reads (including :meth:`preview`) need ``workspace:read``; writes need
    ``workspace:write``.
    """

    def list(self) -> List[JsonDict]:
        """The whole catalogue. A bare list of **five** rows, always.

        **This is the catalogue, not your overrides**: every kind is present
        whether or not you have overridden it, and ``override`` is ``None``
        when the workspace is on the built-in. There is no third state, which
        is exactly why :meth:`delete` means "restore".

        Each row carries ``kind``, ``label``, ``whenSent``, ``audience``,
        ``builtInSummary``, ``tokens`` and ``override``. ``tokens`` is what
        makes this worth calling before a write: each is
        ``{"token", "describes", "sample"}`` plus an optional ``optional``
        flag, and it is the per-kind allow-list :meth:`preview` checks
        against.
        """
        return as_list(self._get("/v1/email-templates"))

    def preview(self, kind: str, *, subject: str, body: str) -> JsonDict:
        """Render a draft without saving it. Answers **201**.

        Args:
            kind: one of :data:`EMAIL_TEMPLATE_KINDS`. **In the body on this
                route**, not the path.
            subject: up to 300 characters. Unlike :meth:`update`, ``""`` is
                accepted here — this is a preview, not a save.
            body: up to 10,000 characters, ``""`` likewise accepted.

        Returns ``{"subject", "html", "text", "unknownTokens"}``.

        It runs the **real** send-time renderer with your resolved brand and
        the catalogue's deliberately fake sample values ("Acme Support",
        "example.com") — real customer names are never substituted into a
        preview. Nothing is written.

        ``unknownTokens`` is the typo net: tokens you wrote that this kind
        does not supply, de-duplicated across subject and body. **An empty
        list is the healthy answer.** It matters because the renderer leaves
        an unknown token *visible* in sent mail rather than blanking it, so a
        misspelling ships as ``{{ customer_nmae }}`` to a customer.

        Token syntax is ``{{ token }}``; whitespace inside the braces is
        tolerated.

        201 rather than 200, even though nothing is created — that is Nest's
        default for a POST and it is part of the contract here.
        """
        return self._post_obj(
            "/v1/email-templates/preview",
            {"kind": _check_kind(kind), "subject": subject, "body": body},
        )

    def update(self, kind: str, *, subject: str, body: str) -> JsonDict:
        """Override one kind. Returns the catalogue row for it.

        Args:
            kind: one of :data:`EMAIL_TEMPLATE_KINDS`.
            subject: 1–300 characters **after trimming**, so whitespace alone
                is a 400.
            body: 1–10,000 characters after trimming.

        An upsert on (workspace, kind): two concurrent saves produce one row
        and the last writer wins, rather than a 500 from a unique violation.
        Both fields are required — this replaces the override wholesale, it
        does not patch it.

        Sent as ``PUT`` because the kind is the identity. The body is strict,
        so an extra key is a 400.
        """
        return self._put_obj(
            f"/v1/{encode_path('email-templates', _check_kind(kind))}",
            {"subject": subject, "body": body},
        )

    def delete(self, kind: str) -> JsonDict:
        """Drop the override and restore the built-in. **200**, with a body.

        Returns ``{"restored": bool}`` — and **``restored: False`` is a
        success**: the workspace was already on the built-in, you asked for a
        state and the state holds. Not a 404 and not an error.

        Two things it is not. It does **not** return the restored template —
        read it back with :meth:`list` if a UI needs it. And "restore" means
        *today's* built-in, not a snapshot of whatever was there before the
        override: the platform's copy may have changed in the meantime.
        """
        return self._delete_obj(
            f"/v1/{encode_path('email-templates', _check_kind(kind))}"
        )


__all__ = ["EMAIL_TEMPLATE_KINDS", "EmailTemplates"]
