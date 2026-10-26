"""``client.channels`` — the mediums conversations arrive on."""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from .._transport import encode_path
from ..errors import InvalidArgumentError
from ._base import JsonDict, Resource, as_list

#: The channel types ``POST /v1/channels`` accepts.
#:
#: Seventeen, and ``telegram_user`` is **not** among them even though it can
#: come back on a read: that channel is created by an OAuth flow, not by this
#: route.
CHANNEL_TYPES = (
    "web",
    "email",
    "whatsapp",
    "messenger",
    "instagram",
    "sms",
    "voice",
    "api",
    "telegram",
    "discord",
    "apple",
    "line",
    "viber",
    "slack",
    "msteams",
    "tiktok",
    "twitter",
)


class Channels(Resource):
    """Read and configure the mediums conversations arrive on.

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
      ``scriptOrigin``, ``connectOrigins``, ``uploadOrigin``, ``fileOrigin``,
      ``deprecatedFileOrigins``, ``initGlobal``, ``snippet`` and
      ``contentSecurityPolicy: {"scriptSrc", "connectSrc", "imgSrc",
      "mediaSrc"}`` — everything needed to install the widget and write a CSP
      for it. This list said ``{"scriptSrc", "connectSrc"}`` while the server
      had been returning four keys, which is the direction of drift that
      matters: a caller trusting it writes a CSP with no ``imgSrc`` and every
      attachment silently fails to render. ``deprecatedFileOrigins`` carries
      file hosts being retired and is ``[]`` normally — put it in ``imgSrc``
      beside ``fileOrigin``, because objects uploaded before a host moved are
      still served from the old one.

    ``type`` on a read is one of ``web``, ``email``, ``whatsapp``,
    ``messenger``, ``instagram``, ``sms``, ``voice``, ``api``, ``telegram``,
    ``telegram_user``, ``discord``, ``apple``, ``line``, ``viber``,
    ``slack``, ``msteams``, ``tiktok``, ``twitter``. :data:`CHANNEL_TYPES`
    is the narrower set :meth:`create` accepts.

    Reads need ``channels:read``, writes ``channels:write``. Deleting a
    channel and reading a channel's secret both require a signed-in person,
    so neither is here — note that makes :meth:`rotate_secret` the only way
    a key ever sees an API channel's secret.
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


    def adapters(self) -> List[JsonDict]:
        """The channel types this deployment can actually serve.

        A bare list of **strings**, sorted and de-duplicated — not objects.

        It is the union of the inbound-adapter registry and every outbound
        route handled by the realtime service. That second half is the point:
        ``web`` has no inbound adapter by design, and a registry-only answer
        reported the product's own primary channel as "coming soon".

        Values use the same vocabulary as :meth:`create`'s ``type``. Static
        per deployment, so cache it.
        """
        return as_list(self._get("/v1/channels/adapters"))

    def create(
        self,
        *,
        type: str,
        name: str,
        public_id: str,
        brand_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        config: Optional[Mapping[str, Any]] = None,
        **extra: Any,
    ) -> JsonDict:
        """Create a channel. Answers 201 with the saved channel.

        Args:
            type: one of :data:`CHANNEL_TYPES`. Checked locally, because the
                enum is narrower than what a read returns.
            name: 1–120 characters.
            public_id: 1–64 characters. For a ``web`` channel this is the id
                the widget snippet carries, so it ends up in a customer's
                page source.
            brand_id: omitted resolves the workspace's **default brand** —
                and is a **404 "Default brand"** if the workspace has none,
                which reads like the channel was not found.
            enabled: default ``True``.
            config: provider configuration, default ``{}``. Validated and
                normalised per ``type`` **before** the row is written, so a
                bad provider config is a 4xx rather than a broken channel.

        The response ``config`` is **redacted** — credential-ish keys read
        the literal ``__redacted__``. The reveal route is not key-accessible,
        so a key never reads back what it just sent here.

        Subject to the plan's channel ceiling, which answers 402/409 rather
        than creating a channel you are not entitled to.
        """
        if type not in CHANNEL_TYPES:
            raise InvalidArgumentError(
                f"unknown channel type {type!r}; expected one of {', '.join(CHANNEL_TYPES)}"
            )
        body: JsonDict = {"type": type, "name": name, "publicId": public_id}
        for key, value in (
            ("brandId", brand_id),
            ("enabled", enabled),
            ("config", dict(config) if config is not None else None),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return self._post_obj("/v1/channels", body)

    def update(self, channel_id: str, **fields: Any) -> JsonDict:
        """Update a channel. Every field optional, **wire** names.

        Accepts ``name``, ``enabled``, ``autoCreateTickets``,
        ``autoAcknowledge``, ``acknowledgeTemplate`` (nullable),
        ``acknowledgeSubject`` (nullable), ``config`` and ``configMode``.
        **Not ``type``, ``publicId`` or ``brandId``** — none is patchable.

        **``configMode`` defaults to ``"merge"``**, which is JSON merge-patch:
        the keys you send are written, a ``None`` **deletes** a key, and
        everything else is left alone. ``"replace"`` wipes the whole object
        and is opt-in for a reason — the old replace-by-default behaviour
        destroyed themes, allowed origins and identity-verification secrets
        whenever anyone patched a single key.

        Two useful behaviours. Echoing a ``__redacted__`` marker back
        **restores the stored plaintext** — that is what the marker is for,
        so a read-modify-write round trip is safe. And rotating the
        identity-verification secret keeps the previous one verifying for a
        grace window rather than breaking every signed-in visitor at once.

        **An empty body is a 409**, not a no-op. A channel outside the
        workspace is a 404.
        """
        return self._patch_obj(
            f"/v1/{encode_path('channels', channel_id)}", dict(fields)
        )

    def rotate_secret(self, channel_id: str) -> JsonDict:
        """Mint a new secret for an **API** channel. Answers 201.

        Returns ``{"secret": "csk_..."}``.

        **Only ``type: "api"`` channels have one.** Every other provider
        issues its own credential, so this is a **409** on them, with a
        message saying so.

        It is a hard cut: the old secret stops working immediately, with no
        grace window, so the integration is broken until the new value is
        deployed. And although the server can re-read this secret, the route
        that does is **not** available to an API key — so for a key-driven
        integration **this response is the only chance to capture it**.

        It is also the one write on this resource that does not demand an
        ``Idempotency-Key``; the SDK sends one anyway, which makes a retried
        rotation a replay rather than a second secret.
        """
        return self._post_obj(
            f"/v1/{encode_path('channels', channel_id)}/secret/rotate"
        )


__all__ = ["CHANNEL_TYPES", "Channels"]
