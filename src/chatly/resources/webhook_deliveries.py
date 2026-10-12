"""``client.webhooks`` — delivery history for your webhook endpoints.

Named ``webhook_deliveries`` rather than ``webhooks`` so it is not mistaken
for :mod:`chatly.webhooks`, which is the signature verifier you run in your
own handler. This module talks to the API *about* deliveries; that one checks
that a delivery you received is genuine.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional, Sequence, Union

from .._transport import encode_path
from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, csv


class Webhooks(Resource):
    """Inspect and re-queue webhook deliveries.

    A delivery is ``{"id", "endpointId", "eventType", "attempt", "status",
    "httpStatus", "durationMs", "error", "nextRetryAt", "deliveredAt",
    "createdAt"}``. ``status`` is a plain string the worker writes —
    ``pending``, ``delivered`` or ``failed`` today, deliberately not an
    enum, so compare it as a string and expect new values.

    Creating and editing endpoints is not here: those routes need a
    signed-in person. Reach them with
    :meth:`chatly.ChatlyClient.request` if you are automating setup.
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


__all__ = ["Webhooks"]
