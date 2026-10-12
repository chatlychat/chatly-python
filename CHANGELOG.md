# Changelog

All notable changes to the `chatly` Python SDK.

This project follows [Semantic Versioning](https://semver.org/). Until
`1.0.0`, minor versions may contain breaking changes; they will always be
listed here.

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
  `has_more`, `raw`) and an `iter_*` generator for each of the seven
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
