"""``client.docs_sources`` — external documentation pulled into the KB."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from .._transport import encode_path
from ..errors import InvalidArgumentError
from ._base import JsonDict, Resource, as_list

#: The documentation platforms Chatly can sync from.
#:
#: ``website`` is the sitemap crawler, and it — like Discourse's public
#: categories — needs no token, which is why an empty ``token`` is legal.
DOCS_PROVIDERS = (
    "gitbook",
    "forumulate",
    "discourse",
    "readme",
    "website",
    "notion",
    "confluence",
    "zendesk",
    "intercom",
    "github",
)

#: Values of a source's ``syncStatus``.
#:
#: ``synced_empty`` and ``synced_partial`` are **successes that need a
#: human**, not failures. ``queued`` covers both "enqueued" and "running".
SYNC_STATUSES = (
    "queued",
    "synced",
    "synced_empty",
    "synced_partial",
    "failed",
    "paused",
)


class DocsSources(Resource):
    """Connect a docs platform, sync it, and keep it syncing.

    Reads need ``kb:read``, writes ``kb:write``. **Every write in this
    namespace requires an ``Idempotency-Key``** — including
    :meth:`discover`, which stores nothing — and answers 428 in production
    without one. This SDK mints one per call, so that is handled; it matters
    if you reach these routes through
    :meth:`chatly.ChatlyClient.request` instead.

    The field to read after any sync is ``syncStatus``
    (:data:`SYNC_STATUSES`). **Do not read ``articleCount: 0`` as "synced and
    found nothing"** — on a fresh source it means the first sync has not run.
    """

    def providers(self) -> List[JsonDict]:
        """The supported providers. A bare list.

        Each is ``{"name", "label", "needsBaseUrl", "needsToken"}``. The two
        booleans are what a connect form should branch on: a self-hosted
        provider needs a ``base_url``, and the sitemap crawler needs no
        token at all.
        """
        return as_list(self._get("/v1/docs-sources/providers"))

    def list(self) -> List[JsonDict]:
        """Every connected source, with live counts. A bare list.

        ``articleCount`` and ``staleCount`` are computed here — and, since
        2026-10-16, by :meth:`update` as well. Only :meth:`create` answers 0
        for both, because a source connected a moment ago has no articles.

        No token is ever returned, on this or any other route here.
        """
        return as_list(self._get("/v1/docs-sources"))

    def discover(
        self,
        *,
        provider: str,
        token: str,
        base_url: Optional[str] = None,
        organization_id: Optional[str] = None,
        **extra: Any,
    ) -> List[JsonDict]:
        """List the spaces a credential can reach. A bare list. Answers 201.

        Args:
            provider: one of :data:`DOCS_PROVIDERS`.
            token: up to 400 characters. **An empty string is legal** —
                Discourse's public categories and the sitemap crawler need no
                credential.
            base_url: required in practice for a self-hosted provider.
            organization_id: needed for an **org-scoped** Forumulate token,
                which cannot list organisations for itself. Omitting it there
                fails the whole connect flow with a message about
                permissions rather than about this field.

        **It stores nothing.** It is a POST because a credential does not
        belong in a query string, and it calls the provider live — so a
        failure here is usually theirs, not yours. It is nevertheless graded
        as a write for idempotency.

        Feed a returned ``id`` to :meth:`create` as ``space_id``.
        """
        if provider not in DOCS_PROVIDERS:
            raise InvalidArgumentError(
                f"unknown docs provider {provider!r}; expected one of "
                f"{', '.join(DOCS_PROVIDERS)}"
            )
        body: JsonDict = {"provider": provider, "token": token}
        for key, value in (
            ("baseUrl", base_url),
            ("organizationId", organization_id),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return as_list(self._post("/v1/docs-sources/discover", body))

    def create(
        self,
        *,
        provider: str,
        token: str,
        organization_id: str,
        space_id: str,
        base_url: Optional[str] = None,
        label: Optional[str] = None,
        publish_on_sync: Optional[bool] = None,
        sync_interval_minutes: Optional[int] = None,
        include_paths: Optional[Sequence[str]] = None,
        exclude_paths: Optional[Sequence[str]] = None,
        **extra: Any,
    ) -> JsonDict:
        """Connect a source and queue its first sync. Answers 201.

        Args:
            provider: one of :data:`DOCS_PROVIDERS`.
            token: the credential, stored encrypted and never returned.
            organization_id: required, even where :meth:`discover` treats it
                as optional.
            space_id: from :meth:`discover`. **Verified live before
                anything is stored**: a space the token cannot reach is a 400
                that enumerates the ones it can.
            base_url: required in practice for a self-hosted provider;
                omitting it there is a 400 naming the field.
            label: 1–160 characters.
            publish_on_sync: publish synced articles rather than drafting
                them.
            sync_interval_minutes: 15–10,080. The floor matches the
                background scan cadence, so a smaller number would promise a
                frequency nothing can honour.
            include_paths, exclude_paths: up to 50 prefixes each, 300
                characters apiece.

        Path filters are **refused with a 400** — not ignored — for a
        provider that cannot apply them (only Forumulate and sitemap-read
        sites can), and also if every entry normalises away. They match at a
        **segment boundary**, so ``guides/selling`` does not capture
        ``guides/selling-tips``, and **exclude beats include**. They are
        stored normalised: ``/Guides/Selling/``, ``guides/selling`` and a
        full URL all become ``guides/selling``, so the echo will not match
        what you sent.

        The first sync is enqueued before the response, so it always reads
        ``syncStatus: "queued"``, ``lastSyncedAt: None``,
        ``articleCount: 0``.
        """
        if provider not in DOCS_PROVIDERS:
            raise InvalidArgumentError(
                f"unknown docs provider {provider!r}; expected one of "
                f"{', '.join(DOCS_PROVIDERS)}"
            )
        body: JsonDict = {
            "provider": provider,
            "token": token,
            "organizationId": organization_id,
            "spaceId": space_id,
        }
        for key, value in (
            ("baseUrl", base_url),
            ("label", label),
            ("publishOnSync", publish_on_sync),
            ("syncIntervalMinutes", sync_interval_minutes),
            ("includePaths", list(include_paths) if include_paths is not None else None),
            ("excludePaths", list(exclude_paths) if exclude_paths is not None else None),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return self._post_obj("/v1/docs-sources", body)

    def update(self, source_id: str, **fields: Any) -> JsonDict:
        """Update a source. Every field optional, **wire** names.

        Accepts ``label``, ``status`` (**only ``active`` or ``paused``** —
        ``error`` is set by the platform and rejected here),
        ``publishOnSync``, ``syncIntervalMinutes``, ``token`` and
        ``baseUrl``.

        **A new ``token`` is verified upstream before it is stored**: a
        credential that authenticates but cannot see *this* source's space is
        refused and the working one is left in place. Sending a ``token``, or
        setting ``status="active"``, also clears ``lastError``.

        **``articleCount`` and ``staleCount`` in this response are the real
        counts**, read alongside the write. They were hardcoded zeros until
        2026-10-16, so renaming a source holding 1,200 articles answered
        ``articleCount: 0``; a UI that re-renders from this response no longer
        has to re-read from :meth:`list`.

        ``baseUrl`` is merged into the stored configuration rather than
        replacing it. A malformed id is a clean 400 here (this namespace
        validates its ids, unlike several others).
        """
        return self._patch_obj(
            f"/v1/{encode_path('docs-sources', source_id)}", dict(fields)
        )

    def sync(self, source_id: str, *, full: Optional[bool] = None) -> JsonDict:
        """Queue a sync. Answers 201 with ``{"queued": true, "full"}``.

        Args:
            full: ``True`` **resets the incremental checkpoint first**, so
                every document is re-read rather than only what changed.

        That flag is the one to reach for when the *reader* changed rather
        than the content — a parser fix, a new field, a filter change.
        Without it, a source that already holds a checkpoint answers "sync
        now" with a delta and the knowledge base stays exactly as wrong as it
        was.

        ``queued`` is a literal ``True`` and the work happens in a worker, so
        poll ``syncStatus`` through :meth:`list` rather than reading success
        into this response. ``full`` echoes what you asked for.
        """
        body: JsonDict = {}
        if full is not None:
            body["full"] = full
        return self._post_obj(
            f"/v1/{encode_path('docs-sources', source_id)}/sync", body
        )

    def webhook(self, source_id: str) -> JsonDict:
        """Subscribe this source to its provider's change events. Answers 201.

        Returns ``{"subscribed", "reason"}``.

        **``subscribed: False`` with a ``reason`` is a success, and it is the
        common case.** Most tokens customers paste are read-only, and
        registering a webhook needs a management scope — so the honest answer
        is "scheduled syncing only, here is why", not an error. A provider
        with no change events at all answers the same way.

        Already-subscribed is an idempotent ``{"subscribed": true}`` that
        registers nothing: these providers have no idempotency on endpoint
        creation, so a second POST would create a duplicate endpoint and
        double-deliver every change.

        **This is the outbound half only.** The public receiver Chatly
        exposes for provider callbacks is a different, unauthenticated route;
        do not confuse the two.

        A 404 for an unknown source.
        """
        return self._post_obj(
            f"/v1/{encode_path('docs-sources', source_id)}/webhook"
        )

    def delete(self, source_id: str) -> JsonDict:
        """Disconnect a source. Returns ``{"kept": n}`` with a **200**.

        **The articles survive.** ``kept`` is how many were re-marked
        ``manual`` and retained; the collection stays, with its link to the
        source cleared. Nothing is removed from the knowledge base, which is
        why this is safe to call on a source whose credential you have lost.

        **It does not 404 on an unknown id** — there is no existence check
        before the delete, so a well-formed id that names nothing answers
        ``{"kept": 0}``. Do not write a handler that treats 404 as "already
        gone"; that answer will not arrive.
        """
        return self._delete_obj(f"/v1/{encode_path('docs-sources', source_id)}")


__all__ = ["DOCS_PROVIDERS", "SYNC_STATUSES", "DocsSources"]
