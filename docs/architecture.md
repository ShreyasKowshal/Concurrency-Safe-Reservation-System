# CSRS architecture

## Implementation boundary

Phase 1 provides configuration, application/engine lifecycle, health checks, React health UI,
and development infrastructure. Phase 2 adds the five-table database foundation, one Alembic
migration, backend authentication, CSRF enforcement, reusable authorization guards, and
local administration commands. Phase 3 adds public event discovery and owner-only event
create/read/edit/capacity/publish/close operations with event-row locks. Phase 4 adds holds,
confirmation/cancellation, request-time expiration, durable idempotency, owner history/detail,
and public advisory availability. Redis limiting/caching, organizer dashboard, business UI,
and the standalone expiration worker remain **future work**.
See [Phase 4 validation](phase-4-validation.md) for the actual PostgreSQL correctness evidence.

## Modular monolith

The React browser client calls `/api/v1` on its own origin. In development Vite proxies
that path to FastAPI without rewriting the browser's Origin header. In the planned deployment,
the backend serves the built frontend from the same origin.

FastAPI handles transport/validation. Authentication/event/reservation services own transaction
boundaries and
authorization decisions. SQLAlchemy supplies synchronous sessions and database access.
PostgreSQL owns durable users, sessions, events, reservations, capacity, and idempotency.
Alembic owns schema evolution. Each request/worker transaction gets an independent session;
sessions are never shared across threads or requests. No generic repository framework is needed.

Redis will handle rate limits and short-lived public event metadata only. Its contents never
authorize allocations or decide confirmation validity. It is running in Compose in Phase 1,
but there is no Redis client or cache implementation yet.

A future standalone expiration process uses the same image and reservation service as the API.
It discovers overdue work in PostgreSQL. No Celery, broker, per-reservation timer, or in-process
API scheduler is required. Multiple API processes must remain correct without Python mutexes.

## Health and resource lifecycle

- `GET /api/v1/health/live`: process can answer HTTP; performs no dependency checks.
- `GET /api/v1/health/ready`: acquires a PostgreSQL connection and executes `SELECT 1`.
- PostgreSQL failure returns sanitized `503`, never a DSN, SQL error, or exception traceback.
- Both responses use `Cache-Control: no-store`.
- Engine creation occurs in application lifespan, without opening a connection. Shutdown
  disposes the pool. A database outage therefore does not prevent the process from starting.
- Connection establishment, pool checkout, and SQL statement execution have bounded timeouts.
  These are individual bounds, not a promised total request-latency SLA.
- Readiness does not assert schema currency, Redis availability, or future worker health.

## Configuration

Application variables start with `CSRS_`. Pydantic Settings validates environment variables
when the application factory is called, not during module import. Database and Redis URLs
are required and redacted in settings representations and rendered validation messages.
Only the explicit `postgresql+psycopg` driver is accepted. Production public origins require HTTPS.

There is no implicit `.env` search: Uvicorn's `--env-file .env` loads host development settings;
Compose injects its explicit `env_file`. Tests construct settings or set isolated variables.
`POSTGRES_*` variables configure the container, not the Python settings model.

`CSRS_PUBLIC_ORIGIN` is the browser trust boundary; do not derive trusted origins
from arbitrary Host or forwarded headers. Phase 2 validates source origins and session-bound
CSRF on auth mutations. No CORS middleware is enabled. Frontend `VITE_*` variables
must never contain secrets; API requests use relative same-origin URLs.

## Development and future hosting

Compose runs PostgreSQL 17 with a persistent volume, ephemeral Redis 7.4, FastAPI, and Vite.
The opt-in test profile has a separate disposable PostgreSQL instance and backend test runner.
Host ports bind to `127.0.0.1`. Production containers, provisioning, and credentials are out of
scope.

The reviewed future hosting option is a Docker web service, paid managed PostgreSQL,
a small background worker, and managed Redis. Choosing a Redis-compatible Valkey service
instead must be documented accurately. No cloud services are created in this phase.

## Interview explanation

The monolith keeps one deployable backend and one transaction boundary for the important work.
Organizer and reservation writes serialize through the same PostgreSQL event-row lock.
The event lock is deliberately a contention point for one event; unrelated events use different
rows. We will measure the cost before considering a more complicated inventory design.

See [database design](database.md), [transaction protocol](concurrency.md),
[CSRF/security contract](security.md), [API contract](contracts/api.md), and
[decision records](decisions.md).

## System architecture diagram

Solid arrows show implemented communication. Dashed arrows show future work. The browser
still displays health only; cookie-aware clients can use the implemented business APIs.

```mermaid
flowchart TB
    Web["React health screen<br/>Business screens: Phase 7 planned"]
    Client["Cookie-aware API client"]
    subgraph Backend["FastAPI modular monolith"]
        Api["Health, auth, events, reservations, availability"]
        Auth["Database sessions, CSRF, roles, ownership"]
        Events["Event services<br/>Existing writes lock event rows"]
        Booking["Reservation service<br/>Idempotency and event locks"]
        Cleanup["Shared due-hold transition<br/>Caller owns event lock and transaction"]
        Orm["SQLAlchemy + Psycopg<br/>Independent session per request"]
        Api --> Auth
        Api --> Events
        Api --> Booking
        Booking --> Cleanup
        Events --> Cleanup
        Auth --> Orm
        Booking --> Orm
        Events --> Orm
        Cleanup --> Orm
    end
    Pg[("PostgreSQL: durable source of truth")]
    Redis[("Redis: running, unused<br/>Phase 6 integration planned")]
    Worker["Standalone sweeper<br/>Phase 5 planned"]
    Web -->|"Vite /api health proxy"| Api
    Client -->|"JSON, cookie, Origin, CSRF, retry key"| Api
    Web -.->|"Phase 7 business screens"| Api
    Orm --> Pg
    Api -.-> Redis
    Worker -.-> Cleanup
```

