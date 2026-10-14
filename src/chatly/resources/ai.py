"""``client.ai`` — provider credentials, custom tools, house tone, spend."""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

from .._transport import encode_path
from ..errors import InvalidArgumentError
from ._base import JsonDict, Resource, as_list

#: The providers a workspace can bring its own key for.
#:
#: Checked locally because the route re-parses the path segment through the
#: same enum and answers **422** on a miss — not a 404, which is what a
#: wrong-looking path usually means.
AI_PROVIDERS = ("openai", "anthropic", "deepgram")

#: The five tone-rule categories. The server caps each at 8 rules.
TONE_CATEGORIES = ("empathy", "language", "formality", "personality", "warmth")


class AI(Resource):
    """BYO provider keys, custom tools, the house tone, and the spend meter.

    Reads need ``ai:read``, writes ``ai:write``, and :meth:`quota` needs
    ``workspace:billing:read`` — it is a billing figure, not an AI one.

    **Every write in this namespace requires an ``Idempotency-Key``**, which
    this SDK mints per call. Two of them are worth pinning deliberately
    (:meth:`generate_tone` and :meth:`test_provider`), because a replayed key
    returns the cached body rather than doing the work again — which is the
    point on a retry and a surprise if you reuse a key for a second,
    genuinely new call.
    """

    # ---- provider credentials -------------------------------------------

    def providers(self) -> JsonDict:
        """Every supported provider and whether a key is stored for it.

        Returns ``{"providers": [...]}`` — **an object wrapping the list**,
        not a bare array.

        All three providers come back whether configured or not:
        ``configured: False`` is the normal state, not an omission. Each row
        carries ``provider``, ``label``, ``capability``, ``consoleUrl``,
        ``configured``, ``keyHint`` (four characters, nullable) and the last
        validation (``lastValidatedAt``, ``lastValidationStatus``,
        ``lastValidationMessage``, all nullable).

        No response on this route, or any other, returns a stored key.
        """
        return self._get_obj("/v1/ai-providers")

    def add_provider(self, provider: str, api_key: str) -> JsonDict:
        """Store a workspace's own key for ``provider``. Answers 201.

        Args:
            provider: one of :data:`AI_PROVIDERS`.
            api_key: the provider's key, 20–512 characters after trimming.
                The literal ``REDACTED`` is refused first, so echoing back a
                masked value from your own UI fails loudly instead of
                storing nonsense.

        **This makes a live call to the provider before storing**, and the
        outcome is in ``validation.status``:

        * ``ok`` — the key works.
        * ``unverified`` — the provider timed out, rate-limited us or was
          down. **This is a success**: the key is stored and settled later,
          either by itself or by :meth:`test_provider`.
        * ``rejected`` — the provider refused the credential, and then
          **nothing is stored and the call is a 422**. So a 201 never carries
          ``rejected``.

        Returns ``{"provider", "validation", "reindexQueued"}``.
        ``reindexQueued`` is how many embedding jobs were enqueued — it is 0
        for every provider but ``openai``, and capped at 500 — because
        switching the embedding key invalidates stored vectors.

        Storing a key for a provider that already has one **replaces** it.
        """
        if provider not in AI_PROVIDERS:
            raise InvalidArgumentError(
                f"unknown AI provider {provider!r}; expected one of {', '.join(AI_PROVIDERS)}"
            )
        return self._post_obj(
            "/v1/ai-providers", {"provider": provider, "apiKey": api_key}
        )

    def test_provider(self, provider: str) -> JsonDict:
        """Re-validate the stored key for ``provider``. Answers 201.

        Returns ``{"provider", "validation"}`` — no ``reindexQueued`` here,
        because nothing is stored.

        This is how an ``unverified`` row from :meth:`add_provider` gets
        settled. **A key that now fails authentication is recorded as failing
        and deliberately not deleted**, so a provider outage cannot silently
        disconnect a workspace.

        A provider with no key stored is a **404**.

        It is a write as far as idempotency goes, despite sending no body:
        reusing a pinned key replays the earlier verdict instead of testing
        again.
        """
        if provider not in AI_PROVIDERS:
            raise InvalidArgumentError(
                f"unknown AI provider {provider!r}; expected one of {', '.join(AI_PROVIDERS)}"
            )
        return self._post_obj(f"/v1/{encode_path('ai-providers', provider)}/test")

    # ---- custom tools ----------------------------------------------------

    def tools(self) -> List[JsonDict]:
        """The workspace's custom agent tools. A bare list.

        Ordered by ``name``, not by date. Disabled tools **are** listed
        (``enabled: False``); soft-deleted ones are not.

        A tool carries ``secretHeaderNames`` (names only) and
        ``signingSecretSet`` (a boolean) — never the values. A row whose
        encrypted header bag cannot be decrypted comes back with
        ``secretHeaderNames: []`` rather than failing the whole list, so an
        empty list there is "we could not read them", not "there are none".
        """
        return as_list(self._get("/v1/ai/tools"))

    def create_tool(
        self,
        *,
        name: str,
        description: str,
        url_template: str,
        method: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        parameters: Optional[Sequence[Mapping[str, Any]]] = None,
        timeout_seconds: Optional[int] = None,
        enabled: Optional[bool] = None,
        **extra: Any,
    ) -> JsonDict:
        """Declare an HTTP tool the AI agent may call. Answers 201.

        Args:
            name: ``^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$``, 2–64
                characters, and not one of the built-in tool names.
            description: required, and it is what the model reads to decide
                whether to call this at all.
            url_template: may interpolate ``{{param}}`` — but **not in the
                host**, and the host must pass the outbound SSRF guard, both
                checked at write time with a 422.
            method: ``GET`` (default), ``POST``, ``PUT``, ``PATCH`` or
                ``DELETE``.
            headers: plain headers. Reserved names are refused.
            parameters: up to 16 ``{"name", "type", "description",
                "required", "source"}``. ``description`` is required per
                parameter — an undescribed argument gets guessed at by the
                model. ``type`` is ``string``, ``number`` or ``boolean``.
            timeout_seconds: 1–30, default 20.
            enabled: default ``True``.

        ``extra`` carries the fields with cross-cutting rules, by wire name,
        because they have to be sent exactly as the server names them:
        ``secretHeaders``, ``signingSecret`` (32–256 characters),
        ``requiresVerifiedIdentity``, ``bodyTemplate``, ``requiresApproval``
        (``False``, ``True``, ``"agent"`` or ``"end_user"``),
        ``confirmTemplate``, ``approvalThresholdParam``,
        ``approvalThresholdValue``.

        Three cross-field rules, each a 422 rather than a silent drop:
        ``requiresApproval="end_user"`` **needs** ``confirmTemplate``; a
        ``confirmTemplate`` with any other audience is refused rather than
        ignored; and ``requiresVerifiedIdentity`` — or any parameter sourced
        from verified context — **needs** ``signingSecret``, because the tool
        has to be able to prove the claim came from us.
        """
        body: JsonDict = {
            "name": name,
            "description": description,
            "urlTemplate": url_template,
        }
        for key, value in (
            ("method", method),
            ("headers", dict(headers) if headers is not None else None),
            ("parameters", list(parameters) if parameters is not None else None),
            ("timeoutSeconds", timeout_seconds),
            ("enabled", enabled),
        ):
            if value is not None:
                body[key] = value
        body.update(extra)
        return self._post_obj("/v1/ai/tools", body)

    def update_tool(self, tool_id: str, **fields: Any) -> JsonDict:
        """Update a tool. Takes **wire** field names and filters nothing.

            client.ai.update_tool(tool_id, description="Looks up an order")
            client.ai.update_tool(tool_id, signingSecret=None)  # clear it

        Snake-case keywords are deliberately not offered here, because an
        explicit ``None`` has to be able to reach the server. Six fields are
        three-way — omit to keep, ``None`` to clear, a value to replace:
        ``secretHeaders``, ``signingSecret``, ``bodyTemplate``,
        ``confirmTemplate``, ``approvalThresholdParam``,
        ``approvalThresholdValue``.

        The other eight (``name``, ``description``, ``method``,
        ``urlTemplate``, ``headers``, ``parameters``, ``timeoutSeconds``,
        ``enabled``) are two-way: omit to keep, send to replace. **They
        cannot be cleared**, and sending ``None`` for one of them is not an
        erasure.

        So do not serialise your unset optionals as ``None``. A client that
        sends ``{"description": "...", "signingSecret": null}`` for a
        one-field edit **wipes the signing secret**, and may then be refused
        with a 422 from the coherence check — which runs against the *merged*
        row, so a patch that never mentions the conflicting field can still
        be rejected by it.

        An unknown or soft-deleted id is a 404.
        """
        return self._patch_obj(f"/v1/{encode_path('ai', 'tools', tool_id)}", dict(fields))

    def delete_tool(self, tool_id: str) -> JsonDict:
        """Soft-delete a tool. Returns ``{"deleted": true}`` with a **200**.

        Not a 204, and not an empty body — ``macros.delete`` is the only real
        204 on this surface.

        ``deleted`` is a literal ``True`` with nothing to branch on, and
        **this route does not 404 on an unknown id**: the update matches no
        row and the answer is the same. So ``deleted: True`` means "the call
        succeeded", never "a row existed". It also clears ``enabled``, so a
        deleted tool cannot be resurrected by a later patch.
        """
        return self._delete_obj(f"/v1/{encode_path('ai', 'tools', tool_id)}")

    # ---- house tone ------------------------------------------------------

    def tone(self) -> List[JsonDict]:
        """The workspace's tone rules. A **bare list**, not an envelope.

        Each rule is ``{"id", "category", "rule", "enabled", "position"}``.
        ``category`` is one of :data:`TONE_CATEGORIES`; ``position`` is
        per-category and comes from the order :meth:`set_tone` sent.

        Ordered by category then position. An empty list is the ordinary
        answer for a workspace that has configured nothing — there is no
        default house style.

        A paginator wrapped around this would read ``nextCursor`` off a list
        and get ``None`` forever: at most 40 rules exist (8 per category
        across 5), which is why the route has no cursor at all.
        """
        return as_list(self._get("/v1/ai/tone"))

    def set_tone(self, rules: Sequence[Mapping[str, Any]]) -> List[JsonDict]:
        """**Replace** every tone rule. Returns the stored set, as a list.

        Args:
            rules: up to 40 of ``{"category", "rule", "enabled"}``, where
                ``category`` is one of :data:`TONE_CATEGORIES`, ``rule`` is
                3–400 characters, and ``enabled`` defaults to ``True``. No
                more than **8 per category**, which is a separate 422 from
                the overall 40.

        **This is a whole-set replace, not a patch.** Every existing rule for
        the workspace is deleted first, in one transaction, so a call that
        omits a rule removes it. ``rules=[]`` wipes the set and is valid.

        **You cannot round-trip :meth:`tone` into this method.** The body is
        strict at both levels, and the read carries ``id`` and ``position``
        — sending either back is a 422. Strip them:

            keep = [
                {"category": r["category"], "rule": r["rule"], "enabled": r["enabled"]}
                for r in client.ai.tone()
            ]
            client.ai.set_tone(keep)

        The returned list is the set re-read from storage, not an echo of
        what you sent, so ``position`` on it is authoritative.
        """
        return as_list(self._put("/v1/ai/tone", {"rules": list(rules)}))

    def generate_tone(self, style_guide: str) -> JsonDict:
        """Draft tone rules from a prose style guide. Answers 201.

        Args:
            style_guide: 40–20,000 characters after trimming.

        Returns ``{"rules", "note"}``, where ``note`` is the model's remark
        about what it could not extract (nullable).

        **Nothing is saved.** These are a draft for a person to approve;
        persisting them is a separate :meth:`set_tone` call.

        And the draft is not guaranteed to be *acceptable* to that call:
        ``rules[]["category"]`` is typed as a plain string here, not the
        five-member enum, precisely because a model can invent a sixth
        category name. Filter against :data:`TONE_CATEGORIES` before passing
        it on, or :meth:`set_tone` answers 422.

        It proxies to the AI service with a 60-second timeout, so this is a
        slow call, and a 503 means that service is down rather than that your
        guide was bad.
        """
        return self._post_obj("/v1/ai/tone/generate", {"styleGuide": style_guide})

    def tone_preview(self) -> JsonDict:
        """The rendered tone block, as the system prompt receives it.

        Returns ``{"instruction": "..."}`` — **an object around one string**,
        so that the shape can grow.

        ``instruction`` is ``""`` for a workspace with no rules, and that is
        a normal successful answer: no house style is invented. The block is
        truncated at 2,000 characters.

        Served from a cache, with a silent fall-through to the database if
        the cache is unavailable — so this is cheap to call per preview.
        """
        return self._get_obj("/v1/ai/tone/preview")

    # ---- spend -----------------------------------------------------------

    def quota(self) -> JsonDict:
        """The AI spend meter for the current period.

        Returns ``{"spent", "platformSpend"-style fields, "budget",
        "remaining", "utilization", "warn", "periodKey", "plan",
        "capBasis", "projectedExhaustionAt"}``. Concretely: ``spent``,
        ``platformSpent``, ``byokSpent``, ``totalSpent``.

        **Read the right number or you will tell a customer the wrong
        thing.** ``spent`` equals ``platformSpent`` and is the **only**
        figure ``budget`` bounds. ``byokSpent`` is metered and never capped —
        it is the customer's own provider bill. ``totalSpent`` is both added
        together. Labelling ``spent`` as "your AI spend" is the specific
        mistake this shape exists to prevent: a BYOK-heavy workspace would
        read "$412 of $5".

        ``budget: None`` means **uncapped** — free-with-BYOK and enterprise
        plans — and is not an error; ``remaining`` and ``utilization`` are
        ``None`` with it.

        This is a live proxy to the AI service, not a local read, so it
        answers **503** when that service is down. Needs
        ``workspace:billing:read``.
        """
        return self._get_obj("/v1/ai/quota")


__all__ = ["AI_PROVIDERS", "TONE_CATEGORIES", "AI"]
