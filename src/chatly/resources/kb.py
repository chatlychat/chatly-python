"""``client.kb`` — help-centre articles and collections."""

from __future__ import annotations

from typing import Any, Iterator, List, Optional, Sequence, Union

from .._transport import encode_path
from ..pagination import Page
from ._base import CsvValue, JsonDict, Resource, as_list, csv


class KnowledgeBase(Resource):
    """Read the knowledge base. Read-only: writing an article needs a person.

    An article has 41 fields, including ``id``, ``collectionId``, ``slug``,
    ``title``, ``body``, ``bodyHtml``, ``locale``, ``status``,
    ``authorUserId``, ``publishedAt``, ``tags``, the view/helpful counters,
    the SEO fields (``metaTitle``, ``metaDescription``, ``ogImageUrl``,
    ``canonicalUrl``, ``noindex``), the docs-connector provenance fields
    (``source``, ``sourceId``, ``externalId``, ``sourceUrl``,
    ``sourceSyncedAt``, ``contentHash``, ``sourceConfidence``,
    ``sourceStale``, ``sourceAgeDays``, ``sourceVerifiedAt``) and the draft
    fields (``draftTitle``, ``draftBody``, ``draftFields``, …).
    """

    def articles(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        fields: CsvValue = None,
        filter: Union[None, str, Sequence[str]] = None,
        **params: Any,
    ) -> Page[JsonDict]:
        """One page of articles.

        Args:
            cursor: from the previous page's ``next_cursor``.
            limit: 1–100, default 25.
            sort: ``id``, ``title``, ``status``, ``publishedAt``,
                ``createdAt`` or ``updatedAt``, with a ``-`` prefix for
                descending. Default ``createdAt`` descending.

                **Do not pass ``position``.** It is in the route's sort
                allow-list but missing from the column map behind it, so it
                passes validation and then fails with a 400 from the paging
                layer. That is a bug in the API, not in this SDK.
            fields: a projection, comma-joined. It cannot name ``source``,
                ``externalId``, ``sourceUrl``, ``sourceSyncedAt``,
                ``contentHash`` or any ``draft*`` field — asking for one is a
                400 — even though all of them arrive when ``fields`` is
                omitted.
            filter: one clause or several, repeated on the wire. Grammar
                ``field:value`` / ``field:op:value`` / ``field:null`` /
                ``field:notnull``; operators ``eq``, ``ne``, ``in``, ``gt``,
                ``gte``, ``lt``, ``lte``, ``null``, ``notnull``. Filterable:
                ``collectionId``, ``status`` (``draft``/``published``/
                ``archived``, case-sensitive), ``locale``, ``authorId`` (the
                filter name for the response's ``authorUserId``),
                ``createdAt``, ``updatedAt``, ``sourceId``, ``sourceStale``.

        **There is no ``status``, ``locale``, ``collectionId`` or ``q``
        parameter on this route** — they were replaced by ``filter`` and any
        leftover use of them is silently stripped, giving a 200 with
        *unfiltered* results. If you expected published articles only and got
        drafts, that is why; use ``filter="status:eq:published"``.

        To search article text, use :meth:`chatly.resources.search.Search.kb`.
        """
        return self._page(
            "/v1/kb/articles",
            {
                "cursor": cursor,
                "limit": limit,
                "sort": sort,
                "fields": csv(fields),
                "filter": filter,
                **params,
            },
        )

    def iter_articles(self, **params: Any) -> Iterator[JsonDict]:
        """Every matching article, as a generator.

            published = client.kb.iter_articles(filter="status:eq:published")
            for article in published:
                print(article["slug"])
        """
        params.pop("cursor", None)
        if "fields" in params:
            params["fields"] = csv(params["fields"])
        return self._walk("/v1/kb/articles", params)

    def article(self, slug: str) -> JsonDict:
        """One article by **slug**.

        Not by id: the route matches on ``slug`` only and has no id branch,
        so passing a UUID gets a 404. Slugs may contain ``/`` and ``.``; this
        method percent-encodes them.

        Returns any status, drafts included — it is the authoring read, not
        the public one. The unauthenticated help-centre route
        (``/v1/public/kb/{workspaceId}/articles/{slug}``) has a different,
        narrower projection and is not part of this SDK.
        """
        return self._get_obj(f"/v1/kb/articles/{encode_path(slug)}")

    def collections(self) -> List[JsonDict]:
        """Every collection, as a bare list. No parameters, no paging.

        ``{"id", "workspaceId", "createdAt", "updatedAt", "name", "slug",
        "description", "iconKey", "order", "parentId", "docsSourceId"}``,
        ordered by ``order`` then ``name``.

        **Flat, not a tree.** Nesting is expressed by ``parentId``; there is
        no ``children`` array, so build the tree yourself if you need one.
        """
        return as_list(self._get("/v1/kb/collections"))


__all__ = ["KnowledgeBase"]
