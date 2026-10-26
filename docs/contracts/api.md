# API contract

## Implemented in Phase 1

These health endpoints remain unchanged. Machine-readable specification:
[health.openapi.yaml](health.openapi.yaml). `/docs` and `/openapi.json` are FastAPI tooling.

| Endpoint | Success | Failure |
| --- | --- | --- |
| GET /api/v1/health/live | 200: `{"status":"alive"}` | No external dependency check |
| GET /api/v1/health/ready | 200: `{"status":"ready","dependencies":{"postgresql":"up"}}` | 503: `{"status":"not_ready","dependencies":{"postgresql":"down"}}` |

Both send `Cache-Control: no-store`. Readiness checks connectivity and a trivial SQL query,
not migrations/schema, Redis, or worker progress. No authentication is required.

## Implemented authentication, events, and reservations

The five `/auth/*` routes below are implemented in Phase 2. Phase 3 adds public event list/detail
and organizer create/list/detail/edit/capacity/publish/close. Phase 4 adds holds, confirmation,
cancellation, owner-only detail/history, and public advisory availability. The organizer
dashboard remains planned and unregistered. The full implemented specification,
including cookie/CSRF security schemes, is [api.openapi.yaml](api.openapi.yaml).

Base path `/api/v1`. JSON requests/responses, UUID resource IDs, RFC 3339 UTC timestamps.
Unknown/extra mutation fields will be rejected. No client-supplied role, reservation state,
allocated counter, user ID, or organizer ownership is trusted.

All mutations use the [CSRF contract](../security.md), including anonymous registration/login.
The CSRF bootstrap supports both anonymous and authenticated sessions. Session cookie values
are never returned in response bodies. `GET /auth/me` requires authentication.

| Method/path | Body or query | Result | Authorization |
| --- | --- | --- | --- |
| GET /auth/csrf | none | 200: csrf_token; creates anonymous cookie if needed | Public/same-origin bootstrap |
| POST /auth/register | email, password | 201: user identity + fresh anonymous csrf_token; does not log in | Anonymous pre-session + CSRF |
| POST /auth/login | email, password | 200: user identity + fresh csrf_token; sets new authenticated cookie | Anonymous pre-session + CSRF |
| POST /auth/logout | empty object | 204, clears cookie | Authenticated + CSRF |
| GET /auth/me | none | 200: id, email, role | Authenticated |
| GET /events | limit, cursor | 200: published event summaries + next_cursor | Public |
| GET /events/{event_id} | none | 200: published event detail | Public |
| GET /events/{event_id}/availability | none | 200: event_id, capacity, available_seats, as_of | Public; advisory snapshot |
| POST /organizer/events | title, description, location, starts_at, ends_at, booking_closes_at, capacity | 201: draft event | Organizer |
| PATCH /organizer/events/{event_id} | permitted metadata subset | 200: event; published deadlines/start immutable | Owning organizer |
| POST /organizer/events/{event_id}/publish | empty object | 200: published event | Owning organizer |
| POST /organizer/events/{event_id}/close | empty object | 200: closed event | Owning organizer |
| PATCH /organizer/events/{event_id}/capacity | capacity | 200: event | Owning organizer; event lock |
| GET /organizer/events | limit, cursor | 200: own event summaries + next_cursor | Organizer |
| GET /organizer/events/{event_id} | none | 200: own event detail, including draft/closed | Owning organizer; Phase 3 addition |
| GET /organizer/events/{event_id}/dashboard | limit, cursor | 200: counts + paginated reservation rows | Owning organizer |
| POST /events/{event_id}/holds | empty object | 201: reservation | Authenticated + idempotency key |
| POST /reservations/{reservation_id}/confirm | empty object | 200: reservation | Owner + idempotency key |
| POST /reservations/{reservation_id}/cancel | empty object | 200: reservation | Owner + idempotency key |
| GET /reservations/{reservation_id} | none | 200: reservation | Owner |
| GET /me/reservations | limit, cursor | 200: reservation rows + next_cursor | Authenticated |

