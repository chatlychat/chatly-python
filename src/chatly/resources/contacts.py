"""``client.contacts`` — the people your agents talk to."""

from __future__ import annotations

from typing import Any, Iterator, Mapping, Optional, Sequence

from .._transport import encode_path
from ..pagination import Page
from ._base import JsonDict, Resource


class Contacts(Resource):
    """Read, upsert, tag, merge and unsubscribe contacts.

    Every method returns the decoded JSON. A contact object carries
    ``id``, ``workspaceId``, ``externalId``, ``email``, ``phone``, ``name``,
    ``avatarUrl``, ``locale``, ``timezone``, ``firstSeenAt``, ``lastSeenAt``,
    ``attributes``, ``tags``, ``unsubscribedAt``, ``mergedIntoId`` and the
    blocking fields (``blockedAt``, ``blockedByUserId``, ``blockReason``,
    ``blockedAttemptCount``, ``lastBlockedAttemptAt``). Nullable fields are
    ``null``, not absent.

    Blocking and unblocking a contact are deliberately absent: those routes
    record *who* blocked, and an API key is not a person, so they answer a
    key with 403. A method that always fails is worse than no method.
    """

    def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        blocked: Optional[bool] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of contacts.

        Args:
            cursor: from the previous page's ``next_cursor``. Opaque — do not
                parse or construct one.
            limit: 1–100, default 25. Out-of-range values are clamped by the
                server on this route rather than rejected.
            blocked: ``True`` for blocked contacts only, ``False`` for
                unblocked only, omitted for both.
        """
        return self._page(
            "/v1/contacts",
            {"cursor": cursor, "limit": limit, "blocked": blocked, **params},
        )

    def iter_list(
        self,
        *,
        limit: Optional[int] = None,
        blocked: Optional[bool] = None,
        **params: Any,
    ) -> Iterator[JsonDict]:
        """Every contact, page by page, as a generator.

        ``limit`` is still the *page* size; it does not cap the total.

            for contact in client.contacts.iter_list():
                print(contact["email"])
        """
        return self._walk("/v1/contacts", {"limit": limit, "blocked": blocked, **params})

    def get(self, contact_id: str) -> JsonDict:
        """One contact by id."""
        return self._get_obj(f"/v1/{encode_path('contacts', contact_id)}")

    def upsert(
        self,
        *,
        external_id: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        locale: Optional[str] = None,
        timezone: Optional[str] = None,
        attributes: Optional[Mapping[str, Any]] = None,
        **extra: Any,
    ) -> JsonDict:
        """Create a contact, or update the one that matches an identifier.

        Every field is optional, and the ones you omit are left alone rather
        than cleared. Pass ``external_id`` whenever you have your own user id
        — it is the identifier the widget's identity verification signs (see
        :func:`chatly.identity_hash`), and matching on it keeps one person
        from becoming two contacts when they change their email address.

        Unknown fields are dropped by the server's schema without an error,
        so a misspelled key is a silent no-op — ``emailAddress=`` does not
        fail, it just does not set the email. The names above are the whole
        accepted set; ``extra`` exists for fields added after this release.

        **No field can be cleared through this route.** Every one is
        optional but not nullable (``contactUpsertInputSchema`` in
        ``packages/shared``), so sending ``null`` is a 400 rather than an
        erasure. ``None`` therefore means "leave it alone" with no
        ambiguity, which is why this method can drop ``None`` arguments
        safely.
        """
        body = _compact(
            {
                "externalId": external_id,
                "email": email,
                "phone": phone,
                "name": name,
                "avatarUrl": avatar_url,
                "locale": locale,
                "timezone": timezone,
                "attributes": attributes,
            }
        )
        # Merged after compacting and deliberately unfiltered, so a field
        # this release has not heard of reaches the server exactly as given.
        body.update(extra)
        return self._post_obj("/v1/contacts", body)

    def bulk_upsert(self, contacts: Sequence[Mapping[str, Any]]) -> JsonDict:
        """Upsert 1–5000 contacts in one call.

        Each element takes the same fields as :meth:`upsert`, in **wire
        casing** (``externalId``, ``avatarUrl``) — this method passes the list
        through untouched rather than translating each row, so that a 5000-row
        import is not 5000 dict rebuilds.

        Returns ``{"total", "created", "updated", "skipped", "errors"}``;
        ``errors`` is a list of ``{"row", "message"}`` capped at 100, so a
        large import reports *that* rows failed even when it cannot report
        every one.
        """
        return self._post_obj("/v1/contacts/bulk", {"contacts": list(contacts)})

    def merge(self, contact_id: str, merged_id: str) -> JsonDict:
        """Merge ``merged_id`` INTO ``contact_id`` and return the survivor.

        The direction is the thing to get right: the path is the contact that
        survives, and the body names the one absorbed. The reverse call also
        succeeds, and leaves the wrong row standing.

        Note the asymmetry with :meth:`chatly.resources.tickets.Tickets.merge`,
        which calls the absorbed row ``loserId``. Same operation, different
        field name, and they are not interchangeable.
        """
        return self._post_obj(
            f"/v1/{encode_path('contacts', contact_id)}/merge", {"mergedId": merged_id}
        )

    def add_tags(self, contact_id: str, tag: str) -> JsonDict:
        """Add one tag. Returns the updated contact.

        Named for the surface spec; the route takes a single ``tag`` per
        call, so loop for several.
        """
        return self._post_obj(f"/v1/{encode_path('contacts', contact_id)}/tags", {"tag": tag})

    def remove_tag(self, contact_id: str, tag: str) -> JsonDict:
        """Remove one tag. Returns the updated contact.

        The tag travels in the path and is percent-encoded here, so a tag
        containing a space or a ``/`` works instead of rewriting the route.
        """
        return self._delete_obj(f"/v1/{encode_path('contacts', contact_id, 'tags', tag)}")

    def unsubscribe(
        self,
        contact_id: str,
        *,
        unsubscribed: bool = True,
        reason: Optional[str] = None,
    ) -> JsonDict:
        """Set or clear a contact's marketing unsubscribe flag.

        ``unsubscribed`` is required by the route and defaults to ``True``
        here because that is the call almost everyone means; pass ``False``
        to resubscribe someone who asked to be resubscribed.
        """
        return self._post_obj(
            f"/v1/{encode_path('contacts', contact_id)}/unsubscribe",
            _compact({"unsubscribed": unsubscribed, "reason": reason}),
        )

    def journey(
        self,
        contact_id: str,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        days: Optional[int] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """A contact's timeline: page views, events, conversations, messages, surveys.

        Args:
            cursor: **not an opaque blob on this one route** — it is an
                ISO-8601 instant with an offset, and the server rejects
                anything else with a 400. Pass back what ``next_cursor``
                gave you and it is correct; do not invent one.
            limit: 1–100, default 25.
            days: how far back to look, 1–365, default 90.

        Rows are ``{"kind", "id", "occurredAt", "title", "subtitle", "meta"}``
        where ``kind`` is one of ``page_view``, ``event``, ``conversation``,
        ``message``, ``survey``. ``id`` is the source row's id and is unique
        only *together with* ``kind`` — the five kinds come from five tables,
        so do not use ``id`` alone as a dict key.

        Unlike :meth:`list`, this route validates its query strictly and
        returns 400 rather than clamping.
        """
        return self._page(
            f"/v1/{encode_path('contacts', contact_id)}/journey",
            {"cursor": cursor, "limit": limit, "days": days, **params},
        )


    def iter_journey(
        self,
        contact_id: str,
        *,
        limit: Optional[int] = None,
        days: Optional[int] = None,
        **params: Any,
    ) -> Iterator[JsonDict]:
        """A contact's whole timeline, as a generator.

            for row in client.contacts.iter_journey(contact_id, days=30):
                print(row["occurredAt"], row["kind"], row["title"])

        The cursor on this route is **an ISO-8601 instant**, not an opaque
        blob: the server sets ``nextCursor`` to the ``occurredAt`` of the last
        row it returned. That is still a cursor — walk it, and never build one
        yourself. Constructing a timestamp looks like it ought to work and
        silently changes which rows you get, because the window is
        half-open on a field that several rows can share.

        ``limit`` is the page size, not a total; ``days`` bounds how far back
        the whole walk reaches (1–365, default 90).
        """
        return self._walk(
            f"/v1/{encode_path('contacts', contact_id)}/journey",
            {"limit": limit, "days": days, **params},
        )


    def mood(self, contact_id: str, *, days: Optional[int] = None, **params: Any) -> JsonDict:
        """A contact's sentiment trend, in weekly buckets.

        Args:
            days: **7**–365, default 90. **Rejected with a 400** below 7,
                unlike :meth:`journey`, whose floor is 1 — the two windows on
                the same resource do not agree, and this is the one that
                refuses.

        Returns ``{"contactId", "days", "sampleCount", "buckets"}``, where
        ``days`` echoes what you asked so a chart can label itself.

        **``buckets: []`` with a low ``sampleCount`` is the ordinary
        not-enough-signal answer, not an error**: fewer than three scored
        messages yields no buckets, and ``sampleCount`` is still populated so
        you can say "not enough yet" rather than "neutral".

        Buckets are weekly, snapped to **UTC Monday midnight**, ascending.
        ``averageScore`` is a sentiment score rounded to three decimals and
        **can be negative**.

        It reads a cache the AI pipeline fills, so it reflects what has been
        scored rather than live traffic. A contact outside the workspace is a
        404.
        """
        return self._get_obj(
            f"/v1/{encode_path('contacts', contact_id)}/mood",
            {"days": days, **params},
        )

    def cards(
        self, contact_id: str, *, conversation_id: Optional[str] = None
    ) -> JsonDict:
        """Render the workspace's customer cards for one contact. Answers 201.

        Returns ``{"cards": [...]}``, each
        ``{"key", "title", "state", "blocks", "text"}``.

        **A POST, and a read.** Not cacheable, and a contact id beside a
        conversation id in a query string would land in every access log next
        to the contact's email — so the arguments travel in a body. The body
        is strict, so ``conversation_id`` is the only thing it accepts.

        ``state`` is where you look when a panel is empty: ``ok``, ``empty``,
        ``missing``, ``invalid`` or ``error``. **``blocks: None`` is a real
        value** meaning there is no data for this contact, not a failure, and
        ``state`` distinguishes the five reasons.

        ``cards: []`` means the workspace configured none — **and also that
        the contact is not in this workspace**, because a missing contact
        answers with an empty list rather than a 404.

        This makes **live outbound HTTP** to the operator's own backend for
        every uncached card, so expect it to be the slowest call in this
        namespace. Configuration lives on
        :class:`chatly.resources.customer_cards.CustomerCards`.
        """
        body: JsonDict = {}
        if conversation_id is not None:
            body["conversationId"] = conversation_id
        return self._post_obj(
            f"/v1/{encode_path('contacts', contact_id)}/cards", body
        )


def _compact(body: Mapping[str, Any]) -> JsonDict:
    """Drop ``None`` fields so an omitted argument is an absent key.

    Safe to do on this route specifically, because none of its fields is
    nullable: there is no "clear it" to confuse with "I did not pass this".

    That is **not** true everywhere on the API. ``PATCH /v1/macros/{id}``
    distinguishes an omitted ``shortCode`` (leave it) from an explicit
    ``null`` (clear it), which is why
    :meth:`chatly.resources.macros.Macros.update` takes wire-named keyword
    arguments and filters nothing.
    """
    return {k: v for k, v in body.items() if v is not None}


__all__ = ["Contacts"]
