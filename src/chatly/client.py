"""The client. One object, thirteen namespaces, one escape hatch."""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Mapping, Optional

from ._transport import DEFAULT_API_URL, QueryParams, Requester, Transport
from .errors import InvalidArgumentError
from .pagination import Page, page_from_untyped_payload
from .resources import (
    Billing,
    Channels,
    Contacts,
    Conversations,
    Events,
    KnowledgeBase,
    Macros,
    Reports,
    Search,
    Tickets,
    Webhooks,
    Workspace,
)
from .resources._base import JsonDict, as_object
from .retry import RetryPolicy


class ChatlyClient:
    """A server-side client for the Chatly API.

    **Backend only.** It authenticates with a workspace API key (``ck_…``),
    which is a bearer credential for the *entire* workspace: every contact,
    every conversation, every report. Never ship it to a browser, a mobile
    app, or anything else a customer can read. The browser-side SDK is
    ``@chatlychat/sdk-js`` and it uses a public channel id instead.

        import chatly

        client = chatly.ChatlyClient(api_key=os.environ["CHATLY_API_KEY"])
        print(client.whoami())

    Args:
        api_key: the workspace API key. Rejected at construction if empty,
            so a missing environment variable fails here rather than at some
            later call.
        api_url: override only for a self-hosted install. Defaults to
            ``https://api.chatlychat.com``.
        timeout: seconds per attempt, default 15. Not a budget for the whole
            call: three attempts with backoff can take longer.
        retry: a :class:`~chatly.retry.RetryPolicy`. The default retries
            connection errors, 429 and 5xx up to three attempts total with
            jittered backoff, honouring ``Retry-After``. Pass
            :data:`chatly.retry.NO_RETRIES` to turn it off.
        transport: an injectable HTTP transport. Tests pass a fake and need
            no network; see ``tests/support.py``.
        sleep: the function used to wait between retries. A seam for tests,
            which would otherwise sit through real backoff.

    Attributes:
        contacts: :class:`~chatly.resources.contacts.Contacts`
        conversations: :class:`~chatly.resources.conversations.Conversations`
        tickets: :class:`~chatly.resources.tickets.Tickets`
        macros: :class:`~chatly.resources.macros.Macros`
        kb: :class:`~chatly.resources.kb.KnowledgeBase`
        search: :class:`~chatly.resources.search.Search`
        events: :class:`~chatly.resources.events.Events`
        webhooks: :class:`~chatly.resources.webhook_deliveries.Webhooks`
        reports: :class:`~chatly.resources.reports.Reports`
        channels: :class:`~chatly.resources.channels.Channels`
        billing: :class:`~chatly.resources.billing.Billing`
        workspace: :class:`~chatly.resources.workspace.Workspace`

    Thread safety: a client holds no per-request state, and the default
    transport builds one ``urllib`` opener that is used per call without
    shared mutable state, so sharing an instance across threads is fine.
    Each call mints its own ``Idempotency-Key`` — except on a client returned
    by :meth:`with_idempotency_key`, which is the point of that method and is
    therefore **not** something to share between concurrent operations.
    """

    def __init__(
        self,
        api_key: str,
        *,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 15.0,
        retry: Optional[RetryPolicy] = None,
        transport: Optional[Transport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._wire(
            Requester(
                api_key=api_key,
                api_url=api_url,
                timeout=timeout,
                retry=retry,
                transport=transport,
                sleep=sleep,
            )
        )

    def _wire(self, requester: Requester) -> None:
        """Attach every namespace to ``requester``.

        The ONLY place namespaces are constructed, so a derived client cannot
        be built with some namespaces pointing at the wrong requester. The
        Node SDK derived clients by rebinding namespaces one at a time and
        missed one, which went on using the parent's configuration; routing
        both construction paths through here makes that unrepresentable
        rather than merely tested.
        """
        self._requester = requester
        self.contacts = Contacts(requester)
        self.conversations = Conversations(requester)
        self.tickets = Tickets(requester)
        self.macros = Macros(requester)
        self.kb = KnowledgeBase(requester)
        self.search = Search(requester)
        self.events = Events(requester)
        self.webhooks = Webhooks(requester)
        self.reports = Reports(requester)
        self.channels = Channels(requester)
        self.billing = Billing(requester)
        self.workspace = Workspace(requester)

    # ---- credential --------------------------------------------------

    def whoami(self) -> JsonDict:
        """Describe the credential: its workspace and its scopes.

        Returns ``{"workspaceId": ..., "scopes": [...]}`` — exactly two keys.

        Make this your first call. It turns a mis-scoped or wrong-workspace
        key into an obvious error at integration time instead of a 403 from
        an unrelated endpoint next week. ``scopes`` is the real narrowed
        grant for a ``ck_`` key, so you can check for ``contacts:write``
        before trying to use it.

        ``GET /v1/api-keys/whoami`` is deliberately the only route on the
        api-keys controller that an API key may call — managing keys with a
        key is a privilege-escalation shape.
        """
        return as_object(self._requester.request("GET", "/v1/api-keys/whoami"))

    # ---- idempotency -------------------------------------------------

    def with_idempotency_key(self, key: Optional[str] = None) -> "ChatlyClient":
        """A derived client that pins one ``Idempotency-Key`` across writes.

        Every write normally mints a fresh UUID, so an SDK-level retry cannot
        double-write. Pin a key when you want to retry the *same logical
        operation* across process boundaries — a job that may be redelivered,
        a webhook handler that may be called twice:

            key = str(uuid.uuid4())           # store this with your job
            client.with_idempotency_key(key).conversations.send(cid, "hi")

        Same key + same body replays the first response. Same key +
        **different** body is a 409 with code ``idempotency_conflict``
        (:attr:`chatly.errors.ConflictError.is_idempotency_conflict`) — the
        server is telling you the retry is not the operation it recorded, and
        retrying it unchanged will fail identically forever.

        Args:
            key: the key to pin. Omit it to have one generated — useful when
                you want several writes in a block to share a key you do not
                need to name. Must be a UUID or a 16–128 character opaque
                token; the server rejects anything else with a 400, so this
                checks the shape locally first.

        Returns a new client. The original is untouched, and the two share a
        transport. The pinned client is not safe to use for *unrelated*
        concurrent writes — that is what pinning means.
        """
        pinned = str(uuid.uuid4()) if key is None else key
        if not isinstance(pinned, str):
            raise InvalidArgumentError("idempotency key must be a string")
        if not _plausible_idempotency_key(pinned):
            raise InvalidArgumentError(
                "idempotency key must be a UUID or an opaque token of 16-128 characters; "
                f"got {len(pinned)} character(s)"
            )
        clone = object.__new__(ChatlyClient)
        clone._wire(self._requester.pinned(pinned))
        return clone

    @property
    def idempotency_key(self) -> Optional[str]:
        """The pinned key, or ``None`` if this client mints one per write."""
        return self._requester.pinned_idempotency_key

    # ---- the escape hatch --------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[QueryParams] = None,
        body: Any = None,
    ) -> Any:
        """Call any endpoint, through the same auth, idempotency and retries.

        Contract §8. 140 of the API's 886 routes accept an API key and 55
        have a typed method here; the other 85 are reachable through this.
        Without it, using one of them means abandoning the SDK and
        hand-rolling HTTP with a bearer token — and losing the retry policy
        and the typed errors with it.

            vocabulary = client.request("GET", "/v1/macros/actions")
            client.request("PUT", f"/v1/api-keys/{key_id}/machine-user",
                           body={"userId": machine_user_id})

        Args:
            method: an HTTP verb. ``POST``, ``PUT``, ``PATCH`` and
                ``DELETE`` get an ``Idempotency-Key`` automatically, and
                ``POST``/``PUT``/``PATCH`` with no ``body`` send ``{}``.
            path: an absolute path starting with ``/``, e.g. ``/v1/labels``.
                **Already-encoded** — if a segment comes from user data,
                percent-encode it yourself with
                :func:`chatly._transport.encode_path`.
            query: parameters. ``None`` values are dropped; a list becomes a
                repeated key.
            body: anything JSON-serialisable.

        Returns the decoded JSON, or ``None`` for a 204 or an empty body.
        Raises the same typed errors as every other method.
        """
        return self._requester.request(method, path, query=query, body=body)

    def paginate(
        self, path: str, *, query: Optional[Mapping[str, Any]] = None
    ) -> Page[JsonDict]:
        """One page from any cursor-paginated route, as a :class:`Page`.

        The pagination half of the escape hatch — several of the 85 untyped
        key-accessible routes are paged, and a caller should not have to
        re-implement envelope parsing to walk one.

        A bare JSON array comes back as one cursor-less page, because an
        untyped path cannot know whether the route is paged and several of
        those routes are ``@PaginationExempt``. The typed methods are strict
        instead: each one knows its route's shape, and
        :func:`chatly.pagination.page_from_payload` raises
        :class:`~chatly.errors.ResponseDecodeError` on anything that is not
        an ``items`` envelope. Anything that is neither an array nor an
        envelope raises here too.
        """
        return page_from_untyped_payload(self.request("GET", path, query=query))

    def __repr__(self) -> str:
        """Identify the client without printing the key.

        Deliberately shows the URL and nothing else: a ``repr`` ends up in
        logs, exception context and notebooks, and an API key that reaches a
        log is a rotated key.
        """
        pinned = "" if self.idempotency_key is None else ", idempotency_key=<pinned>"
        return f"ChatlyClient(api_url={self._requester.api_url!r}{pinned})"


def _plausible_idempotency_key(key: str) -> bool:
    """Would the server accept this key's shape?

    It wants a UUID, or an opaque token of 16–128 characters. Checked here so
    a too-short key is a local error naming the rule, rather than a 400
    whose message a caller has to go and read.
    """
    try:
        uuid.UUID(key)
        return True
    except (ValueError, AttributeError, TypeError):
        return 16 <= len(key) <= 128


__all__ = ["ChatlyClient"]
