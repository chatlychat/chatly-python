# chatly

The official Python SDK for **Chatly** — a live-chat and customer-messaging
platform. Your visitors chat from a widget on your site (or email, WhatsApp,
SMS, Telegram and a dozen other channels); your team answers from an agent
inbox; an AI layer drafts and sometimes resolves. This package is how your
_backend_ talks to that platform: sync your users in as contacts, read and
reply to conversations, read tickets and reports, and verify the webhooks
Chatly sends you.

- **Zero dependencies.** Standard library only — `urllib`, `hmac`, `hashlib`.
  You should not have to inherit our dependency tree to send a message.
- **Python 3.9+**, fully type-annotated, ships a `py.typed` marker.
- **Server-side only.** See the warning below; this matters.

```bash
pip install chatly
```

## Quickstart

```python
import os
import chatly

client = chatly.ChatlyClient(api_key=os.environ["CHATLY_API_KEY"])

print(client.whoami())                      # which workspace, which scopes

contact = client.contacts.upsert(email="ada@example.com", name="Ada")
client.events.track(contact["id"], "trial_started", {"plan": "growth"})

for conversation in client.conversations.iter_list(status="open"):
    print(conversation["id"], conversation["lastMessagePreview"])
    client.conversations.send(conversation["id"], "Thanks — looking into it.")
```

