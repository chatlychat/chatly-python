"""``client.brands`` — optional sub-tenants inside one workspace."""

from __future__ import annotations

from typing import Any, List

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list


class Brands(Resource):
    """Multi-brand configuration: name, slug, look, and reply domain.

    Reads need ``workspace:read``; writes ``workspace:write``.

    A brand is ``{"id", "workspaceId", "name", "slug", "domain",
    "isDefault", "logoUrl", "primaryColor", "supportEmail", "replyDomain",
    "icons", "createdAt", "updatedAt"}``. The five presentational fields and
    ``icons`` are **not columns** — the server flattens them out of a stored
    ``branding`` object, which is never returned itself — and they come back
    as ``None`` rather than absent when unset.
    """

    def list(self) -> List[JsonDict]:
        """Every brand, with usage counts. A bare list, ordered by name.

        **Each row carries ``usage``** —
        ``{"channels", "conversations", "triggers", "workflows"}``, four
        non-negative integers, always present. There is a usage-free listing
        in the service and this route deliberately does not use it, because
        the counts are what tell you whether a brand can be deleted.

        Soft-deleted brands are excluded.
        """
        return as_list(self._get("/v1/brands"))

    def create(self, *, name: str, slug: str, **fields: Any) -> JsonDict:
        """Create a brand. Answers 201. ``fields`` takes **wire** names.

        Args:
            name: 1–120 characters.
            slug: 1–64, lowercase alphanumeric and hyphens, and it may
                neither start nor end with a hyphen.

        Optional: ``logoUrl``, ``primaryColor``, ``supportEmail``,
        ``replyDomain``, ``icons``, ``domain``, ``isDefault``.

        ``primaryColor`` must be a **six**-digit hex with a leading ``#``.
        The three-digit form and named colours are both 400s.

        **``domain`` and ``replyDomain`` are different things**, and this is
        the mistake worth naming: ``domain`` is the help-centre hostname,
        while ``replyDomain`` is where ``reply+…@`` addresses are received.
        Setting ``replyDomain`` **enables nothing on its own** — the domain
        also has to be claimed and verified through ``POST /v1/domains`` with
        ``kind: "email"``, which is not in this namespace. It is lowercased
        and trimmed on write, and it is a bare hostname, not a URL.

        ``icons`` is a partial map over ``attachment``, ``emoji``, ``mic``,
        ``stop``, ``check``, ``star``; each value may be an inline ``<svg>``,
        an image URL or a literal character, and is **refused** — not
        sanitised — if it contains a script tag, an ``on*=`` handler, a
        ``javascript:`` URL or a ``<foreignObject>``.

        **``isDefault=True`` demotes every other brand**: at most one default
        exists per workspace, enforced by a unique index rather than by
        politeness.
        """
        body: JsonDict = {"name": name, "slug": slug}
        body.update(fields)
        return self._post_obj("/v1/brands", body)

    def update(self, brand_id: str, **fields: Any) -> JsonDict:
        """Update a brand. Every field optional, **wire** names.

        An empty body is accepted and rewrites the row with its existing
        values.

        Two asymmetries with :meth:`create`. **``icons`` merges per key**
        rather than replacing the map, so a form that sends one icon does not
        clear the other five — and there is therefore no way to clear the
        whole set in one call. And ``name``, ``slug``, ``domain`` and
        ``isDefault`` fall back to the stored value when omitted *or null*,
        so **``domain`` cannot be cleared through this route**.

        ``isDefault=True`` demotes the others, as on create. A missing brand
        is a 404 — but note the id is **not** validated as a UUID here, so a
        malformed one surfaces as a 500 rather than a 400. Pass an id from
        :meth:`list`.
        """
        return self._patch_obj(f"/v1/{encode_path('brands', brand_id)}", dict(fields))

    def delete(self, brand_id: str) -> JsonDict:
        """Soft-delete a brand. Returns ``{"id": ...}`` with a **200**.

        Not a 204, and note the shape: ``{"id"}``, where
        :meth:`chatly.resources.bot_routes.BotRoutes.delete` answers
        ``{"deleted": true}``. Two deletes, two shapes.

        Two **409**s stand in the way, both of them useful: the workspace's
        **default** brand cannot be deleted until another is made default,
        and a brand **any channel still points at** cannot be deleted either
        — that message carries the count, which is what
        :meth:`list`'s ``usage`` is for.

        Conversations, triggers and workflows are deliberately left attached:
        the row survives with ``deletedAt`` set so that history still renders
        the brand it happened under.
        """
        return self._delete_obj(f"/v1/{encode_path('brands', brand_id)}")


__all__ = ["Brands"]
