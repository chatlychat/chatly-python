"""``client.events`` — the CDP event stream."""

from __future__ import annotations

from typing import Any, Iterator, Mapping, Optional, Sequence, Union

from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, csv


class Events(Resource):
    """Record behavioural events against a contact, and read them back.

    An event row is ``{"id", "workspaceId", "createdAt", "updatedAt",
    "contactId", "name", "properties", "occurredAt"}``.
    """

    def track(
        self,
        contact_id: str,
        name: str,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> JsonDict:
        """Record one event. Returns the stored row.

        Args:
            contact_id: required. The contact the event belongs to — events
                are not anonymous here, so upsert the contact first
                (:meth:`chatly.resources.contacts.Contacts.upsert`) and use
                the ``id`` it returns.
            name: required, 1–120 characters, e.g. ``"trial_started"``.
            properties: an open object. Values are unconstrained.

        **One event per call — there is no batch form.** The body is the
        event itself at the top level, with no wrapper key and no array, so
        a loop is the only way to send many. The route requires an
        ``Idempotency-Key``, which this SDK mints per call; a retry inside
        the SDK therefore cannot record the same event twice, but two
        separate calls with the same arguments record two events.

        ``occurredAt`` is **not** accepted: the server stamps it on insert,
        so you cannot backfill historical events through this route.
        """
        body: JsonDict = {"contactId": contact_id, "name": name}
        if properties is not None:
            body["properties"] = dict(properties)
        return self._post_obj("/v1/cdp/events", body)

    def list(
        self,
        *,
        contact_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        fields: CsvValue = None,
        filter: Union[None, str, Sequence[str]] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of events, newest first.

        Args:
            contact_id: narrow to one contact.
            cursor: from the previous page's ``next_cursor``.
            limit: 1–100, default 25.
            sort: ``id``, ``createdAt``, ``occurredAt`` or ``name``, ``-``
                for descending. **Default is ``occurredAt`` descending**, not
                ``createdAt`` like the rest of the API.
            fields: a projection over ``id``, ``workspaceId``, ``contactId``,
                ``name``, ``properties``, ``occurredAt``, ``createdAt``,
                ``updatedAt``.
            filter: clauses over ``contactId``, ``name``, ``occurredAt``,
                ``createdAt``. ``properties`` is **not** filterable, so you
                cannot query by event property through this route.

        The cursor is minted from the unprojected row, so a ``fields=``
        projection does not break paging — but do not try to derive a cursor
        from a projected item yourself.
        """
        return self._page(
            "/v1/cdp/events",
            {
                "contactId": contact_id,
                "cursor": cursor,
                "limit": limit,
                "sort": sort,
                "fields": csv(fields),
                "filter": filter,
                **params,
            },
        )

    def iter_list(self, **params: Any) -> Iterator[JsonDict]:
        """Every matching event, as a generator.

            for event in client.events.iter_list(contact_id=cid):
                print(event["name"], event["occurredAt"])
        """
        params.pop("cursor", None)
        if "contact_id" in params:
            params["contactId"] = params.pop("contact_id")
        if "fields" in params:
            params["fields"] = csv(params["fields"])
        return self._walk("/v1/cdp/events", params)


__all__ = ["Events"]
