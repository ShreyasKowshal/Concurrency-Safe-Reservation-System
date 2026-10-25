# API contract

## Implemented in Phase 1

These health endpoints remain unchanged. Machine-readable specification:
[health.openapi.yaml](health.openapi.yaml). `/docs` and `/openapi.json` are FastAPI tooling.

| Endpoint | Success | Failure |
| --- | --- | --- |
| GET /api/v1/health/live | 200: `{"status":"alive"}` | No external dependency check |
| GET /api/v1/health/ready | 200: `{"status":"ready","dependencies":{"postgresql":"up"}}` | 503: `{"status":"not_ready","dependencies":{"postgresql":"down"}}` |

Both send `Cache-Control: no-store`. Readiness checks connectivity and a trivial SQL query,
not migrations/schema, Redis, or future worker availability. No authentication is required.

## Phase 2 authentication and planned domain API

The five `/auth/*` routes below are implemented in Phase 2. All event, organizer, and
reservation HTTP routes remain unregistered. The full implemented specification, including
cookie/CSRF security schemes, is [api.openapi.yaml](api.openapi.yaml).

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
| GET /organizer/events/{event_id}/dashboard | limit, cursor | 200: counts + paginated reservation rows | Owning organizer |
| POST /events/{event_id}/holds | empty object | 201: reservation | Authenticated + idempotency key |
| POST /reservations/{reservation_id}/confirm | empty object | 200: reservation | Owner + idempotency key |
| POST /reservations/{reservation_id}/cancel | empty object | 200: reservation | Owner + idempotency key |
| GET /reservations/{reservation_id} | none | 200: reservation | Owner |
| GET /me/reservations | limit, cursor | 200: reservation rows + next_cursor | Authenticated |

Pagination: default 20, maximum 100, opaque cursor with stable ordering and ID tie-breaker.
Event summaries contain id/title/location/starts_at/booking_closes_at/status/capacity;
details additionally contain description/ends_at/organizer_id. Organizer responses may include
allocated_seats; public availability is computed in one consistent query from valid holds and
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

State/locking rules are normative in [concurrency.md](../concurrency.md). Future event and
reservation DTOs and OpenAPI schemas will be implemented with each phase; those routes
do not currently exist. Authentication is implemented as described below.

## Authentication details

Registration: password length 15-128; response contains `user: {id, email, role}` and a fresh
anonymous csrf_token. Email normalization and session/security policy are in [security](../security.md).
Login: password length 1-128; successful response has the same shape with a fresh authenticated
csrf_token and cookie. Register/login reject extra fields, including role, IDs, and active status.
Logout requires a JSON empty object, Origin (or trusted Referer fallback), cookie, and token;
success is an empty 204 response clearing the cookie. Current user returns only id/email/role.
CSRF bootstrap returns only csrf_token, with a cookie when a new pre-session is created.

Auth errors: 401 AUTHENTICATION_REQUIRED or INVALID_CREDENTIALS; 403 CSRF_FAILED/FORBIDDEN;
409 REGISTRATION_UNAVAILABLE; 415 UNSUPPORTED_MEDIA_TYPE; 503 TEMPORARILY_UNAVAILABLE.
There is no public organizer-provisioning endpoint. Roles can be exercised through reusable
dependencies and local promotion, not through unfinished organizer/event routes.
