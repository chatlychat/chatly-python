"""Widget identity verification — the backend half. Contract §7.

When a workspace turns identity verification on, the widget has to prove that
the ``externalId`` it claims was issued by your backend rather than typed into
a browser console. Without it, anyone can open a chat as anyone else's
account. :func:`identity_hash` is what your server computes:

    user_hash = chatly.identity_hash(os.environ["CHATLY_IDV_SECRET"], user.id)
    # render into the page:
    #   Chatly('identify', { externalId: user.id, userHash: user_hash, ... })

The secret is the workspace's identity-verification secret and must never
reach a browser — only the digest does. If it leaks, rotate it in the
dashboard; every previously issued digest stops being accepted.
"""

from __future__ import annotations

import hashlib
import hmac

from .errors import InvalidArgumentError


def identity_hash(secret: str, external_id: str) -> str:
    """HMAC-SHA256 of ``external_id`` under ``secret``, lowercase hex.

    Args:
        secret: the workspace's identity-verification secret (``sek_…``).
        external_id: your own stable id for the signed-in user. Use the one
            you also pass to the widget as ``externalId``; a digest over a
            different string verifies against nothing.

    Raises:
        InvalidArgumentError: if either argument is empty. An empty secret is
            a valid HMAC key, which is exactly the problem — it would produce
            a digest anyone can forge, and the likeliest cause is an
            environment variable that did not get set.

    Pinned vector (contract §10.8, cross-checked across implementations)::

        identity_hash("sek_test_secret", "user_42")
        # '5e26772dce97d5ba995796e621f83f2e97e6f8c3f9386dbf153a98ab24c10271'
    """
    if not isinstance(secret, str) or secret == "":
        raise InvalidArgumentError("identity_hash: secret is empty")
    if not isinstance(external_id, str) or external_id == "":
        raise InvalidArgumentError("identity_hash: external_id is empty")
    return hmac.new(
        secret.encode("utf-8"), external_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()


__all__ = ["identity_hash"]
