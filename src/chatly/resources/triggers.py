"""``client.triggers`` — event-driven rules the worker evaluates."""

from __future__ import annotations

from typing import Any, Iterator, Optional, Sequence, Union

from .._transport import encode_path
from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, csv


class Triggers(Resource):
    """List, create and delete triggers. Reads ``triggers:read``, writes
    ``triggers:write``.

    A trigger is ``{"id", "workspaceId", "brandId", "name", "enabled",
    "eventType", "conditions", "actions", "priority", "debounceSeconds",
    "debounceKeyTemplate", "createdAt", "updatedAt"}``.

    Two fields read as more meaningful than they are. On a **read**,
    ``conditions[]["op"]`` and ``actions[]["type"]`` come back as plain
    strings rather than the write-side enums, because rows written before
    those enums existed are still in the table. And ``enabled`` is
    **vestigial** — nothing writes it and the dispatcher ignores it — but it
    is non-nullable, so it is always present and always a lie if you read it
    as "this trigger is off". Delete a trigger you want stopped.
    """

    def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        fields: CsvValue = None,
        filter: Union[None, str, Sequence[str]] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of triggers, newest first.

        Args:
            cursor: from the previous page's ``next_cursor``.
            limit: 1–100, default 25.
            sort: ``id``, ``name``, ``priority``, ``createdAt`` or
                ``updatedAt``, optionally ``-`` prefixed. Default
                ``createdAt`` descending.
            fields: a projection over the trigger fields — and the reason
                **every key on a row is optional**. The cursor is built from
                the unprojected row, so narrowing ``fields`` does not break
                paging even if you drop the sort column.
            filter: clauses, repeated on the wire. Filterable: ``enabled``,
                ``eventType``, ``brandId``, ``createdAt``, ``updatedAt``.

        **The order is ``createdAt`` descending, not ``priority``
        ascending**, which is deliberate: this is a management list, and the
        worker reads its own ordered copy. Do not infer evaluation order from
        it.

        The envelope carries ``hasMore`` beside ``items`` and ``nextCursor``.
        """
        return self._page(
            "/v1/triggers",
            {
                "cursor": cursor,
                "limit": limit,
                "sort": sort,
                "fields": csv(fields),
                "filter": filter,
                **params,
            },
        )

    def iter_list(self, **params: Any) -> Iterator[JsonDict]:
        """Every trigger, as a generator.

            for trigger in client.triggers.iter_list():
                print(trigger["eventType"], trigger["name"])
        """
        params.pop("cursor", None)
        if "fields" in params:
            params["fields"] = csv(params["fields"])
        return self._walk("/v1/triggers", params)

    def create(
        self,
        *,
        name: str,
        event_type: str,
        enabled: bool,
        conditions: Sequence[Any],
        actions: Sequence[Any],
        trigger_id: Optional[str] = None,
        priority: Optional[int] = None,
        debounce_seconds: Optional[int] = None,
        debounce_key_template: Optional[str] = None,
        **extra: Any,
    ) -> JsonDict:
        """Create **or update** a trigger. Answers 201 either way.

        Despite the name this route is an upsert: pass ``trigger_id`` (sent
        as ``id``) and the existing row is updated. The status is **201 on
        both arms**, so do not read it as "created".

        Args:
            name: 1–160 characters.
            event_type: 1–64 characters, and **a free-form string here** —
                this schema does not validate it against the catalogue of
                offered trigger types, so a typo creates a trigger that never
                fires. Take the value from the dashboard's builder
                vocabulary.
            enabled: required by the schema, and vestigial in effect — see
                the class docstring.
            conditions: up to 50 ``{"field", "op", "value"}``, where ``op``
                is ``eq``, ``neq``, ``in``, ``gt``, ``lt``, ``contains`` or
                ``matches``. May be ``[]`` — that means "every event of this
                type".
            actions: **at least one**, up to 20, each ``{"type", "params"}``.
                ``type`` is a closed enum of about 34 values —
                ``send_message``, ``assign``, ``tag``, ``change_status``,
                ``enqueue_workflow``, ``fire_webhook``, the ``ai_*`` family
                and so on. A trigger with no actions is a 400.
            priority: ≥ 0, default 0. Lower runs first.
            debounce_seconds: 1 to 604,800 (7 days), or ``None`` for no
                debounce.
            debounce_key_template: what to debounce *per*. ``None`` defaults
                to the contact (or conversation) at evaluation time, which is
                usually what you want; set it when one contact should be able
                to fire the same trigger for two different objects.
        """
        body: JsonDict = {
            "name": name,
            "eventType": event_type,
            "enabled": enabled,
            "conditions": list(conditions),
            "actions": list(actions),
        }
        for key, value in (
            ("id", trigger_id),
            ("priority", priority),
            ("debounceSeconds", debounce_seconds),
            ("debounceKeyTemplate", debounce_key_template),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return self._post_obj("/v1/triggers", body)

    def delete(self, trigger_id: str) -> JsonDict:
        """Delete a trigger. Returns ``{"ok": true}`` with a **200**.

        Not a 204 — parse the body. ``ok`` is a literal ``True`` and
        ``ok: False`` is not a producible answer: a trigger that does not
        exist is a **404**, which is how you tell the two apart.

        A **hard** delete: no ``deleted_at``, no undo. Until this route
        existed there was no way to remove a trigger from any surface, so one
        created by mistake fired forever — which is also why there is no
        "disable" to reach for instead (``enabled`` is not honoured).

        A malformed id is a 400 naming the trigger id.
        """
        return self._delete_obj(f"/v1/{encode_path('triggers', trigger_id)}")


__all__ = ["Triggers"]