> [!WARNING] > **Never ship your API key to a browser or a mobile app.** A `ck_…` key is a
> bearer credential for the _whole workspace_ — every contact, every
> conversation, every report. Anyone who reads it can act as your entire
> company. Keep it in server-side environment variables or a secret manager.
> The browser-side SDK is [`@chatlychat/sdk-js`](https://www.npmjs.com/package/@chatlychat/sdk-js),
> which uses a public channel id instead and is safe to embed.

Get a key in the Chatly dashboard under **Settings → API keys**, and scope it
to only what your integration needs. `client.whoami()` tells you what a key
can do:

```python
me = client.whoami()
# {'workspaceId': '...', 'scopes': ['contacts:read', 'contacts:write']}
if "conversations:write" not in me["scopes"]:
    raise SystemExit("this key cannot reply to conversations")
```

## Configuration

```python
client = chatly.ChatlyClient(
    api_key=os.environ["CHATLY_API_KEY"],
    api_url="https://api.chatlychat.com",   # the default; another environment, or a test server
    timeout=15.0,                           # seconds per attempt
    retry=chatly.RetryPolicy(max_attempts=5),
)
```

| Argument    | Default                      | Notes                                                                                 |
| ----------- | ---------------------------- | ------------------------------------------------------------------------------------- |
| `api_key`   | —                            | Required. An empty key raises at construction, not at the first call.                 |
| `api_url`   | `https://api.chatlychat.com` | Point it at another Chatly environment, or at a test server in your suite.            |
| `timeout`   | `15.0`                       | Seconds **per attempt**, not for the whole call.                                      |
| `retry`     | `RetryPolicy()`              | 3 attempts, jittered backoff, honours `Retry-After`. `chatly.NO_RETRIES` disables it. |
| `transport` | `UrllibTransport()`          | Inject your own for tests or an unusual network.                                      |
| `sleep`     | `time.sleep`                 | The function used to wait between retries.                                            |

The client holds no per-request state, so sharing one instance across threads
is fine.

## What you can call

55 methods, grouped by namespace. Each one maps to a single endpoint; the
response is decoded JSON (a `dict`, a `list`, or a `Page` — see
[Pagination](#pagination)).

### `client.whoami()`

| Method     | Endpoint                  | Returns                     |
| ---------- | ------------------------- | --------------------------- |
| `whoami()` | `GET /v1/api-keys/whoami` | `{"workspaceId", "scopes"}` |

### `client.contacts` — the people your agents talk to

| Method                                                                                      | Endpoint                              |
| ------------------------------------------------------------------------------------------- | ------------------------------------- |
| `list(cursor=, limit=, blocked=)`                                                           | `GET /v1/contacts`                    |
| `iter_list(...)`                                                                            | auto-paginates the above              |
| `get(contact_id)`                                                                           | `GET /v1/contacts/{id}`               |
| `upsert(external_id=, email=, phone=, name=, avatar_url=, locale=, timezone=, attributes=)` | `POST /v1/contacts`                   |
| `bulk_upsert(contacts)`                                                                     | `POST /v1/contacts/bulk`              |
| `merge(contact_id, merged_id)`                                                              | `POST /v1/contacts/{id}/merge`        |
| `add_tags(contact_id, tag)`                                                                 | `POST /v1/contacts/{id}/tags`         |
| `remove_tag(contact_id, tag)`                                                               | `DELETE /v1/contacts/{id}/tags/{tag}` |
| `unsubscribe(contact_id, unsubscribed=True, reason=)`                                       | `POST /v1/contacts/{id}/unsubscribe`  |
| `journey(contact_id, cursor=, limit=, days=)`                                               | `GET /v1/contacts/{id}/journey`       |

`merge` absorbs `merged_id` _into_ `contact_id` — the path is the survivor.

### `client.conversations` — threads and messages

| Method                                                                                                                                                                                                             | Endpoint                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| `list(cursor=, limit=, status=, channel=, tags=, priority=, assignee=, team=, segment=, brand=, sort=, unread=, mentioned=, unattended=, sla=, unattended_for=, from_=, to=, created_from=, created_to=, filter=)` | `GET /v1/conversations`                                      |
| `iter_list(...)`                                                                                                                                                                                                   | auto-paginates the above                                     |
| `get(conversation_id)`                                                                                                                                                                                             | `GET /v1/conversations/{id}`                                 |
| `messages(conversation_id, cursor=, limit=)`                                                                                                                                                                       | `GET /v1/conversations/{id}/messages`                        |
| `iter_messages(conversation_id, ...)`                                                                                                                                                                              | auto-paginates the above                                     |
| `send(conversation_id, body, kind=, attachments=, metadata=, blocks=, body_html=, canvas=, client_ref=, reply_to_message_id=)`                                                                                     | `POST /v1/conversations/{id}/messages`                       |
| `unattended(cursor=, limit=, assignee=, team=, channel=, older_than_minutes=)`                                                                                                                                     | `GET /v1/conversations/unattended`                           |
| `agent_handling(conversation_id)`                                                                                                                                                                                  | `GET /v1/conversations/{id}/agent-handling`                  |
| `set_agent_handling(conversation_id, state, reason=)`                                                                                                                                                              | `PUT /v1/conversations/{id}/agent-handling`                  |
| `generated_replies(conversation_id)`                                                                                                                                                                               | `GET /v1/conversations/{id}/generated-replies`               |
| `generate_reply(conversation_id, body, based_on_message_id=, proposed_by_label=)`                                                                                                                                  | `POST /v1/conversations/{id}/generated-replies`              |
| `scheduled_messages(conversation_id)`                                                                                                                                                                              | `GET /v1/conversations/{id}/scheduled-messages`              |
| `schedule_message(conversation_id, body, send_at)`                                                                                                                                                                 | `POST /v1/conversations/{id}/scheduled-messages`             |
| `cancel_scheduled(scheduled_id)`                                                                                                                                                                                   | `DELETE /v1/conversations/scheduled-messages/{scheduled_id}` |

`from_` is sent as `from`; `from` is a Python keyword. `set_agent_handling`
requires a key linked to a machine user — see its docstring.

### `client.tickets`

| Method                                                                                                 | Endpoint                                             |
| ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| `list(cursor=, limit=, sort=, fields=, filter=)`                                                       | `GET /v1/tickets`                                    |
| `iter_list(...)`                                                                                       | auto-paginates the above                             |
| `comments(ticket_id)`                                                                                  | `GET /v1/tickets/{id}/comments`                      |
| `for_conversation(conversation_id)`                                                                    | `GET /v1/tickets/for-conversation/{conversation_id}` |
| `queues()`                                                                                             | `GET /v1/tickets/queues`                             |
| `merge(ticket_id, loser_id)`                                                                           | `POST /v1/tickets/{id}/merge`                        |
| `split(ticket_id, title, description=, priority=, type=, assignee_user_id=, tags=, conversation_ids=)` | `POST /v1/tickets/{id}/split`                        |
| `bulk(ids, action, payload=)`                                                                          | `POST /v1/tickets/bulk`                              |

There is no `create` and no `add_comment`: those endpoints record _which
person_ acted, so an API key cannot call them. Tickets are normally created
by the platform from an inbound email or conversation.

### `client.macros` — saved replies

| Method                                                                            | Endpoint                                        |
| --------------------------------------------------------------------------------- | ----------------------------------------------- |
| `list(scope=, team=, query=, language=)`                                          | `GET /v1/macros` — returns a **list**           |
| `create(name=, scope=, body=, actions=, short_code=, team_id=, language=, tags=)` | `POST /v1/macros`                               |
| `update(macro_id, **fields)`                                                      | `PATCH /v1/macros/{id}`                         |
| `delete(macro_id)`                                                                | `DELETE /v1/macros/{id}` — returns `None` (204) |

`list` is the one collection in this SDK that returns a plain list rather
than a `Page`, and there is no `iter_list` for it: the route is
pagination-exempt — no `cursor`, no `limit` — and answers with a bare array
the server caps at 200 rows, ordered by usage rank. Narrow it with `query`
or `scope`; there is no cursor to walk.

`update` takes **wire** field names (`shortCode`, `teamId`) so that an
explicit `None` can reach the server and clear a field, which omitting it
does not.

### `client.kb` — help-centre content

| Method                                               | Endpoint                                           |
| ---------------------------------------------------- | -------------------------------------------------- |
| `articles(cursor=, limit=, sort=, fields=, filter=)` | `GET /v1/kb/articles`                              |
| `iter_articles(...)`                                 | auto-paginates the above                           |
| `article(slug)`                                      | `GET /v1/kb/articles/{slug}` — by **slug**, not id |
| `collections()`                                      | `GET /v1/kb/collections`                           |

`articles` has no `status` or `q` parameter; filter instead —
`filter="status:eq:published"`. To search article _text_, use
`client.search.kb(...)`.

### `client.search`

| Method                                                                                    | Endpoint                                |
| ----------------------------------------------------------------------------------------- | --------------------------------------- |
| `query(q, kinds=, from_=, to=, channel_id=, assignee_user_id=, status=, limit=, cursor=)` | `GET /v1/search`                        |
| `kb(q, ...)`                                                                              | the same route narrowed to `kinds="kb"` |
| `iter_query(q, ...)`                                                                      | auto-paginates the hits                 |

`kinds` is one or more of `contact`, `conversation`, `message`, `ticket`,
`kb`. The response is this route's own envelope: `{"items", "nextCursor",
"facets", "tier"}`.

### `client.events` — the CDP event stream

| Method                                                        | Endpoint                 |
| ------------------------------------------------------------- | ------------------------ |
| `track(contact_id, name, properties=)`                        | `POST /v1/cdp/events`    |
| `list(contact_id=, cursor=, limit=, sort=, fields=, filter=)` | `GET /v1/cdp/events`     |
| `iter_list(...)`                                              | auto-paginates the above |

One event per `track` call — the endpoint takes no batch form.

### `client.webhooks` — delivery history

| Method                                                                        | Endpoint                                                      |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `deliveries(endpoint_id=, status=, cursor=, limit=, sort=, fields=, filter=)` | `GET /v1/webhooks/deliveries`                                 |
| `iter_deliveries(...)`                                                        | auto-paginates the above                                      |
| `delivery(delivery_id)`                                                       | `GET /v1/webhooks/deliveries/{id}` — adds `payload` and `url` |
| `redeliver(delivery_id)`                                                      | `POST /v1/webhooks/deliveries/{id}/redeliver`                 |

`redeliver` _queues_ a new attempt; the outcome appears as a new row in
`deliveries`, not in its own response.

### `client.reports`

| Method                               | Endpoint                               | Window default |
| ------------------------------------ | -------------------------------------- | -------------- |
| `overview(days=)`                    | `GET /v1/reports/overview`             | 7              |
| `agents(days=)`                      | `GET /v1/reports/agents`               | 7              |
| `conversations_by_day(days=)`        | `GET /v1/reports/conversations-by-day` | **14**         |
| `sla(days=, from_=, to=, group_by=)` | `GET /v1/reports/sla`                  | 30             |

The four windows differ, so pass `days` explicitly if two of these numbers
are going to sit next to each other.

### `client.channels`

| Method            | Endpoint                |
| ----------------- | ----------------------- |
| `list()`          | `GET /v1/channels`      |
| `get(channel_id)` | `GET /v1/channels/{id}` |

Credential-shaped keys inside `config` come back as the literal string
`"__redacted__"`. On a `web` channel, `originsRestricted=False` means **any
origin is admitted** — not that restriction is unnecessary.

### `client.billing`

| Method                           | Endpoint                                                                           |
| -------------------------------- | ---------------------------------------------------------------------------------- |
| `plans()`                        | `GET /v1/billing/plans` — `[]` when the deployment has no Stripe prices configured |
| `usage(event_type, from_=, to=)` | `GET /v1/billing/usage`                                                            |

`event_type` is required: `conversation.opened`, `message.sent.agent`,
`message.sent.bot` or `ai.tokens`.

### `client.workspace`

| Method                  | Endpoint                     |
| ----------------------- | ---------------------------- |
| `settings()`            | `GET /v1/workspace/settings` |
| `labels(usage=)`        | `GET /v1/labels`             |
| `inboxes()`             | `GET /v1/inboxes`            |
| `team_members(team_id)` | `GET /v1/teams/{id}/members` |
| `agent_skills()`        | `GET /v1/agents/skills`      |

Two of these are narrower than their names suggest:

- `team_members(team_id)` reads **one team's** roster, so you need a team id
  from somewhere else: a conversation's `teamId`, an inbox's
  `settings["routingTeamId"]`, or a workflow.
- `agent_skills()` returns `{"skills": [...]}` — the workspace's skill
  taxonomy, which skill-based routing matches against. It is a list of
  labels, not of agents. For the people, use `team_members(...)` or take
  `userId` from `reports.agents()`.

On `inboxes()`, note the id field is `channelId`, not `id`.

## Error handling

Every failure raises a typed exception, never a bare string. Branch on the
class; never on a substring of a message.

```python
import chatly

try:
    client.conversations.send(conversation_id, "Hello")
except chatly.AuthenticationError:
    ...   # 401 — the key is wrong, revoked or missing
except chatly.PermissionDeniedError:
    ...   # 403 — the key is valid but lacks the scope for this route
except chatly.NotFoundError:
    ...   # 404 — no such conversation in this workspace
except chatly.ValidationError as err:
    ...   # the request was understood and rejected
    print(err.details.get("issues"))
except chatly.RateLimitError as err:
    ...   # 429 — err.retry_after is seconds, or None
except chatly.ServerError:
    ...   # 5xx, already retried
except chatly.TransportError:
    ...   # DNS, connect, TLS, timeout — never got an HTTP status
```

Every HTTP error carries:

| Attribute    | From                                                                                                                                                |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`     | the HTTP status                                                                                                                                     |
| `code`       | the API's `code` field                                                                                                                              |
| `message`    | the API's `message` field                                                                                                                           |
| `details`    | the API's `details` object, `{}` if absent                                                                                                          |
| `request_id` | the `x-request-id` response header — the API mints one per request and sends it on every response, errors included, so quote it in a support ticket |
| `body`       | the raw response text, verbatim                                                                                                                     |

The full hierarchy, all rooted at `ChatlyError`:

```
ChatlyError
├── APIError                  (any non-2xx)
│   ├── AuthenticationError   401
│   ├── PermissionDeniedError 403
│   ├── NotFoundError         404
│   ├── ConflictError         409   .is_idempotency_conflict
│   ├── BadRequestError       400   (not a validation failure)
│   ├── ValidationError       400 `validation_failed`, or 422
│   ├── RateLimitError        429   .retry_after
│   └── ServerError           5xx
├── TransportError            no HTTP status at all
│   └── ChatlyTimeoutError
├── InvalidArgumentError      bad argument; also a ValueError
├── PaginationError           the server's cursors cannot be walked
└── ResponseDecodeError       a 2xx body that was not the JSON we expect
```

Note `ValidationError` covers **both** `422` and `400` with code
`validation_failed`. In practice this platform sends the 400; you should not
have to know which layer rejected you.

### Retries

Connection failures, `429` and `5xx` are retried: 3 attempts by default,
exponential backoff with full jitter, and a server's `Retry-After` is
honoured (clamped, so a misconfigured proxy cannot park your process for a
day). A `400`, `404`, `409` or `422` is **never** retried — it will fail
identically every time.

```python
client = chatly.ChatlyClient(
    api_key=key,
    retry=chatly.RetryPolicy(max_attempts=5, initial_backoff=1.0, max_backoff=20.0),
)
no_retries = chatly.ChatlyClient(api_key=key, retry=chatly.NO_RETRIES)
```

### Idempotency

Every write sends an `Idempotency-Key`, minted fresh per call, so a retry
inside the SDK can never double-write. To retry _the same logical operation_
across process restarts — a job that might be redelivered, a webhook handler
that might be called twice — pin a key:

```python
key = str(uuid.uuid4())          # store this alongside your job
client.with_idempotency_key(key).conversations.send(conversation_id, "Hello")
```

Same key + same body replays the first response. Same key + a _different_
body is a 409:

```python
except chatly.ConflictError as err:
    if err.is_idempotency_conflict:
        ...   # this retry is not the operation the server recorded; do not loop
```

`with_idempotency_key()` returns a **new** client; the original keeps minting
one key per call.

## Pagination

List endpoints are cursor-paginated. Both forms are available everywhere.

**One page**, as returned:

```python
page = client.contacts.list(limit=50)
for contact in page.items:
    print(contact["email"])
print(page.next_cursor)     # None on the last page
print(page.total)           # None unless the endpoint reports it
print(page.raw)             # the whole decoded body, nothing lost
```

**Every page**, as a generator — `iter_` plus the method name:

```python
for contact in client.contacts.iter_list():
    print(contact["email"])
```

It is lazy: no request is made until you start iterating, and it stops on a
null cursor. If the server ever repeats a cursor it raises `PaginationError`
rather than looping forever — or quietly truncating, which would be worse,
because you would believe you had seen every row.

The auto-paginators, one per cursor-paginated route — ten of them:
`contacts.iter_list`, `contacts.iter_journey`, `conversations.iter_list`,
`conversations.iter_messages`, `conversations.iter_unattended`,
`tickets.iter_list`, `kb.iter_articles`, `events.iter_list`,
`webhooks.iter_deliveries` and `search.iter_query`.

A paged method only accepts a page. If one of these routes ever answers with
something that is not an `{"items": ..., "nextCursor": ...}` envelope — a
bare array, say — you get a `ResponseDecodeError` and not one page that looks
complete. A list you believe is whole is the worse failure, and two other
Chatly SDKs shipped exactly that against `GET /v1/macros`.

Methods without one return a plain list, because their route has no cursor:
`macros.list`, `channels.list`, `billing.plans`, `kb.collections`,
`reports.agents`, `reports.conversations_by_day`, `workspace.labels`,
`workspace.inboxes`, `workspace.team_members`, `tickets.queues`,
`tickets.comments`, `tickets.for_conversation`,
`conversations.generated_replies` and `conversations.scheduled_messages`.

> Never sort or page on `id`. Ids here are a mix of UUID v4 and v7, so id
> order is **not** time order. The cursor is the only correct sequence, and
> it is opaque — do not parse it or construct one.

## Verifying webhooks

Chatly signs every webhook it sends you. Verify before you trust it.

```python
import chatly
from flask import Flask, request

app = Flask(__name__)
SECRET = os.environ["CHATLY_WEBHOOK_SECRET"]       # the endpoint's whsec_… secret

@app.post("/hooks/chatly")
def hook():
    ok = chatly.verify_webhook_signature(
        request.get_data(),                         # the RAW bytes — see below
        request.headers.get("x-livechat-signature", ""),
        SECRET,
    )
    if not ok:
        return "", 401
    event = request.get_json()
    ...
    return "", 204
```

```python
chatly.verify_webhook_signature(body, signature_header, secret, tolerance=300, *, now=None)
```

- The header is `x-livechat-signature: t=<unix seconds>,v1=<hex>`.
- `v1` is HMAC-SHA256 over the bytes `<t>.<raw body>`. The timestamp is bound
  **into** the digest; that is what makes the replay window enforceable.
- **Pass the raw bytes you received.** Re-serialising parsed JSON reorders
  keys and changes whitespace, and the digest will not match. In Flask that
  is `request.get_data()`, in Django `request.body`, in FastAPI
  `await request.body()`.
- `tolerance` is seconds either side of `t`, default 300. Pass
  `float("inf")` only when re-verifying an archived delivery.
- It returns `True` or `False` and **never raises** — not for a malformed
  header, a missing field, a non-numeric timestamp, a wrong type, or
  anything else. A verifier that raises is an accepted webhook in a handler
  that forgot to catch.

Comparison is constant-time.

## Identity verification (`identity_hash`)

If your workspace turns on widget identity verification, the widget must
prove the user id it claims was issued by your backend rather than typed
into a browser console. Your server computes the digest; the secret never
leaves it.

```python
user_hash = chatly.identity_hash(os.environ["CHATLY_IDV_SECRET"], str(user.id))
```

Then render it into the page for the browser widget:

```html
<script>
  Chatly('identify', {
    externalId: '{{ user.id }}',
    userHash: '{{ user_hash }}',
    email: '{{ user.email }}',
  });
</script>
```

`identity_hash(secret, external_id)` is the lowercase hex HMAC-SHA256 of
`external_id` under the workspace's identity-verification secret. It raises
`InvalidArgumentError` if either argument is empty — an empty secret is a
valid HMAC key, which is the problem, and the likeliest cause is an
environment variable that never got set.

## The escape hatch

55 endpoints have a typed method here. 140 of the API's routes accept an API
key, so about 85 do not — new routes, niche ones, and the ones whose shape
did not justify a method. `client.request(...)` reaches any of them through
the same auth, idempotency, retry and typed errors:

```python
actions = client.request("GET", "/v1/macros/actions")
client.request("PUT", f"/v1/api-keys/{key_id}/machine-user", body={"userId": uid})
client.request("DELETE", f"/v1/some/resource/{rid}")

page = client.paginate("/v1/custom-objects", query={"limit": 100})
```

`paginate` is the one place a bare array is folded into a single cursor-less
page, because an untyped path cannot know whether the route is paged and a
good number of the untyped ones are pagination-exempt. The typed methods are
strict instead.

- `method` — `POST`/`PUT`/`PATCH`/`DELETE` get an `Idempotency-Key`
  automatically, and `POST`/`PUT`/`PATCH` with no body send `{}`.
- `path` — absolute, starting with `/`, and **already encoded**. If a segment
  comes from user data, encode it: `from chatly._transport import encode_path`.
- `query` — `None` values are dropped; a list becomes a repeated key.
- Returns decoded JSON, or `None` for a 204.

## Testing your own code

Inject a transport and the SDK makes no network calls at all:

```python
import json
from chatly import ChatlyClient, HTTPResponse, Transport

class StubTransport(Transport):
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return HTTPResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=json.dumps(self.payload).encode(),
        )

stub = StubTransport({"items": [{"id": "c1"}], "nextCursor": None})
client = ChatlyClient("ck_test", transport=stub)

assert [c["id"] for c in client.contacts.iter_list()] == ["c1"]
assert stub.requests[0].headers["authorization"] == "Bearer ck_test"
```

## Running this package's tests

The suite uses only `unittest` from the standard library — no test runner to
install, no network, no API key, no running API:

```bash
cd packages/sdk-python
python3 -m unittest discover -s tests -v
```

Type checking, if you have mypy:

```bash
python3 -m mypy
```

Running the suite also regenerates `surface.lock.json`, which records the
`METHOD /path` every one of the 55 methods actually issued. It is produced by
executing the client against an in-process fake transport, so it is evidence
rather than a source scan — a doc comment cannot emit a request, and a path
assembled by a helper is captured the same as a literal one. The
cross-language parity gate reads that file, and the test fails if it does not
match the shared manifest.

## License

MIT — see [LICENSE](./LICENSE).

---

## About this repository

This is a **mirror**. `chatly-python` is built from a private monorepo where the rest
of the platform, its migrations and its contract checks live, so a pull request here
cannot be merged directly — but a patch is still the fastest way to get something
fixed and we will port it with attribution.

What you can do here: read the source, run the tests, open an issue, or open a PR
and we will treat the diff as the proposal.

Issues: https://github.com/chatlychat/chatly-python/issues · Docs: https://chatlychat.com/docs