Pagination: default 20, maximum 100, opaque cursor with stable ordering and ID tie-breaker.
Phase 3 pages use `items` and `next_cursor` (null on the last page).
Event summaries contain id/title/location/starts_at/booking_closes_at/status/capacity;
details additionally contain description/ends_at/organizer_id. Organizer responses may include
allocated_seats; Phase 3 includes that field only on organizer responses. Public
availability is computed in one consistent query from valid holds and
confirmed rows. Availability is no guarantee that a later hold succeeds and is not cached.

A reservation response contains id, event_id, effective status, created_at, hold_expires_at,
confirmed_at, cancelled_at, expired_at, and server_time. Overdue stored HELD projects as
EXPIRED without a read-side write; expired_at remains null until cleanup persists the transition.
The dashboard separates valid holds, overdue holds awaiting cleanup, confirmed, cancelled,
expired, and stored allocated_seats to avoid presenting incompatible counts as equal.

## Validation and errors

Implemented auth errors and planned mutation errors use `{"error":{"code":"...","message":"..."}}`.
Validation uses 422 `detail` with type/loc/msg; submitted input and ctx are omitted to prevent
credential disclosure. Health responses use the schema above.
Use 401 for missing/invalid authentication, 403 for role/CSRF failure, and 404 for unavailable
resources (including another user's private resource). Reject unsupported media types with 415.

| HTTP | Business code | Meaning |
| --- | --- | --- |
| 409 | EVENT_FULL | No seat can be allocated |
| 409 | BOOKING_CLOSED | Event status/deadline disallows a new hold |
| 409 | ACTIVE_RESERVATION_EXISTS | User already holds or confirmed a seat |
| 409 | HOLD_EXPIRED | Confirmation deadline reached |
| 409 | INVALID_RESERVATION_STATE | Terminal row cannot confirm |
| 409 | CANCELLATION_CLOSED | Event has started |
| 409 | CAPACITY_BELOW_ALLOCATED | Requested capacity violates current allocations |
| 409 | INVALID_EVENT_STATE | Publication/closing/editing is not allowed in the current state |
| 409 | EVENT_SCHEDULE_IMMUTABLE | A published event's start/deadline was supplied for editing |
| 409 | EVENT_NOT_PUBLISHABLE | Publication requires future start and booking deadline |
| 422 | INVALID_EVENT_SCHEDULE | Combined partial update violates schedule relationships |
| 422 | INVALID_CURSOR | Cursor is malformed or belongs to another listing scope |
| 409 | IDEMPOTENCY_KEY_REUSED | Same key with a different fingerprint |
| 403 | CSRF_FAILED | Missing/invalid token, pre-session, or trusted origin |
| 429 | RATE_LIMITED | Quota exceeded; include Retry-After |
| 503 | TEMPORARILY_UNAVAILABLE | Database/lock timeout or required limiter unavailable; retry same key |

## Idempotency and transport

Hold/confirm/cancel require `Idempotency-Key`: 1-128 visible ASCII characters without spaces.
Scope to user, not just route. Hash method + canonical path + canonical validated JSON.
Replay returns the stored status/body with `Idempotency-Replayed: true`; a new execution
returns `Idempotency-Replayed: false`. Business conflicts are stored; transient infrastructure,
authentication, CSRF, validation, and rate-limit failures are not completed outcomes.

Clients retain a key across network retries and fetch the current resource after replay.
A new intentional attempt, including retrying after a stored EVENT_FULL, uses a new key.
Authenticated/idempotent responses use no-store. Auth/CSRF validation still precedes replay.

State/locking rules are normative in [concurrency.md](../concurrency.md). Event DTOs/OpenAPI
are implemented in Phase 3; reservation/availability DTOs/OpenAPI in Phase 4. Dashboard
DTOs and routes remain future work. Authentication is implemented as described below.

## Phase 3 event rules and clarified contract details

The earlier contract listed organizer collection retrieval but no private single-event detail
route. Phase 3 adds `GET /organizer/events/{event_id}` so an owner can read a draft without
making public detail conditional on cookies or implementing the reservation dashboard early.
Public detail always uses the same PUBLISHED-only visibility rule, even for a logged-in owner.

| Operation | Allowed state | Rules |
| --- | --- | --- |
| Create | New row | Server sets DRAFT, authenticated organizer owner, allocated_seats=0 |
| Metadata PATCH | DRAFT | title/description/location/starts_at/ends_at/booking_closes_at |
| Metadata PATCH | PUBLISHED | title/description/location/ends_at only; supplying start/deadline, even unchanged, is 409 |
| Capacity PATCH | DRAFT or PUBLISHED | Separate endpoint; integer >=1 and >= stored allocated_seats |
| Publish | DRAFT only | Change to PUBLISHED; start and booking deadline strictly after post-lock PostgreSQL clock |
| Close | PUBLISHED only | Change to CLOSED; no allocations or reservation rows changed |
| Edit/publish/close | CLOSED | Reject; no reopening, hard deletion, or event cancellation |

Repeated publish/close is an invalid transition (409), not an idempotent replay. Event commands
do not implement reservation idempotency and do not require an Idempotency-Key.

Creation requires title, location, all three timestamps, and capacity. Description defaults
to an empty string. Title/location are trimmed and nonempty, at most 200/300 characters;
description is at most 10,000 characters and can be cleared with an empty string.
Capacity must be a JSON integer from 1 to 2,147,483,647 (PostgreSQL INTEGER range); booleans,
numeric strings, and fractional values are rejected. Unknown fields are rejected, including
owner, status, IDs, and the allocation counter. Capacity is not accepted by metadata PATCH.
PATCH requires at least one field and rejects explicit nulls. Publish/close require `{}`.

Timestamps must be RFC 3339 strings with an explicit timezone and are normalized to UTC.
Epoch numbers/strings and naive dates are rejected. The merged schedule always satisfies
`booking_closes_at <= starts_at < ends_at`. Drafts may store past but structurally valid
schedules, enabling an organizer to repair a stale draft; publication rechecks future dates
using the database clock. Public discovery filters by PUBLISHED status, not booking eligibility:
full events and events whose booking deadline/start has passed remain visible until closed.
No automatic closing or promise of available seats is implied.

Public and organizer lists order by `(starts_at, id)` ascending and use a bounded base64url
JSON keyset cursor: version, listing scope, last start time, and ID. Default limit=20, max=100;
cursor max length=512. Organizer cursors are scoped to that user. Cursors are navigation data,
not secrets or access tokens; changing a cursor never bypasses the SQL visibility/owner filter.
Separate pages are not a frozen database snapshot: draft schedule edits or publication changes
between requests can change membership/order. A refresh restarts the listing.

Every existing-event mutation locks its owned event with `SELECT ... FOR UPDATE`, then
rechecks session expiry/revocation, current active user/role, ownership, and state. All successful
writes commit before responding. Read endpoints reuse the current-user/organizer dependencies.
All event responses use no-store, including public responses. Phase 6 adds server-side public
detail caching as described below; this does not enable browser caching.
Validation errors omit submitted values. Event 422 responses can be sanitized `detail` errors
or the controlled INVALID_EVENT_SCHEDULE/INVALID_CURSOR envelope; OpenAPI describes both.

**Phase 4 integration:** capacity changes clean due HELD rows under the same event lock
before comparing against allocated_seats. Useful cleanup commits even if a capacity reduction
is refused. Reservation commands store business conflicts and useful cleanup atomically.
Closing leaves existing holds/confirmed rows intact. No independent cleanup commit is used.

## Authentication details

Registration: password length 15-128; response contains `user: {id, email, role}` and a fresh
anonymous csrf_token. Email normalization and session/security policy are in
[security](../security.md).
Login: password length 1-128; successful response has the same shape with a fresh authenticated
csrf_token and cookie. Register/login reject extra fields, including role, IDs, and active status.
Logout requires a JSON empty object, Origin (or trusted Referer fallback), cookie, and token;
success is an empty 204 response clearing the cookie. Current user returns only id/email/role.
CSRF bootstrap returns only csrf_token, with a cookie when a new pre-session is created.

Auth errors: 401 AUTHENTICATION_REQUIRED or INVALID_CREDENTIALS; 403 CSRF_FAILED/FORBIDDEN;
409 REGISTRATION_UNAVAILABLE; 415 UNSUPPORTED_MEDIA_TYPE; 503 TEMPORARILY_UNAVAILABLE.
There is no public organizer-provisioning endpoint. Roles can be exercised through reusable
dependencies and local promotion; there is no public role-selection route.

## Phase 4 implementation details

Hold/confirm/cancel accept only `{}`. The key header must occur exactly once. Missing/invalid
keys use sanitized 422 validation; malformed bodies never consume a key. Validated UUID paths
are canonicalized before fingerprinting POST, path, and the validated body. Keys are user-wide.
Different valid command paths with the same key return IDEMPOTENCY_KEY_REUSED.

A hold for an existing event outside PUBLISHED/open-deadline state returns BOOKING_CLOSED;
a missing event returns 404. A cancelled confirmation returns INVALID_RESERVATION_STATE;
an expired confirmation returns HOLD_EXPIRED and persists any due expiration. Repeat cancel
of CANCELLED/EXPIRED and repeat confirm of CONFIRMED are 200 no-ops, including new keys.
Ownership and current session/CSRF are checked before replay and after waits.

History orders `(created_at, id)` ascending and returns `items`/`next_cursor`. Cursors are
bounded and scoped to the authenticated user. Reservation/availability timestamps normalize
to UTC. GETs perform no reservation writes; effective EXPIRED can have null expired_at until
cleanup. Availability filters PUBLISHED events and uses one PostgreSQL statement/snapshot with
a single database time sample, valid HELD plus CONFIRMED rows, and no cache.

## Phase 6 quotas and public metadata consistency

Payload shapes and API version 0.4.0 remain unchanged. Limited endpoints additionally return
429 RATE_LIMITED with integer Retry-After and the existing error envelope. Defaults use
60-second windows anchored at the first accepted request: new anonymous sessions 30/peer,
login/register combined 10/peer, public event list/detail/availability combined 120/peer,
and all booking commands/replays plus organizer mutations combined 60/authenticated user.
Forwarded headers do not select the peer; current server commands disable proxy-header trust.
Valid existing CSRF-token retrieval, logout, health, and private reads are unthrottled.

If Redis is unavailable, new-session creation/login/register return sanitized 503
TEMPORARILY_UNAVAILABLE with Retry-After: 1. Public reads and authenticated mutations continue
through PostgreSQL. All session/CSRF/role/ownership and post-wait rechecks remain mandatory.
Neither 429 nor limiter/database transient errors complete an idempotency outcome; retry the
same key for uncertain commands. PostgreSQL failures keep their existing controlled error.

Only GET /events/{event_id} has a server metadata cache. Its existing public detail fields,
including displayed capacity, can be stale for the configured TTL (default 15, maximum 60
seconds from the original Redis miss). A cache hit still requires a fresh SQL PUBLISHED
visibility check; a request after close commits receives 404 even if invalidation failed.
Concurrent reads can observe visibility before a concurrent close, as ordinary SQL reads do.
Edit/capacity/publish/close invalidate after commit. Older fills after invalidation retain
their original absolute expiry, and hits never extend it. Malformed/oversized/incompatible
cache data falls back to PostgreSQL. Redis does not contain private organizer/reservation data.
Lists and availability are uncached; availability remains the one-query advisory snapshot,
and every allocation/confirmation/expiration decision still uses the locked SQL transaction.
