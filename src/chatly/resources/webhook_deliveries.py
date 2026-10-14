"""``client.webhooks`` — delivery history for your webhook endpoints.

Named ``webhook_deliveries`` rather than ``webhooks`` so it is not mistaken
for :mod:`chatly.webhooks`, which is the signature verifier you run in your
own handler. This module talks to the API *about* deliveries; that one checks
that a delivery you received is genuine.
"""

from __future__ import annotations

from typing import Any, Iterator, List, Optional, Sequence, Union

from .._transport import encode_path
from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, as_list, csv


class Webhooks(Resource):
    """Inspect and re-queue webhook deliveries.

    A delivery is ``{"id", "endpointId", "eventType", "attempt", "status",
    "httpStatus", "durationMs", "error", "nextRetryAt", "deliveredAt",
    "createdAt"}``. ``status`` is a plain string the worker writes —
    ``pending``, ``delivered`` or ``failed`` today, deliberately not an
    enum, so compare it as a string and expect new values.

    Endpoints themselves are here too — :meth:`list`, :meth:`create`,
    :meth:`delete`, :meth:`set_schema_version` — along with the two static
    catalogues
    (:meth:`events`, :meth:`schema_versions`) a settings screen needs.
    Editing an endpoint's URL or event list still requires a signed-in
    person; reach that with :meth:`chatly.ChatlyClient.request` if you are
    automating setup.

    Endpoint reads and writes need ``integrations:write``; the delivery
    history needs ``integrations:read``.
    """

    def deliveries(
        self,
        *,
        endpoint_id: Optional[str] = None,
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        fields: CsvValue = None,
        filter: Union[None, str, Sequence[str]] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of deliveries, newest first.

        Args:
            endpoint_id: narrow to one endpoint.
            status: ``pending``, ``delivered`` or ``failed``. Unvalidated —
                a typo returns an empty list rather than an error.
            cursor: from the previous page's ``next_cursor``.
            limit: 1–100, default 25.
            sort: a sortable column with an optional ``-`` prefix.
            fields: a projection.
            filter: clauses, repeated on the wire.

        The rows carry no payload — fetch one with :meth:`delivery` for that.
        """
        return self._page(
            "/v1/webhooks/deliveries",
            {
                "endpointId": endpoint_id,
                "status": status,
                "cursor": cursor,
                "limit": limit,
                "sort": sort,
                "fields": csv(fields),
                "filter": filter,
                **params,
            },
        )

    def iter_deliveries(self, **params: Any) -> Iterator[JsonDict]:
        """Every matching delivery, as a generator.

            failures = client.webhooks.iter_deliveries(status="failed")
            for delivery in failures:
                client.webhooks.redeliver(delivery["id"])
        """
        params.pop("cursor", None)
        if "endpoint_id" in params:
            params["endpointId"] = params.pop("endpoint_id")
        if "fields" in params:
            params["fields"] = csv(params["fields"])
        return self._walk("/v1/webhooks/deliveries", params)

    def delivery(self, delivery_id: str) -> JsonDict:
        """One delivery, with its payload.

        Everything :meth:`deliveries` returns, plus ``payload`` — the exact
        body that was POSTed — and ``url``.

        Two cautions. ``url`` is the endpoint's **current** URL, not the one
        this attempt went to, so it can disagree with history after an
        endpoint is edited. And ``payload`` is the decoded JSON, not the raw
        bytes: re-serialising it will not reproduce a digest that
        :func:`chatly.verify_webhook_signature` accepts, because key order
        and whitespace are lost. Verify against the bytes your handler
        received, not against this.
        """
        return self._get_obj(f"/v1/{encode_path('webhooks', 'deliveries', delivery_id)}")

    def redeliver(self, delivery_id: str) -> JsonDict:
        """Queue a delivery to be sent again.

        Returns ``{"queued": true, "eventType": ..., "url": ...}``.
        **Queued, not delivered** — the result shows up as a *new* attempt in
        :meth:`deliveries`, with its own id, so poll there rather than
        reading success into this response.
        """
        return self._post_obj(
            f"/v1/{encode_path('webhooks', 'deliveries', delivery_id)}/redeliver"
        )


    # ---- endpoints -------------------------------------------------------

    def list(self) -> List[JsonDict]:
        """Your webhook endpoints. A bare list, no cursor.

        Each is ``{"id", "url", "description", "eventTypes", "enabled",
        "schemaVersion"}``, with ``description`` nullable.

        **``secret`` is absent from every row by design** — the query selects
        six named columns rather than the whole row precisely so a leak is
        not one careless ``select()`` away. The only response that ever
        carries it is :meth:`create`.
        """
        return as_list(self._get("/v1/webhooks"))

    def create(
        self,
        *,
        url: str,
        event_types: Sequence[str],
        description: Optional[str] = None,
        schema_version: Optional[str] = None,
        **extra: Any,
    ) -> JsonDict:
        """Register an endpoint. Answers 201 **with the signing secret**.

        Args:
            url: where deliveries are POSTed.
            event_types: at least one, each from :meth:`events`. An
                unrecognised name is a 400.
            description: up to 280 characters.
            schema_version: from :meth:`schema_versions`; omitted takes the
                platform default. **An unrecognised version is a 400 here**,
                deliberately unlike the delivery path, which resolves an
                unknown pin to the latest — loud on the write, generous on
                the read.

        **The ``secret`` in this response is the only time it is readable.**
        There is no reveal route and no rotation route: if you lose it, the
        endpoint has to be deleted and recreated. It is a ``whsec_`` value,
        and it is the input to
        :func:`chatly.verify_webhook_signature`.

        There is no ``secret`` parameter — the server mints it, so an SDK
        that let you choose one would be lying about where it came from.
        """
        body: JsonDict = {"url": url, "eventTypes": list(event_types)}
        for key, value in (
            ("description", description),
            ("schemaVersion", schema_version),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return self._post_obj("/v1/webhooks", body)

    def events(self) -> JsonDict:
        """Every event type an endpoint may subscribe to.

        Returns ``{"eventTypes": [...]}`` — **an object wrapping the list**,
        not a bare array.

        **Static and workspace-independent**, so cache it. It exists because
        the dashboard's picker and the server's validation were separately
        hard-coded and drifted: the picker offered three events the platform
        never emits, so customers subscribed to names that could never
        arrive. Fetch the allow-list from here rather than copying it into
        your own code.

        Note this list is **not** filtered by any endpoint's pinned schema
        version — a name here may still not be delivered to an endpoint
        pinned to an older version. Cross-check with
        :meth:`schema_versions`.
        """
        return self._get_obj("/v1/webhooks/events")

    def schema_versions(self) -> JsonDict:
        """The webhook payload schema versions, and what each one carries.

        Returns ``{"latest", "versions"}``, each version
        ``{"version", "isLatest", "isDeprecated", "eventTypes"}``.

        A version is a dated string, ``YYYY-MM-DD``, so it sorts
        lexicographically — but read ``latest`` rather than sorting, since
        that is the field the platform maintains. The versions are
        **additive**: each is the previous one plus the event types added
        since, which is why pinning backwards *stops* deliveries rather than
        changing their shape.

        **``isDeprecated`` is advisory and non-blocking** — nothing refuses a
        deprecated pin, so treat it as a warning to schedule work, not an
        error. Do not hard-code the version list; fetch it.
        """
        return self._get_obj("/v1/webhooks/schema-versions")

    def delete(self, endpoint_id: str) -> JsonDict:
        """Delete an endpoint. Returns ``{"ok": true}`` with a **200**.

        Not a 204 — parse the body. ``ok`` is a literal ``True`` and
        ``ok: False`` cannot be returned: an endpoint that does not exist, or
        belongs to another workspace, is a **404**. Unlike several other
        deletes on this surface, this one really does check before answering.

        A **hard** delete, with no ``deleted_at`` and no undo — and it
        destroys the only copy of the signing secret, since :meth:`create` is
        the only route that ever returns one. A recreated endpoint is a new
        subscription with a new secret.

        **This route was closed to API keys until 2026-10-14**, which is
        worth knowing if you are reading older integration code. A key could
        create a subscription and never remove one, so a deploy pipeline
        registering an endpoint per environment leaked one into the
        customer's workspace on every run. The workaround that used to be
        recommended — repointing the endpoint at a dead URL — is not
        equivalent: the subscription stays alive and the delivery log fills
        with failures. Delete it.

        Needs ``integrations:write``, the same grant as :meth:`create`, on
        the argument that a credential which can add a delivery target can
        already do the thing with consequences.
        """
        return self._delete_obj(f"/v1/{encode_path('webhooks', endpoint_id)}")

    def set_schema_version(self, endpoint_id: str, schema_version: str) -> JsonDict:
        """Pin an endpoint to a schema version.

        Returns ``{"id", "url", "eventTypes", "schemaVersion",
        "missingEventTypes"}`` — a **partial** endpoint: no ``description``,
        no ``enabled``, and never the secret.

        Moving the pin **forward** starts delivering the event types the
        newer version added; moving it **backward** stops delivering them.
        Both take effect on the **next event** — the dispatcher reads the
        column per delivery and caches nothing — which is what makes this a
        usable lever during an incident: pin back, stop the flood, fix the
        handler, pin forward.

        ``missingEventTypes`` names, rather than counts, the event types this
        endpoint would gain by moving to the latest version. It is what a
        settings screen shows and what a maintainer diffs their handler
        against.

        An unrecognised version is a 400, an unknown endpoint a 404, and the
        body is strict so a misspelled key is refused rather than ignored.
        """
        return self._patch_obj(
            f"/v1/{encode_path('webhooks', endpoint_id)}/schema-version",
            {"schemaVersion": schema_version},
        )


__all__ = ["Webhooks"]
