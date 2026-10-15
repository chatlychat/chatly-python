# Changelog

All notable changes to the `chatly` Python SDK.

This project follows [Semantic Versioning](https://semver.org/). Until
`1.0.0`, minor versions may contain breaking changes; they will always be
listed here.

## Unreleased

### Added

- **`chatly.verify_chatly_signature(surface, body, headers, secret, ...)`** —
  one verifier for every signed request Chatly sends: the eight surfaces in
  `chatly.CHATLY_SIGNATURE_SURFACES` (event webhooks, agent deliveries, AI
  tool calls, canvas steps, customer cards, both workflow headers, and the
  unified `x-chatly-signature-v2`). It returns a `ChatlySignatureResult`
  carrying `ok`, `surface`, and either `timestamp_ms` / `base` /
  `secret_index` or a stable `reason` (one of
  `chatly.CHATLY_SIGNATURE_FAILURES`) and a printable `message`, and it never
  raises. It takes a list of secrets for rotation, prefers the v2 header
  when `method` and `path` are supplied (`v2="prefer"|"require"|"ignore"`),
  refuses a duplicated signature header instead of trial-verifying it, and
  refuses the timestamp-less legacy workflow header unless
  `allow_unprotected_replay=True`. Also exported:
  `CHATLY_SIGNATURE_TOLERANCE_SECONDS` (300), `CHATLY_V2_SIGNATURE_HEADER`
  and `SurfaceSpec`. It is a port of the Node SDK's `verifyChatlySignature`
  and runs the same cross-SDK corpus (`tests/signature_vectors.json`).
  `verify_webhook_signature` is unchanged.

- **`client.bots.rotate_external_secret(bot_id, activate_at=)`** — the
  optional `activate_at` (sent as `{"activateAt": ...}`) defers the switch to
  a new external-agent signing secret by up to 168 hours, so the old secret
  keeps signing deliveries while you deploy the new one. A string passes
  through verbatim; a `datetime` must be timezone-aware and is sent as its UTC
  instant with a `Z` (a naive one raises `InvalidArgumentError` before any
  request). The response now carries `activatesAt` — `None` when the new
  secret is already signing. The no-argument call is unchanged, body `{}` and
  all, and is still a hard cut.

- **`client.visitors.start_conversation(contact_id)`** — the 163rd route, and
  the first that reaches out to a contact who has not written. `POST
/v1/visitors/{contactId}/start-conversation`, no body and no query
  parameters, answering `{"conversationId"}`. It opened to API keys on
  2026-10-14; before that it was documented and answered any `ck_` key with a 403.

  Three things an integrator needs, all in the method's docstring. It is
  **off by default per workspace**
  (`settings.proactiveOutreach.apiKeysMayStartConversations`), enabled only
  with a session-only `PATCH /v1/workspace/settings` and readable with
  `client.workspace.settings()` — so a `PermissionDeniedError` here is more
  likely the setting than the key's scopes. It is limited to **three per
  contact per hour**, counted per contact rather than per caller, surfacing as
  `RateLimitError`. That refusal sends no `Retry-After` header — the API's
  exception filter sets none, and the hook that synthesises one only folds
  `@nestjs/throttler`'s buckets — so the TTL arrives in the body at
  `details.retryAfterSeconds`. `retry_after` is still populated, because
  `errors.py` already falls back to that field; there is now a test pinning
  that fallback, and a control proving a real header still wins over it. And an **offline visitor gets no
  notification at all**: the greeting is persisted and rendered from history
  on their next page view.

  `GET /v1/visitors/live` and `GET /v1/visitors/{contactId}/pages` sit on the
  same controller, carry no `@AllowApiKey()`, and so deliberately have no
  method here.

### Changed

- **A paged method now refuses a body that is not a page.**
  `page_from_payload` used to fold a bare JSON array into one cursor-less
  page, and turn any other unrecognised body into an _empty_ page with the
  payload kept in `Page.raw`. Both readings answer a wrong shape with a
  plausible result: the caller is handed one page that looks complete, or an
  empty list, with a 200 and nothing raised. It raises `ResponseDecodeError`
  now. The tolerance survives only on `client.paginate`, the untyped escape
  hatch, where there is no manifest entry to consult and several reachable
  routes are pagination-exempt.

  This is a behaviour change for anyone who was relying on a typed walker
  silently accepting an unpaged body. Nothing on the current API does that —
  all ten paged routes send the envelope — so in practice it converts a
  wrong answer into an error.

### Added

- **The whole key-accessible surface now has typed methods: 162, up from 55.** Eleven new namespaces — `ai`, `bots`, `bot_routes`, `brands`,
  `canvas_steps`, `customer_cards`, `customer_card_endpoints`,
  `docs_sources`, `email_templates`, `knowledge_gaps`, `triggers` — and 104
  new methods across those and the existing twelve, plus the three below. Every route was verified
  against its handler before being implemented: the manifest has been wrong
  in both directions before, and the response shape each method expects was
  derived independently from each handler's `@ZodResponse` schema rather than
  copied from `surface.json`. All 162 agreed on this pass.
- `client.me()` (`GET /v1/me`), `webhooks.delete(endpoint_id)` and
  `workspace.mine()`, the three routes added to the manifest after the sweep
  above. `me()` is the one to call first: it answers the same thing as
  `whoami()` for a key but requires **no scope**, so a key with a wrong or
  narrow grant still gets a 200 and you can tell a bad credential from a
  missing permission. `webhooks.delete` closes an asymmetry — a key could
  register a delivery target and never remove one.
- Three new auto-paginators, bringing the total to thirteen:
  `bots.iter_list`, `bots.iter_deliveries` and `triggers.iter_list`. All
  three routes are built by the API's shared `buildPaginatedResponse`, so
  they carry `hasMore` beside the cursor — which makes six such routes, not
  the four the manifest's own prose claims.
- `billing.invoices` is cursor-paginated and deliberately has **no** `iter_`
  form: its envelope key is `data`, not `items`, so it is not a `Page`. It
  returns the raw dict and its docstring carries the loop, because reading
  it as unpaginated silently truncates any customer with more than 25
  invoices.
- `surface.lock.json` now records, per route, the **top-level response
  shape** this SDK's decoder expects: `array`, `page`, `object` or `empty`.
  The column is hand-written in `tests/test_surface_lock.py` from the API's
  handlers and deliberately **not** read from `packages/sdk-spec/surface.json`
  — a fixture derived from the manifest agrees with the manifest even when
  the manifest is wrong, which is how the sibling `paged` flag stayed wrong
  in both directions for months. `scripts/check-sdk-surface-parity.mjs`
  diffs eight independently written columns against the manifest.
- The suite now feeds every method a body of **its own** declared shape and
  asserts the value handed back really has that shape, which catches a
  method that wraps or unwraps an envelope even when the request it issued
  was perfect. It also asserts the distribution of the column (33 `array`,
  13 `page`, 115 `object`, 1 `empty`), because a column of 162 `object` rows
  would satisfy every other assertion and prove nothing.
- Every auto-paginator is fed a bare array where it expects a page and
  required to raise, with the set of walkers exercised asserted equal to the
  thirteen routes declared `page`.
- `tests/test_transport.py`'s bare-array table is now asserted **complete**
  against this package's own declared shapes, not merely disjoint from the
  paged ones. Without that half a route could fall out of the table and
  leave every other assertion satisfied, which is how the list it replaced
  went stale.

### Changed

- The hand-declared shape column moved from `tests/test_surface_lock.py` to
  `tests/expected_shapes.py`, and the invocation table from
  `tests/test_surface.py` to `tests/invocations.py`; the six
  `conversations` routes that are _about_ a thread rather than in it moved to
  `chatly/resources/conversation_edges.py`, a mixin
  `Conversations` inherits. All three splits are the contract's 650-line
  ceiling (§9) rather than a change of design — `client.conversations` still
  exposes every method and nothing was renamed.

### Fixed

- `tests/support.py`'s fallback response is a cursor envelope rather than
  `{}`, for the tests that assert on the _request_. The 0.1.0 note below
  claimed response shapes were already pinned per route; they were not —
  every route was answered with the same body — and that claim is true as of
  this entry.
- The documented count of auto-paginators was seven; there are ten.
  `contacts.iter_journey` and `conversations.iter_unattended` were missing
  from the README's list, and `GET /v1/kb/articles`,
  `GET /v1/webhooks/deliveries` and `GET /v1/cdp/events` send `hasMore`
  beside the cursor, which `pagination.py` claimed only `/v1/tickets` did.

## 0.1.0 — 2026-10-12

First release. Implements the cross-language Chatly backend-SDK contract
(`packages/sdk-spec/CONTRACT.md`) in full.

### Added

- `ChatlyClient` with twelve resource namespaces and all 55 methods in
  `packages/sdk-spec/surface.json`: `contacts`, `conversations`, `tickets`,
  `macros`, `kb`, `search`, `events`, `webhooks`, `reports`, `channels`,
  `billing`, `workspace`, plus `whoami()`.
- **Zero runtime dependencies.** HTTP is `urllib.request`, signing is
  `hmac`/`hashlib`, ids are `uuid` — all standard library.
- **Typed errors.** `ChatlyError` at the root; `AuthenticationError` (401),
  `PermissionDeniedError` (403), `NotFoundError` (404), `ConflictError`
  (409, with `.is_idempotency_conflict`), `BadRequestError`,
  `ValidationError` (400 `validation_failed` _and_ 422), `RateLimitError`
  (429, with `.retry_after`), `ServerError` (5xx), `TransportError` /
  `ChatlyTimeoutError` for failures that never reached a status, plus
  `InvalidArgumentError`, `PaginationError` and `ResponseDecodeError`.
  Each HTTP error carries `status`, `code`, `message`, `details`,
  `request_id` and the raw `body`.
- **Retries.** Connection errors, 429 and 5xx only; 3 attempts by default;
  exponential backoff with full jitter; `Retry-After` honoured and clamped.
  A retried write reuses the `Idempotency-Key` of the attempt that failed.
  `RetryPolicy` to tune it, `NO_RETRIES` to turn it off.
- **Idempotency.** A fresh UUID per write by default;
  `client.with_idempotency_key(key)` returns a derived client that pins one.
- **Pagination.** `Page` for a single page (`items`, `next_cursor`, `total`,
  `has_more`, `raw`) and an `iter_*` generator for each of the ten
  cursor-paginated routes. Lazy, stops on a null cursor, and raises
  `PaginationError` rather than looping if the server repeats one.
  Pagination-exempt collections — `macros.list`, `channels.list`,
  `billing.plans` and the rest — return a plain list and have no `iter_*`,
  because advertising a walker for a route with no cursor is a promise the
  SDK cannot keep.
- **`verify_webhook_signature(body, signature_header, secret, tolerance=300)`**
  — HMAC-SHA256 over `<t>.<raw body>`, constant-time, returns `False` for
  every malformed input and never raises.
- **`identity_hash(secret, external_id)`** — the backend half of widget
  identity verification.
- **`client.request(method, path, query=, body=)`** — the escape hatch to
  any of the ~85 key-accessible routes with no typed method, through the same
  auth, idempotency, retries and errors. Plus `client.paginate(path)`.
- An injectable `Transport`, so tests need no network, no key and no running
  API.
- Full type annotations and a `py.typed` marker. Passes `mypy --strict`.
- A `unittest` suite that runs with nothing installed, covering all nine
  items in CONTRACT.md §10 including both pinned vectors, plus a loopback
  HTTP server exercising the real `urllib` transport. Verified on CPython
  3.9 and 3.14.

### Notes

- `workspace.team_members(team_id)` reads one team's roster and
  `workspace.agent_skills()` returns the skill taxonomy. Neither is a
  workspace-wide team list or an agent roster; there is no key-accessible
  route for either, and the README says so rather than leaving it to be
  discovered from a 403.
- `search.query(kinds=...)` sends **repeated bare `kinds` parameters**, and
  a single kind is sent twice. `kinds[]=` is silently dropped by that route
  (200, unfiltered, no error) and one bare `kinds=kb` is a 400, because the
  schema is parsed straight off the query with no array coercion. Repeating
  the value is the only spelling that both parses and filters.
- `reports.sla(group_by=...)` sends snake_case `group_by`, which is what
  that handler reads; a camelCase `groupBy` is ignored and you get daily
  buckets.
- Response shapes are pinned per route by a test that feeds each method the
  shape its endpoint really returns — a bare array to the pagination-exempt
  collections, an envelope to the paged ones — and the paged set is asserted
  equal to the manifest's. A fake transport that answers every route with a
  page envelope would otherwise make the suite agree with a wrong manifest
  rather than with the server.
