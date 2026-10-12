"""``client.channels`` — the mediums conversations arrive on."""

from __future__ import annotations

from typing import List

from .._transport import encode_path
from ._base import JsonDict, Resource, as_list


class Channels(Resource):
    """Read channel configuration. Read-only for an API key.

    A channel is ``{"id", "workspaceId", "brandId", "type", "name",
    "publicId", "enabled", "config", "autoCreateTickets",
    "autoAcknowledge", "acknowledgeTemplate", "acknowledgeSubject",
    "createdAt", "updatedAt", "originsRestricted", "embed"}``.

    Three fields need explaining:

    * **``config`` is redacted.** Any key that looks like a credential
      (``secret``, ``apiKey``, ``accessToken``, ``clientSecret``,
      ``botToken``, ``webhookSecret``, ``verifyToken``, ``refreshToken`` and
      about 45 more) comes back as the literal string ``"__redacted__"``,
      recursing through nested objects and arrays. An **empty string is not
      redacted** — that means "not configured", and the distinction is the
      point: it is how you tell a channel that has no token from one whose
      token you are not allowed to see.

    * **``originsRestricted`` is tri-state.** ``None`` for every non-``web``
      channel. ``True`` means an allow-list is enforced. **``False`` means
      the allow-list is empty or blank, i.e. ANY origin is admitted** — it
      is not "restriction is off because this is safe", it is "this widget
      will load on anyone's site". It exists as a field precisely because an
      empty list is invisible in JSON.

    * **``embed``** (``None`` for non-``web``) carries ``loaderUrl``,
      ``scriptOrigin``, ``connectOrigins``, ``initGlobal``, ``snippet`` and
      ``contentSecurityPolicy: {"scriptSrc", "connectSrc"}`` — everything
      needed to install the widget and write a CSP for it.

    ``type`` is one of ``web``, ``email``, ``whatsapp``, ``messenger``,
    ``instagram``, ``sms``, ``voice``, ``api``, ``telegram``,
    ``telegram_user``, ``discord``, ``apple``, ``line``, ``viber``,
    ``slack``, ``msteams``, ``tiktok``, ``twitter``.
    """

    def list(self) -> List[JsonDict]:
        """Every channel, as a bare list. No parameters, no paging."""
        return as_list(self._get("/v1/channels"))

    def get(self, channel_id: str) -> JsonDict:
        """One channel by id. Same shape as a :meth:`list` row.

        ``GET /v1/channels/adapters`` is a *different* route declared before
        this one, so ``get("adapters")`` returns a list of adapter names
        rather than a channel. Pass an id.
        """
        return self._get_obj(f"/v1/{encode_path('channels', channel_id)}")


__all__ = ["Channels"]