Redis never decides capacity. The future worker must lock the event before calling the shared
cleanup; the helper neither claims a key nor commits. Request-time cleanup already works when
no worker runs. The current schema has five tables and no new Phase 4 migration.

## Application workflow diagram

These are implemented backend transitions. React account/event/booking screens remain Phase 7.

```mermaid
flowchart TD
    Login["Bootstrap, register, login<br/>Phase 2 cookie and CSRF"]
    Draft["Organizer creates draft"]
    Publish["Publish event"]
    Browse["Public event and advisory availability"]
    Hold["Authenticated POST hold<br/>One seat, up to 300 seconds"]
    Held["HELD<br/>Allocated +1"]
    Confirm["CONFIRMED<br/>Allocation unchanged"]
    Cancel["CANCELLED<br/>Release once"]
    Expire["EXPIRED<br/>Release once"]
    Rebook["New hold row and new key"]
    Login --> Draft --> Publish --> Browse
    Login --> Hold
    Browse --> Hold
    Hold -->|"Locked admission succeeds"| Held
    Held -->|"Before hold deadline"| Confirm
    Held -->|"Cancel before deadline"| Cancel
    Held -->|"At or after deadline"| Expire
    Confirm -->|"Cancel before event start"| Cancel
    Cancel --> Rebook
    Expire --> Rebook
    Rebook --> Hold
```

Closing an event blocks new holds without invalidating existing valid holds. Confirmed rows
never expire at the old hold deadline. Repeat confirm/cancel follow the state table in
[concurrency.md](concurrency.md). GET projects overdue HELD as effective EXPIRED without a write.
History stays private and uses `(created_at,id)` keyset pagination; availability is public for
PUBLISHED events, with one SQL snapshot and one database time sample, and remains advisory.

## Concurrency-safe reservation workflow

This sequence is implemented in Phase 4. Rate limiting before the transaction remains Phase 6.
For confirm/cancel, the service first discovers the immutable event ID with an unlocked,
owner-scoped reservation read. No reservation lock precedes the event lock.

```mermaid
sequenceDiagram
    participant Client as Cookie-aware client
    participant Api as FastAPI
    participant Service as Reservation service
    participant Db as PostgreSQL
    Client->>Api: POST command, JSON {}, cookie, Origin, CSRF, Idempotency-Key
    Api->>Api: Validate source, media type, body, UUID, exactly one valid key
    Api->>Service: Validated command
    Service->>Db: BEGIN READ COMMITTED, validate session, active user, CSRF, access
    Service->>Db: INSERT key claim ON CONFLICT DO NOTHING
    Note over Service,Db: Uniqueness waits for competing claims, authorization is rechecked afterward
    alt Matching committed key
        Service->>Db: Read stored response, commit replay transaction
        Service-->>Api: Original status/body, replayed true
    else Different fingerprint
        Service-->>Api: 409 IDEMPOTENCY_KEY_REUSED, original record unchanged
    else New claim
        Service->>Db: SELECT event FOR UPDATE
        Service->>Db: Refresh authorization and ownership after wait
        Service->>Db: SELECT clock_timestamp()
        Service->>Db: Due HELD to EXPIRED, decrement by rows actually changed
        Service->>Db: Apply hold, confirm, cancel, or business conflict
        Service->>Db: Store status/body/completed_at, flush
        Service->>Db: COMMIT all pieces atomically
        Db-->>Service: Commit acknowledged, release locks
        Service-->>Api: Committed outcome, replayed false
    end
    Api-->>Client: Original HTTP status/body, no-store
```

A flush sends SQL without committing. Business conflicts are values so useful expiration and
the stored conflict can commit together. Security/validation exceptions and database failures
roll back the new claim and changes. Missing/foreign resources return 404 without completing
an outcome. No remote call or password hashing occurs inside this lock.

The serialization point is the event row: if two users want the last seat, the waiter reads
fresh committed capacity after the winner commits. Every admitted hold adds one counted row
and one counter unit. Confirmation preserves the count; cancellation/expiry release only on
an actual transition. The invariant includes overdue **persisted** HELD rows until cleanup:

`allocated_seats = count(persisted HELD + CONFIRMED)`, within `[0, capacity]`.

The database CHECK bounds the counter; application protocol plus independent SQL checks prove
cross-table equality for the tested scenarios. Arbitrary administrator writes can violate it.
Capacity edits use the same due-hold helper and lock, committing cleanup even on a refused
reduction. All transactions cover one event; no reverse lock order or multi-event write exists.

A decision uses PostgreSQL actual time **after** the lock; transaction-start `now()` could
predate a wait. Equality at expiration is expired. A valid confirmation uses that decision
instant even if commit occurs later. Reservation output normalizes timestamps to UTC.

Idempotency fingerprints POST, canonical UUID path, and validated `{}`. `(user_id,key)`
uniqueness arbitrates across processes. The claim and completed outcome commit together; a
rolled-back claim is reusable. Records are retained in this MVP. A response lost after commit
or connection lost during commit requires the **same key**; no automatic server retry or new
key is generated. 503 transient failures are not stored. Replayed responses can be stale;
clients fetch the current reservation afterward.
