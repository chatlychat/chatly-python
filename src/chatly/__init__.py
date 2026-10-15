"""Chatly — the official Python SDK for the Chatly live-chat platform.

Backend only. It authenticates with a workspace API key (``ck_…``), which is
a bearer credential for the whole workspace, so it belongs in server-side
code and nowhere else.

    import os
    import chatly

    client = chatly.ChatlyClient(api_key=os.environ["CHATLY_API_KEY"])

    me = client.whoami()
    print(me["workspaceId"], me["scopes"])

    for contact in client.contacts.iter_list():
        print(contact["email"])

Zero runtime dependencies: everything here is the standard library.

What is in this package:

* :class:`ChatlyClient` — the client, with twenty-three resource namespaces,
  :meth:`~ChatlyClient.whoami`, :meth:`~ChatlyClient.with_idempotency_key`
  and :meth:`~ChatlyClient.request`, the escape hatch to any endpoint.
* :func:`verify_webhook_signature` — verify a delivery in your own handler.
* :func:`verify_chatly_signature` — verify ANY signed request Chatly sends
  (eight surfaces, the unified v2 header, key rotation), with a reason on
  every refusal rather than a bare ``False``.
* :func:`identity_hash` — the backend half of widget identity verification.
* A typed error per HTTP failure mode; see :mod:`chatly.errors`.
* :class:`Page` and the ``iter_*`` generators for cursor pagination.
"""

from __future__ import annotations

from ._transport import (
    DEFAULT_API_URL,
    HTTPRequest,
    HTTPResponse,
    Transport,
    UrllibTransport,
)
from ._version import USER_AGENT, __version__
from .client import ChatlyClient
from .errors import (
    APIError,
    AuthenticationError,
    BadRequestError,
    ChatlyError,
    ChatlyTimeoutError,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    PaginationError,
    PermissionDeniedError,
    RateLimitError,
    ResponseDecodeError,
    ServerError,
    TransportError,
    ValidationError,
)
from .identity import identity_hash
from .pagination import Page, iter_items, iter_pages, page_from_payload
from .retry import NO_RETRIES, RetryPolicy
from .signatures import (
    CHATLY_SIGNATURE_FAILURES,
    CHATLY_SIGNATURE_SURFACES,
    CHATLY_SIGNATURE_TOLERANCE_SECONDS,
    CHATLY_V2_SIGNATURE_HEADER,
    ChatlySignatureResult,
    SurfaceSpec,
    verify_chatly_signature,
)
from .webhooks import (
    DEFAULT_TOLERANCE_SECONDS,
    SIGNATURE_HEADER,
    verify_webhook_signature,
)

__all__ = [
    # client
    "ChatlyClient",
    "DEFAULT_API_URL",
    "USER_AGENT",
    "__version__",
    # helpers
    "identity_hash",
    "verify_webhook_signature",
    "DEFAULT_TOLERANCE_SECONDS",
    "SIGNATURE_HEADER",
    "verify_chatly_signature",
    "ChatlySignatureResult",
    "SurfaceSpec",
    "CHATLY_SIGNATURE_FAILURES",
    "CHATLY_SIGNATURE_SURFACES",
    "CHATLY_SIGNATURE_TOLERANCE_SECONDS",
    "CHATLY_V2_SIGNATURE_HEADER",
    # errors
    "APIError",
    "AuthenticationError",
    "BadRequestError",
    "ChatlyError",
    "ChatlyTimeoutError",
    "ConflictError",
    "InvalidArgumentError",
    "NotFoundError",
    "PaginationError",
    "PermissionDeniedError",
    "RateLimitError",
    "ResponseDecodeError",
    "ServerError",
    "TransportError",
    "ValidationError",
    # pagination
    "Page",
    "iter_items",
    "iter_pages",
    "page_from_payload",
    # retries and transport
    "NO_RETRIES",
    "RetryPolicy",
    "Transport",
    "UrllibTransport",
    "HTTPRequest",
    "HTTPResponse",
]
