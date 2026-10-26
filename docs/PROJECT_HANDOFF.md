# CSRS project handoff: continue with Phase 5

**Snapshot, 2026-10-26:** Phases 1-4 are implemented, reviewed, committed, and pushed to main.
The latest verified implementation commit is `50cca058987a72adf4ac575b28cdbdc4840ca685`
(`feat: implement concurrency-safe reservations`). Its GitHub Actions workflow is **green**.
The final local suite passed **417 tests: 114 unit/contract and 303 real PostgreSQL integration**.
**Phase 5 - Expiration & Recovery - is next and has not started.** This documentation-only
update prepares that phase; it implements no worker or application change.

Repository: [Concurrency-Safe-Reservation-System](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System).
Local workspace: `C:\Users\ASUS\OneDrive\Desktop\csrs`.

Before editing in a new conversation, read this document, inspect Git status, and read the
current source and contracts. This is a snapshot, not a replacement for the implementation.
Some older reports, explanations, and the README retain pre-commit "pending review" wording. Those are
historical review records; they do not mean approved Phases 2-4 must be implemented again.
Do not rewrite their results to imply tests ran at a later commit.

## A. Project overview

The **Concurrency-Safe Reservation System (CSRS)** is a student-built event/workshop application
intended to demonstrate backend engineering in Software Engineer / SDE-1 interviews.
Its central capacity guarantee is implemented and tested through the shared PostgreSQL protocol:
concurrent reservation requests do not allocate beyond an event's capacity.

An attendee can use backend APIs to browse events and hold, confirm, or cancel one seat.
An organizer manages their own events and will eventually inspect a booking dashboard.
Local administrators provision
organizer access. The project is a modular monolith, deliberately sized for one student to
understand and defend; it is not a collection of microservices.

Currently working: health checks/UI, configuration, PostgreSQL schema/migrations, backend
registration/login/logout/current user, sessions/CSRF/roles, organizer event-management APIs,
public discovery/availability, one-seat holds, confirmation/cancellation, owner reservation
detail/history, durable idempotency, and request-time expiration. **The standalone expiration
worker, Redis integration, organizer dashboard, business UI, and production deployment remain
unimplemented.** The 50/100-attempt tests establish their documented correctness cases; they
are not production throughput or latency benchmarks.

The roadmap spans eight phases. Complete, test, report, review, approve, commit/push, and
verify CI for one phase before proceeding. Do not purchase services or provision paid
infrastructure under a routine implementation request.

## B. Technology stack

| Component | Actual role and current boundary |
| --- | --- |
| Python 3.12, FastAPI, Uvicorn | Synchronous backend handlers, validation, and HTTP serving; API/package version 0.4.0 |
| React 19, TypeScript 5.9, Vite 7, Node.js 24 | Existing health screen and development proxy; no account/event/booking forms |
| PostgreSQL 17 | Durable source of truth for identity, events, capacity, reservations, and idempotency |
| SQLAlchemy 2.0, Psycopg 3 | Synchronous sessions, explicit transactions, connection pool, SQL, and PostgreSQL driver |
| Alembic | Explicit schema migrations; one revision, 0001_foundation |
| Redis 7.4 | Running in Compose with persistence disabled; no application Redis client, limiter, cache, or session store |
| argon2-cffi, email-validator | Argon2id passwords and canonical validated ASCII email addresses |
| Database-backed opaque sessions | Random cookie secrets, server-side expiry/revocation, independent synchronizer CSRF tokens; no JWT/OAuth |
| Pytest, FastAPI TestClient, HTTPX2 | Unit/contract tests, real PostgreSQL integration, controlled concurrency/failure tests |
| Ruff | Backend lint and format checks |
| Docker / Docker Compose | Local development and a separate disposable PostgreSQL test service |
| GitHub Actions | CI on pushes/PRs: backend, frontend, Compose; no automatic production deployment |

Dependency constraints live in `backend/pyproject.toml`; resolved development constraints are
in `backend/requirements-dev.lock`. Frontend reproducibility uses `frontend/package-lock.json`
and npm ci. Do not upgrade dependencies merely to begin the next phase. HTTPX2 is the current
test client's dependency, not an application HTTP service. No Celery or broker is installed.

## C. Architecture and source map

### Components and request flow

The browser uses relative `/api/v1` URLs. Vite forwards `/api` to FastAPI without rewriting
Origin. The local browser trust boundary is `http://localhost:5173`; API documentation on
port 8000 does not get a CSRF exemption. Same-origin serving of the built frontend is a
future deployment design, not implemented hosting.

FastAPI routes handle HTTP/body validation and source/content-type checks. Authentication
and event/reservation services own explicit transactions. SQLAlchemy uses Psycopg to communicate with
PostgreSQL at READ COMMITTED isolation. Each request/worker transaction must own its own
database session; never share one concurrently. A database Session is distinct from a
user's security session row. No generic repository framework is needed.

For an existing-event mutation, the current flow is: validate HTTP input, begin a service
transaction, validate organizer/session/CSRF, lock the owned event, recheck authorization
after any wait, validate/change the event, flush, commit, then respond. A flush sends SQL;
it does not commit. Reservation commands first claim a user-scoped idempotency key, then lock
the event, refresh authorization, sample database time, clean due holds, and commit the
transition/counter/outcome together. No Redis call, remote I/O, or password work belongs inside
the event lock.

See the existing [architecture and three diagrams](architecture.md), especially the system,
application, and **implemented** reservation transaction diagrams. Their labels distinguish
implemented Phase 1-4 services from the planned worker, Redis integration, and business UI.
Detailed authority is in
[API contracts](contracts/api.md), [concurrency](concurrency.md), [database](database.md),
[security](security.md), [decisions](decisions.md), and [phase gates](phases.md).

### Important repository-relative paths

| Path | Purpose |
| --- | --- |
| `backend/src/csrs/main.py` | App factory, lifespan/engine ownership, routers, no-store/error handling |
| `backend/src/csrs/config.py` | Validated CSRS_ environment settings; URLs redacted; no implicit .env loading |
| `backend/src/csrs/database.py` | READ COMMITTED engine, pool and connection/statement timeouts |
| `backend/src/csrs/models.py` | Five SQLAlchemy application tables and named constraints/indexes |
| `backend/src/csrs/api/health.py` | Liveness/readiness routes |
| `backend/src/csrs/api/auth.py` | Five authentication endpoints |
| `backend/src/csrs/api/events.py` | Public and organizer event routers |
| `backend/src/csrs/api/reservations.py` | Hold/confirm/cancel, private detail/history, advisory availability routes |
| `backend/src/csrs/api/openapi.py` | Cookie/CSRF security declarations; preserves path/query parameters |
| `backend/src/csrs/auth/` | Crypto, schemas, HTTP guards, service transactions, dependencies, admin commands |
| `backend/src/csrs/events/` | Event schemas, transaction services, errors, scoped pagination |
| `backend/src/csrs/reservations/service.py` | Durable claim/replay, event-locked reservation transactions, supporting reads |
| `backend/src/csrs/reservations/transitions.py` | Shared expire_due_holds helper; caller owns event lock/transaction |
| `backend/src/csrs/reservations/schemas.py` | UTC reservation/page/availability response DTOs |
| `backend/src/csrs/cli.py` | Explicit local promotion/session-cleanup entrypoint |
| `backend/migrations/env.py` | Alembic metadata and supplied isolated test-connection support |
| `backend/migrations/versions/0001_foundation_foundation_schema_and_sessions.py` | Explicit initial schema upgrade/downgrade |
| `backend/scripts/export_health_contract.py` | Intentionally refreshes complete and health OpenAPI snapshots |
| `backend/scripts/smoke_reservations.py` | Local live HTTP verification with generated records and scoped cleanup |
| `backend/tests/unit/` | Config, health, crypto, event input/cursor, runtime-contract checks |
| `backend/tests/integration/` | Real PostgreSQL auth, events, schema, migrations, and concurrency/failure cases |
| `backend/tests/integration/test_reservations.py` | Reservation HTTP/state/deadline behavior and SQL invariants |
| `backend/tests/integration/test_reservation_transactions.py` | Two-process contention, controlled lock waits, strengthened clock test, faults |
| `frontend/src/App.tsx` | Health screen; latest change is Phase 4 label |
| `frontend/src/api/health.ts` | Validated readiness fetch and frontend error classification |
| `frontend/vite.config.ts` | Origin-preserving /api proxy |
| `compose.yaml`, `backend/Dockerfile`, `frontend/Dockerfile` | Development/test containers, ports, volumes, startup |
| `.github/workflows/ci.yml` | Foundation CI, including required PostgreSQL tests |
| `.github/dependabot.yml` | Dependency-update proposals; does not automatically merge changes |

The reservation module and shared expiration transition exist and must be reused by Phase 5.
There is no standalone worker entrypoint, worker Compose service, or Redis integration yet.
Do not invent an existing worker command or independently commit the shared helper.

## D. Completed phases and their evidence

Counts below are historical final results, not fresh executions for this handoff. Each later
suite retains earlier behaviors; counts must not be added together as independent totals.

| Phase | Completed scope | Final recorded tests | Source |
| --- | --- | --- | --- |
| 1 | Monorepo, configuration, health backend/UI, Compose, Alembic scaffolding, CI, contracts | 24 passed: 22 unit/contract + 2 real PostgreSQL; exit 0 | [Validation](phase-1-validation.md), [explanation](phase-explanations/phase-1-explanation.md) |
| 2 | Five tables, initial migration, sessions/auth/CSRF/roles/admin CLI | 170 passed: 54 unit/contract + 116 PostgreSQL; exit 0 | [Validation](phase-2-validation.md), [explanation](phase-explanations/phase-2-explanation.md) |
| 3 | Public/owner event reads, draft create/edit/capacity/publish/close, event locks | 323 passed: 107 unit/contract + 216 PostgreSQL; exit 0 | [Validation](phase-3-validation.md), [explanation](phase-explanations/phase-3-explanation.md) |
| 4 | Holds, confirmation/cancellation, request-time expiry, durable idempotency, private history/detail, public availability | 417 passed: 114 unit/contract + 303 PostgreSQL; exit 0 | [Validation](phase-4-validation.md), [explanation](phase-explanations/phase-4-explanation.md) |

### Phase 1: foundation

Introduced `GET /api/v1/health/live` and `GET /api/v1/health/ready` through the health route,
settings/engine factory, React health client, Compose, and CI files listed above. Liveness
checks no dependency; readiness executes SELECT 1 and returns controlled 200/503 responses.
Both are no-store. Engine construction is lazy at startup and the pool is disposed at shutdown.
Invalid PostgreSQL configuration fails early, with secret values redacted.

There were no application tables or migration revision in Phase 1. The later final validation
resolved initial Docker-related test skips. A read-only PostgreSQL restart check retained
cluster/catalog identity and volume attachment; it was not a business-data backup/restore test.
Redis was provisioned, not integrated. Authentication and capacity correctness were future work.
Phase 1's verified final commit is `cc4f3df452e2ce49ca5d496705d44d38543499e1`.

### Phase 2: schema and identity

Introduced `GET /auth/csrf`, `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`,
and `GET /auth/me`, all below `/api/v1`. Main implementation is the models/migration, auth
modules, CLI, route/OpenAPI modules, and PostgreSQL fixtures. Chose opaque revocable sessions,
anonymous pre-sessions for login/registration CSRF, Argon2id, controlled errors, and server roles.
Public registration cannot elevate privileges. Session rotation and locked rechecks prevent
competing use of one consumed pre-session. Migration/constraint tests use actual PostgreSQL.

No event or reservation command existed yet. Password recovery, email verification, MFA,
auth screens, rate limiting, and scheduled maintenance remain absent today. The implementation
commit is `4b7aaa8d4628b55b122692a62f0ff48b61d87410`.

### Phase 3: event management

Introduced the nine event operations in section G using `backend/src/csrs/api/events.py`
and `backend/src/csrs/events/`.
The existing table/schema was sufficient, so no migration or new dependency was added.
Private owner detail was added to resolve an earlier contract gap without exposing drafts
on the public endpoint. Pagination is keyset-based, scoped, and owner-filtered in SQL.

Existing-event writes serialize through PostgreSQL event-row locks. Tests observe real
blocking, post-wait session/role/state changes, rollback after flush, and a safe statement
timeout. Capacity tests use consistent seeded reservation data; no booking API was implemented.
Final local evidence: 323 passed in 26.81s, no failures/skips, 31 expected live proxy smoke
checks, and six localhost HTTP checks. Temporary smoke records were removed and original
row counts restored. No generated test databases remained. CI is independently verified green
for Phase 3 commit `48790480c9959442d1121dd85191529199960399`. These are correctness tests
for their stated scope, not reservation performance or completed final-seat booking evidence.

### Phase 4: concurrency-safe reservations

Implemented all six reservation-flow operations in H1, using the existing authentication,
five-table schema, READ COMMITTED engine, constraints, and event-lock protocol. No schema
revision or dependency upgrade was needed. Capacity edits now reclaim due holds under their
existing event lock. Commands commit claim, cleanup, reservation state, counter, and completed
response together. GETs remain write-free and public availability is advisory.

Final local verification: **417 passed in 58.53s**, exit 0, no failures/skips: 114 unit/contract
plus 303 real PostgreSQL integration cases. The suite retains Phase 1-3 behavior. Two independent
Uvicorn API processes admitted exactly 1 of 50 attempts for capacity 1 and 20 of 100 for capacity
20. Duplicate keys, same-user different keys, competing transitions, rollback, timeout,
response loss, and simulated uncertain commit outcomes pass with SQL reconciliation.

The audit found zero BLOCKER/HIGH/LOW issues and one MEDIUM test-coverage finding. It is
resolved: the post-lock clock test now observes the waiting transaction's actual xact_start,
sets a deadline strictly between that start and event-lock release, and checks persisted expiry
and the durable 409 outcome. The target passed initially and in **10/10 fresh executions**.
An in-memory SELECT now() negative control returned 200 and failed the same 409 assertion as
intended, proving sensitivity to transaction-start time. Production behavior was unchanged.

Other recorded checks passed: Ruff/51 formatted Python files, dependency checks, Alembic head/
current/drift, frontend TypeScript/build, Compose, exact OpenAPI equality, 33 live HTTP smoke
checks with original table counts restored, six localhost checks, Markdown, local references,
and four diagrams. Supplemental verification runs do not add cases to the 417-test total.
The validation report distinguishes initial and final follow-up checks and their commands.

Commit `50cca058987a72adf4ac575b28cdbdc4840ca685` changes 32 files: 21 modified and 11 added,
3,492 insertions and 353 deletions. It was pushed to origin/main with matching local/remote
hashes and a clean working tree. [Foundation CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40235993807)
is completed/success for that exact commit; backend, frontend, and compose jobs are all green.
These are Phase 4 implementation results, not fresh test executions for this documentation edit.

## E. Current database design

### Tables and relationships

| Table | Key columns and relationships |
| --- | --- |
| users | UUID, normalized_email, Argon2id password_hash, ATTENDEE/ORGANIZER role, is_active, created_at/updated_at |
| sessions | UUID, optional users FK, ANONYMOUS/AUTHENTICATED kind, unique cookie token_hash, csrf_token, created_at/expires_at/revoked_at |
| events | UUID, organizer users FK, title/description/location, starts_at/ends_at/booking_closes_at, status, capacity/allocated_seats, timestamps |
| reservations | UUID, event/user FKs, status, hold_expires_at, confirmed_at/cancelled_at/expired_at, timestamps; Phase 4 transitions implemented |
| idempotency_records | UUID, user FK, key, request_fingerprint, response_status/body, created_at/completed_at; durable command outcomes implemented |

All application IDs are UUIDs with Python/server defaults; PostgreSQL supplies gen_random_uuid().
Foreign keys use RESTRICT, preserving referenced history. Time columns are timezone-aware;
API timestamps use UTC. States are strings with named CHECK constraints, not PostgreSQL enums.
Created timestamps default to transaction-start now(). SQLAlchemy updates updated_at on user/
event/reservation updates; Phase 4 explicitly uses the decision instant for new/transitioned
reservation timestamps. Arbitrary administrator SQL has no automatic timestamp trigger.

### Constraints all reservation/worker writes must preserve

- Email is normalized ASCII/lowercase and unique. Session cookie digests are unique. An
  anonymous session has no user; an authenticated session must reference one. Session expiry
  is after creation. Token digests and CSRF values have a 64-character lowercase hex format.
- Events use DRAFT/PUBLISHED/CLOSED; capacity >=1; `0 <= allocated_seats <= capacity`;
  `booking_closes_at <= starts_at < ends_at`. Owner role eligibility is a service rule,
  not something the event foreign key proves.
- Reservations use HELD/CONFIRMED/CANCELLED/EXPIRED, with hold_expires_at after creation.
  State/timestamp combinations must agree. Confirmation is at/after creation and strictly
  before the hold deadline. Expiration is at/after that deadline. Cancellation is at/after
  creation and any prior confirmation. A cancelled confirmed row retains confirmed_at;
  an expired row cannot have been confirmed.
- The partial unique index on `(user_id, event_id)` for persisted HELD/CONFIRMED permits only
  one active reservation, including requests with different keys. Do not add now() to that
  predicate. Clean an overdue HELD row under the event lock before inserting its replacement.
- Idempotency has unique `(user_id, key)`. Keys are 1-128 visible ASCII characters without
  spaces; fingerprints are 64 lowercase hex characters. Pending response fields are all NULL;
  completed fields must be present together with status 200-499, object JSONB, and a completion
  timestamp at/after creation. The Phase 4 service forbids independently committed pending
  claims and excludes transient/security outcomes despite the wider storage constraint.

Reservation owner/event immutability and legal transition order require service enforcement;
the schema alone does not supply them. No trigger/stored procedure enforces cross-table counts.

### Capacity invariant and indexes

The implemented reservation protocol maintains, for each event at every committed state:

```text
allocated_seats = count(persisted HELD) + count(CONFIRMED)
0 <= allocated_seats <= event.capacity
```

**Persisted HELD includes overdue rows awaiting cleanup.** Effective occupancy can exclude
those rows, but the stored counter changes only when a transaction changes their status.
Do not compare the counter with only currently valid holds and report a false mismatch.
The event CHECK bounds the counter; it cannot enforce equality with another table's rows.
Correctness assumes all application/worker writes follow the shared protocol, not arbitrary SQL.

Existing indexes include unique email/session digest; session expiry/user; event organizer;
published `(starts_at,id)`; reservation `(user_id,created_at,id)` history and `(event_id,status)`;
partial HELD `(hold_expires_at,event_id)` expiration discovery; active-user uniqueness; and
the user/key idempotency constraint. See actual names in `backend/src/csrs/models.py`.

### Migrations and transactions

Alembic head is **0001_foundation**. Phases 3-4 changed no schema. Migrations are explicit admin
steps, not startup create_all or an automatic task in each API process. Preserve current
migrations; add a revision only for a necessary reviewed schema change. Downgrade is destructive
and is tested only against generated disposable databases.

READ COMMITTED, explicit service transactions, and `SELECT ... FOR UPDATE` are established.
User commands claim idempotency, lock the event, then lock/update reservation rows. Phase 5
worker transactions need no user key and must lock the event before reservation updates. Never commit
row/counter/idempotency pieces independently or use a nested service's independent commit.

## F. Authentication and authorization

### Account/session flow

1. `GET /api/v1/auth/csrf` returns a valid session's stable token or creates an anonymous
   pre-session: random cookie secret plus independent CSRF token, default lifetime 15 minutes.
2. Register using JSON, that cookie/token, and trusted source. Email is stripped, validated
   without DNS, converted to ASCII, and lowercased. Password length is 15-128 with no trimming
   or truncation. The server assigns ATTENDEE, replaces the anonymous session, and does not log in.
3. Login accepts password length 1-128. It verifies Argon2id outside a database transaction,
   then locks/rechecks the pre-session and user. Success deletes the old pre-session and
   issues independently fresh authenticated secrets, default absolute lifetime eight hours.
4. `GET /auth/me` reads current active-user/session state and returns only id/email/role.
   Logout requires a valid authenticated cookie/CSRF/source and JSON `{}`; it revokes the
   stored session, clears the cookie, and returns 204. Old-cookie replay fails.

Argon2id uses 19,456 KiB memory, two iterations, one lane, fresh 16-byte salts, 32-byte output;
older parameters can be upgraded on successful login. Unknown users still perform dummy
verification; unknown/wrong/inactive credentials share one 401 response. This is not constant
end-to-end latency. Duplicate registration's generic 409 can disclose account availability.

Cookie and CSRF values each have 256 random bits. Only the cookie's SHA-256 digest is stored
as the authentication verifier; the independent synchronizer CSRF value is stored server-side.
Neither belongs in logs/URLs or browser persistent storage. CSRF alone cannot authenticate.
Local HTTP uses csrs_session, host-only, Path=/, HttpOnly, SameSite=Lax. HTTPS uses Secure and
the __Host-csrs_session prefix; production settings require an HTTPS origin. No deployment exists.

### CSRF and endpoint reuse

The existing `backend/src/csrs/auth/http.py` validates trusted Origin, or Referer only when
Origin is absent.
Null, duplicate, or untrusted Origin is rejected without fallback. Mutations require JSON and
the matching session-bound X-CSRF-Token, including registration/login, logout, and implemented
idempotent replays. Bootstrap may lack source headers initially but rejects explicitly unsafe
sources/Fetch Metadata. No permissive CORS or special script/Swagger bypass exists.

Reuse `Database`, `CurrentUser`, `require_attendee`, `require_organizer`, and `require_owner`
from `backend/src/csrs/auth/dependencies.py`; organizers retain attendee capabilities.
Read dependencies alone
do not authorize a write. Reservation mutation services use the existing session/CSRF primitives
inside their transaction, refresh user/session state after waits, and check owner IDs obtained
from stored resources. Do not call current_user's transaction-owning helper inside an already
open transaction; structure service ownership deliberately. Reuse the established controlled
errors, sanitized validation, no-store policy, and OpenAPI cookie-plus-CSRF security.

Local provisioning is `python -m csrs.cli promote-organizer EMAIL` for an existing active user;
it revokes that user's sessions and requires login again. There is no public role-selection API.
The bounded purge-sessions CLI removes expired/revoked security sessions; it is not scheduled,
and it does not expire reservations. Logout/revocation does not cancel requests that already
completed their authorization checks. Post-lock rechecks address state changes during a wait.

## G. Phase 3 event-management behavior to preserve

All paths below have `/api/v1` prefix. Create returns 201; other successful operations return 200.

| Method/path | Visibility/authorization and behavior |
| --- | --- |
| GET /events | Public PUBLISHED summaries, paginated |
| GET /events/{event_id} | Public PUBLISHED detail; draft/closed/missing is 404, even for an owner |
| GET /organizer/events | Active organizer's own events in all states, paginated |
| GET /organizer/events/{event_id} | Owning organizer's detail, including allocated_seats |
| POST /organizer/events | Organizer + mutation protections; server-owned DRAFT with allocation zero |
| PATCH /organizer/events/{event_id} | Owner; permitted metadata only; entire merged schedule validated |
| PATCH /organizer/events/{event_id}/capacity | Owner; positive bounded integer, not below stored allocation |
| POST /organizer/events/{event_id}/publish | Owner; DRAFT only, future start/deadline after event lock |
| POST /organizer/events/{event_id}/close | Owner; PUBLISHED only, changes status without cancelling/releasing rows |

The state machine is **DRAFT -> PUBLISHED -> CLOSED**, with no reopening/deletion/event-wide
cancellation. Repeated publish/close is 409, not idempotency replay. All existing-event writes,
including metadata edits, use the event-row lock and recheck authorization/state after waits.

Creation requires title/location/three timestamps/capacity; description defaults empty.
Title/location are trimmed/nonempty with 200/300 character limits; description max 10,000.
Capacity must be a JSON integer 1-2,147,483,647, excluding booleans/numeric strings/fractions.
Timestamps require timezone-qualified RFC 3339 and normalize to UTC; naive/epoch values fail.
Always enforce booking_closes_at <= starts_at < ends_at. A structurally valid stale draft is
allowed, but cannot publish until its start and booking deadline are strictly future.

Draft metadata PATCH permits title/description/location/start/end/deadline. PUBLISHED permits
title/description/location/end only; merely supplying start/deadline, even unchanged, is 409.
Capacity is a separate endpoint. PATCH must be nonempty, with no explicit nulls/extra fields.
Publish/close require `{}`. Owner, ID, status, and allocation counter are never client-owned.
CLOSED is read-only. Foreign private IDs produce 404. All event responses currently use no-store.
Event commands have no Idempotency-Key/replay contract; Phase 4's key requirement is for
hold/confirm/cancel, not an implicit change to organizer endpoints.

Public visibility is publication status, not bookability: full or past PUBLISHED events remain
visible until closed. Lists order by `(starts_at,id)`, default limit 20, max 100, with scoped
base64url JSON cursors capped at 512 characters. Cursors are navigation, not authorization;
every query still filters publication/owner. Pages are not a frozen snapshot across edits.
Summaries contain id/title/location/start/deadline/status/capacity; detail adds description/
end/organizer_id. Organizer variants add allocated_seats; public ones do not expose it.

**Integration point:** `backend/src/csrs/events/service.py` now runs shared due-hold cleanup
under the event lock before comparing capacity with stored allocation. Cleanup commits even
if a requested reduction is still refused. Its `_owned_event` context manager already opens a
transaction: do not nest it blindly inside another transaction or independently commit cleanup.
Preserve current role/ownership/time restrictions. Closing must continue to leave existing
valid holds eligible for future confirmation; a blanket PUBLISHED check on confirmation would
violate the contract. Capacity changes must not invalidate already counted bookings.

## H. Implemented Phase 4 reservation contract to preserve

### H1. Scope, authority, and endpoint contracts

Phase 4 implements holds, confirmation/cancellation, request-time expiry, and durable idempotency.
The normative behavior is in [concurrency.md](concurrency.md) and [API contract](contracts/api.md).
The [OpenAPI snapshot](contracts/api.openapi.yaml) includes the registered reservation routes,
DTOs, key header, replay headers, and cookie/CSRF declarations. Preserve these working contracts.

| Implemented method/path | Body and success | Access |
| --- | --- | --- |
| POST /events/{event_id}/holds | `{}`; 201 reservation | Authenticated attendee/organizer, session CSRF/source/JSON, Idempotency-Key |
| POST /reservations/{reservation_id}/confirm | `{}`; 200 reservation | Reservation owner, same protections and key |
| POST /reservations/{reservation_id}/cancel | `{}`; 200 reservation | Reservation owner, same protections and key |
| GET /reservations/{reservation_id} | 200 reservation | Owner |
| GET /me/reservations | Paginated reservation rows | Authenticated user |
| GET /events/{event_id}/availability | event_id/capacity/available_seats/as_of | Public, advisory, never allocation authority |

All six operations above are implemented. The organizer dashboard
`GET /organizer/events/{event_id}/dashboard` remains planned and unregistered: future owner-only
counts and paginated reservation rows. Dashboard/business UI work is not part of Phase 5.

Reservation output is id/event_id/effective status/created_at/hold_expires_at/confirmed_at/
cancelled_at/expired_at/server_time. UUID IDs, UTC RFC 3339 times, sanitized validation, and
the existing error envelope are retained. Reject client-supplied user/owner/state/counter fields.
History pagination orders `(created_at,id)` ascending with user-scoped cursors, default 20 and max 100.
An overdue stored HELD reads as effective EXPIRED without a GET-side write; expired_at remains
null until cleanup persists it. Availability is computed in one consistent database query
from valid holds plus confirmed rows, is not cached, and never guarantees a later hold succeeds.
Future dashboards must distinguish valid holds, overdue HELD awaiting cleanup, confirmed,
cancelled, expired, and the stored counter rather than presenting incompatible counts as equal.

### H2. Admission and capacity accounting

One reservation is exactly **one seat**. Permit only one active persisted HELD/CONFIRMED row
per user/event. Both the service and existing unique index defend this; different keys must
not bypass it. Terminal rows remain history. Rebooking needs a new row and a new key.

A new hold requires PUBLISHED status, an open booking deadline, no active reservation for
that user/event after due cleanup, and allocated_seats < capacity, checked only after locking.
The hold TTL defaults to five minutes (300 seconds), configured through Settings and
`CSRS_HOLD_TTL_SECONDS` with bounds 1-3600 seconds. The deadline is:

```text
hold_expires_at = earlier of (decision_time + hold TTL) and event.booking_closes_at
```

Never create a hold with no remaining validity. Booking closes no later than event start.
An accepted hold inserts HELD and increments allocation by one in the same transaction.
Confirmation changes state without incrementing again. Cancellation/expiration release once,
only if they actually transition a counted row. Always preserve the persisted-count invariant
in E, including overdue HELD until its status/counter transition commits.

### H3. Exact reservation state transitions

| Starting state | Command/condition | Ending state | Allocation delta | Result |
| --- | --- | --- | --- | --- |
| No reservation | Hold admitted | HELD | +1 | 201 |
| HELD | Confirm before deadline | CONFIRMED | 0 | 200 |
| HELD | Confirm at/after deadline | EXPIRED | -1 | 409 HOLD_EXPIRED |
| HELD | Cancel before deadline | CANCELLED | -1 | 200 |
| HELD | Cancel at/after deadline, or expire | EXPIRED | -1 | 200 for cancellation |
| CONFIRMED | Confirm again | CONFIRMED | 0 | 200, even after the former hold deadline |
| CONFIRMED | Cancel before event start | CANCELLED | -1 | 200 |
| CONFIRMED | Cancel at/after event start | CONFIRMED | 0 | 409 CANCELLATION_CLOSED |
| CANCELLED | Cancel again | CANCELLED | 0 | 200 |
| EXPIRED | Cancel | EXPIRED | 0 | 200 |
| CANCELLED/EXPIRED | Confirm | Unchanged | 0 | 409 INVALID_RESERVATION_STATE or HOLD_EXPIRED per terminal state |

Terminal rows never reactivate. CONFIRMED rows never expire at the hold deadline.
Closing an event prevents new holds, but **does not invalidate otherwise valid existing
holds**. A first HELD-to-CONFIRMED transition after booking close is impossible because the
hold deadline is capped by booking close; a repeated confirmation of an already CONFIRMED row
is still the documented no-op. Confirmed cancellation is allowed strictly before event start, independent
of the old hold TTL. Do not add event-wide cancellation, quantities, seat maps, or payment state.

### H4. Transaction, lock order, and database time

The reservation service implements this single-event user-command protocol:

1. Authenticate and validate JSON, source/CSRF, request shape, and ownership context.
   A future Phase 6 rate limiter runs outside the capacity transaction; do not implement
   Redis merely because it appears in this later protocol.
2. Begin one READ COMMITTED transaction and claim the user-scoped idempotency key.
   Session/CSRF and current authorization must also be valid inside the mutation service.
3. After any claim wait, refresh session/CSRF/authorization before replay. For a new claim,
   lock the event using SELECT ... FOR UPDATE. Read current capacity/state after the lock,
   with refreshed SQLAlchemy state, and recheck authorization/session after waits.
4. Sample PostgreSQL **clock_timestamp() after acquiring the event lock**. Use this single
   decision instant for all due-hold checks and transition timestamps in that command.
5. Transition this event's due persisted HELD rows to EXPIRED and decrement allocation by
   the number actually changed. Integrate this same helper into capacity editing under its lock.
6. Apply the requested transition/counter change, or determine the business conflict.
7. Store the completed response in the idempotency row and commit all changes atomically.
8. Return the response only after commit succeeds. Do not send success before a commit.

Lock order is **idempotency claim -> event -> reservation rows**. For reservation-addressed
commands, discover the immutable event ID without first locking the reservation, then lock
the event and reread the reservation and ownership. Never reverse this ordering. Future
workers discover candidate event IDs without holding reservation locks and then follow it.
Each transaction covers one event; multi-event commands require a new reviewed ordering.

Validity is `decision_time < hold_expires_at`; equality means expired. Do not use transaction-
start now() after a lock wait, or browser/application clocks for booking eligibility. A request
that arrived before expiry but obtains the lock afterward fails. A confirmation accepted
just before expiry may commit afterward; its confirmed_at must reflect the valid decision
instant, not a later wall clock. Respect the existing timestamp CHECKs.

For the last seat, two distinct users must contend on the same event row. The winner commits
the new allocation; the waiter reads that committed state and cannot allocate beyond capacity.
This must work across database connections/API processes, without Python mutexes or Redis locks.
Different events have different row locks. Measure hot-event contention rather than inventing
throughput claims or redesigning inventory before evidence exists.

### H5. Idempotency, duplicate commands, and uncertain outcomes

- Require exactly one Idempotency-Key on hold/confirm/cancel: 1-128 visible ASCII characters,
  no spaces; missing, duplicate, and malformed keys receive sanitized 422 validation.
  Scope is user-wide, not merely per endpoint. Fingerprint method + canonical path + validated
  canonical JSON body. The same key with another path/body is not a new operation.
- Use PostgreSQL uniqueness to arbitrate competing claims. The winner records its response
  in the **business transaction**; concurrent matching duplicates wait and replay after commit.
  A rolled-back claim can be retried. Never commit a pending claim independently.
- Same key/different fingerprint returns 409 IDEMPOTENCY_KEY_REUSED without overwriting the
  original outcome. Same user/different keys is still constrained by active reservation uniqueness.
- Replay the original status/body with `Idempotency-Replayed: true`; new execution uses false.
  Do not re-execute a successful transition just to obtain current status. The client fetches
  current resource state afterward because the original response can be stale.
- Authentication, CSRF, ownership, and later throttling apply before replay. Idempotency is
  neither authentication nor CSRF protection. Use no-store for authenticated/idempotent results.
- Store completed business conflicts, including EVENT_FULL/HOLD_EXPIRED. A later retry of
  that same key still returns the original result even if seats become available. New intent
  needs a new key. Security/validation/rate-limit failures and transient database failures/429s
  are not completed booking outcomes. Retain idempotency records in the MVP; no retention/
  key-reuse policy has been implemented.
- A response lost after commit is recovered with the same key. A connection lost during
  commit has an **uncertain outcome**, not proof of rollback. The client must retry that key;
  do not automatically generate a new one or blindly repeat non-idempotent work.
- The current service performs no automatic retries. Any future bounded server retry must be
  limited to known safe transaction-abort cases. Lock timeout rolls back and returns retryable
  503. Do not continue using an aborted SQLAlchemy transaction
  after an IntegrityError without correct rollback/savepoint handling.

Use the existing error codes: EVENT_FULL, BOOKING_CLOSED, ACTIVE_RESERVATION_EXISTS,
HOLD_EXPIRED, INVALID_RESERVATION_STATE, CANCELLATION_CLOSED, CAPACITY_BELOW_ALLOCATED,
IDEMPOTENCY_KEY_REUSED, and TEMPORARILY_UNAVAILABLE, plus existing security/validation errors.
Normal business conflicts use 409; missing/unusable auth 401, role/CSRF 403, unavailable/foreign
private resource 404, unsupported JSON media type 415, invalid fields 422, transient DB/lock 503.
429/RATE_LIMITED belongs to the later limiter phase; it is not implemented today.

### H6. Request-time expiration versus Phase 5 worker

Phase 4 reclaims due holds for the locked event before admission and uses the shared cleanup
in capacity edits. It rejects expired confirmations at the boundary even when no worker runs.
Cleanup decrements only rows actually transitioned. Cancellation of an overdue
hold results in EXPIRED, not a second release or an invented CANCELLED transition.

Useful cleanup may coexist with a business failure. Confirming an expired hold must commit
expiration/counter change **and the stored 409 response**. Throwing a rollback-triggering HTTP
exception inside the transaction would undo both; construct/return the outcome after commit.
Faults before commit must roll back reservation, counter, and idempotency together.

Phase 5 separately adds a standalone polling process, initially one worker, approximately
15-second polls and bounded candidate-event batches. It will lock/recheck one event per
transaction and call the same service. No Celery, per-hold timer, or in-process API scheduler
is required. Worker lag/outage can delay stored cleanup, but cannot permit an expired
confirmation or prevent an active request from reclaiming due capacity. Worker restart,
duplicate sweeps, and stale candidates belong to that phase's verification, not an imaginary
worker test claim in Phase 4. Unvisited events may retain conservative stored HELD rows until
request cleanup or the later sweeper runs.

### H7. Completed tests, audit, and acceptance evidence

The implemented suites use generated PostgreSQL databases, independent sessions/connections,
real commits, barriers/controlled lock holders, and observed pg_blocking_pids waits.
The two-process HTTP tests start separate Uvicorn apps/engines. Active connections are bounded
by each pool (5 plus overflow 5), not 50/100 pre-opened connections. This still exercises
cross-process coordination without Python mutexes or SQLite substitutes.

Covered cases include final-seat contention, concurrent same-user/different-key and duplicate
claims, path fingerprint mismatch, confirm/cancel/expiry in both orderings, capacity edit versus
admission, close versus admission/valid confirmation, post-wait auth/state changes, and response
loss/replay. All valid command bodies are `{}`; different nonempty bodies fail validation before
a claim. SQL checks compare the counter with persisted HELD/CONFIRMED rows in one snapshot.

Fault tests cover row/counter/outcome writes, before commit, response loss after commit, and
both committed/uncommitted simulations of uncertain commit outcomes. Real statement timeout
rolls back and permits same-key retry. Network loss during COMMIT is simulated, not a physical
connection-cut experiment. Worker restart/stale sweep/duplicate sweep recovery is Phase 5;
Redis outage/rate-limit behavior is Phase 6. Do not present those future tests as already passed.

Phase 4's implemented acceptance gate is complete:

- [x] Hold/confirm/cancel routes, DTOs, supporting reads, errors, CSRF/ownership, and OpenAPI match.
- [x] One-seat admission, capped five-minute holds, exact time boundaries, terminal history,
  repeat-confirm/cancel rules, and existing CLOSED-event behavior are implemented/tested.
- [x] All booking/capacity paths follow one event-lock protocol and shared due-hold cleanup.
- [x] Committed test snapshots satisfy counter bounds/equality and active-user uniqueness.
- [x] Durable claim/fingerprint/replay, concurrent duplicates, stored business conflicts,
  rollback, response loss, uncertain commit, and retryable timeout tests pass.
- [x] Full suite: 417 passing cases, retaining Phase 1-3 behavior with documented scope updates.
- [x] Real PostgreSQL deterministic race evidence, migration checks, lint/format,
  TypeScript/build, Compose, API-contract, and relevant HTTP smoke checks are reported.
- [x] Phase 4 validation/explanation documents show actual counts, commands, limitations,
  changed-file manifest, and clear separation from the unimplemented Phase 5-8 work.
- [x] Independent audit completed; the MEDIUM clock-test finding resolved and mutation-checked.
- [x] User approved publication; implementation committed/pushed with matching hashes and green CI.
- [x] Worker, Redis integration, full UI, payments, and deployment remain deferred.

## I. Next phase: Phase 5 - Expiration & Recovery

**Planned only; not implemented or started by this handoff update.** Begin Phase 5 only after
a new explicit implementation request. Its purpose is to persist expiration on quiet events
and recover safely after worker/database interruption. Request-time correctness already exists.

### Dependencies and reuse

- Verified Phase 4 implementation `50cca058987a72adf4ac575b28cdbdc4840ca685` and its green CI.
- Existing PostgreSQL models, deadline/state constraints, due-hold index, READ COMMITTED engine,
  per-event serialization, and database-clock helper.
- `backend/src/csrs/reservations/transitions.py::expire_due_holds`: it updates due HELD rows,
  decrements by rows actually changed, and never starts/commits a transaction or acquires a lock.
- Existing real PostgreSQL fixtures, observed-lock helpers, invariant SQL, fault tests, and
  strengthened post-lock clock test. Preserve all 417 existing cases as regression coverage.

Do not call the user command service with invented cookies or retry keys from the worker.
The worker is an internal database maintenance process, not a user HTTP command; it needs no
session, CSRF, or user idempotency record. It reuses the same locked state transition.

### Worker and recovery requirements

1. Add a standalone polling process using the backend image, initially one worker. The existing
   contract calls for approximately 15-second polls and bounded candidate-event batches.
   No worker entrypoint, worker configuration, or Compose service exists today; document the
   actual startup command/configuration when implemented. No Celery/broker or API scheduler.
2. Discover candidate event IDs from overdue persisted HELD rows without holding reservation
   locks. Discovery is advisory: candidates can become stale before processing. Do not filter
   out CLOSED events; closing does not cancel or release their existing holds.
3. For each event, open an independent READ COMMITTED transaction, SELECT the event FOR UPDATE
   with refreshed ORM state, then sample clock_timestamp. Only after the event lock may the
   worker call expire_due_holds and flush/commit row/counter changes atomically.
4. Keep one event per transaction and the event-before-reservation lock order. Never reuse a
   stale pre-lock allocation count or discovery-time clock. No independently committed counter
   update, reservation change, or nested transaction-owning user service is permitted.
5. Recheck the actual rows at execution time. Only due HELD rows expire. CONFIRMED and terminal
   rows do not release again; duplicate discovery, retries, and multiple discoverers are safe.
6. Recover by rediscovering durable database work after restart. A crash before commit rolls
   back both row/counter changes; after commit, rediscovery must cause no duplicate release.
   An uncertain commit can be retried through the same conditional transition.
7. Keep lock/database waits bounded, roll back failed transactions, and use a fresh transaction
   for subsequent work. Document retry/backoff and busy-event deferral policy, startup/shutdown,
   and failure reporting. A temporarily unavailable database must not create partial changes
   or an uncontrolled retry loop. Do not expose settings, credentials, cookies, or CSRF tokens.
8. Worker downtime may delay persisted cleanup but must not weaken request-time expiration,
   permit expired confirmation, block request reclamation, or change GETs into domain writes.
   Preserve durable request outcomes and existing API/security/state contracts.

### Required Phase 5 acceptance criteria

- [ ] A real standalone worker expires due holds on an unvisited event without an HTTP trigger.
- [ ] Downtime leaves conservative stored holds; restarting drains the backlog correctly.
- [ ] Repeated sweeps and stale candidates do not double-release, including a candidate confirmed
  or cancelled before the worker obtains the event lock; CLOSED-event due holds are reclaimed.
- [ ] Independent PostgreSQL transactions/processes cover duplicate discoverers and worker races
  with confirmation, cancellation, admission, and capacity edits in both relevant lock orders.
- [ ] Post-lock clock sampling and exact deadline equality are tested; confirmed rows never expire.
- [ ] Fault injection before commit rolls back all changes; after-commit retry is a no-op, and
  real timeout/database-recovery tests verify bounded failure and continued progress.
- [ ] Consistent SQL snapshots retain counter bounds/equality and active-user uniqueness after
  every recovery/race scenario. Arbitrary sleeps or mocked locks do not establish correctness.
- [ ] The complete existing suite plus new worker tests actually run against PostgreSQL. Report
  actual counts, commands, process/pool settings, failures, and limitations; no invented metrics.
- [ ] Relevant lint/format, migrations/contracts if affected, Compose worker startup/shutdown,
  and retained backend/frontend smoke/regression checks pass.
- [ ] Add `docs/phase-5-validation.md` and `docs/phase-explanations/phase-5-explanation.md` with
  the established twelve-section structure and a clear Phase 6-8 boundary.
- [ ] Stop for review before Phase 5 commit/push. This documentation publication authorizes
  neither Phase 5 implementation nor future application commits.

### Remaining roadmap and dependencies

| Phase | Planned delivery | Depends on / evidence gate |
| --- | --- | --- |
| 5 (next) | Expiration & Recovery: standalone expiry sweeper and recovery | Phase 4 shared locked transitions; backlog drains after restart, duplicate/stale sweeps do not double-release, timeout behavior |
| 6 | Redis rate limiting and short-lived public metadata cache | Correct PostgreSQL protocol first; atomic/multi-process quotas and explicit outage policy; capacity independent of cache; availability not cached |
| 7 | Booking/organizer browser UI | Stable auth/event/reservation APIs; account flows, accessible errors, current-state refresh, retain retry keys on uncertain requests |
| 8 | Full concurrency/failure evidence, deployment, backup/restore | Earlier gates complete; reproducible mixed load/multiple processes, persistent DB, restore exercise, accurate resume claims |

The reviewed future hosting direction is a Docker web service with persistent managed
PostgreSQL and suitable Redis/worker infrastructure. It is not deployed or purchased. Retain
the simple monolith; do not introduce new infrastructure or paid services without authorization.
Email verification/recovery/MFA, payments, quantities/seat maps, and event-wide cancellation
are not delivered features. Session cleanup remains a manual bounded admin command.

## J. Running and checking this repository

Commands are from the repository root unless stated otherwise. They were checked against
README, Compose/Dockerfile configuration, package scripts, CI, and prior validation evidence.
The final Phase 4 run recorded 417 passing tests (114 unit/contract, 303 PostgreSQL); those are
historical implementation results. This documentation-only update validates Markdown, local
references, scope, and sensitive-information hygiene; it does not claim a new local suite run.
Use Docker Desktop with Linux containers and Compose supporting --wait. Keep existing volumes.

### Start local development

In PowerShell, copy the example **only if .env does not already exist**; never overwrite local
credentials simply to follow setup instructions:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 120
docker compose exec -T backend python -m alembic upgrade head
docker compose exec -T backend python -m alembic check
docker compose ps
```

The backend needs migrations even if readiness passes. Settings have no implicit .env search;
Compose injects it and supplies service-name connection URLs. Host Uvicorn instructions in
README use explicit --env-file .env. Never send database settings through `VITE_*` variables.
Ports bind to 127.0.0.1: frontend 5173, API 8000, PostgreSQL 5432, Redis 6379; test PG is 5433.
Development PG uses postgres_data, tests use separate temporary storage. Frontend has no
Docker health probe: verify HTTP, not just Compose's generic running/healthy wording.

### Backend tests and quality checks

Full suite, including real PostgreSQL and migration tests:

```powershell
docker compose --profile test run --build --rm backend-test
```

Integration-only and unit/contract-only alternatives use the same image and its backend
working directory. Build after source changes; there is no test-image source bind mount:

```powershell
docker compose --profile test run --build --rm backend-test python -m pytest tests/integration -p no:cacheprovider
docker compose --profile test run --build --rm backend-test python -m pytest tests/unit -p no:cacheprovider
docker compose exec -T backend python -m ruff check --no-cache .
docker compose exec -T backend python -m ruff format --check --no-cache .
docker compose exec -T backend python -m pip check
```

The dedicated test role needs CREATEDB. Its provided database must use postgresql+psycopg
and end in _test. Fixtures create `csrs_phase2_<uuid>_test` databases, migrate/reset only those,
and remove them. That historical prefix is still used through Phase 4. Never truncate the configured
input database or point tests at development data. A missing test URL can skip local integration;
required CI/full Docker verification must actually run them. A configured unreachable DB fails.
Host TestClient runs previously stalled on this Windows environment; container results are decisive.

### Migrations, frontend, HTTP, and contract checks

```powershell
docker compose exec -T backend python -m alembic heads
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
docker compose exec -T frontend npm run typecheck
docker compose exec -T frontend npm run build
docker compose exec -T redis redis-cli ping
```

Head/current should be 0001_foundation until a necessary new revision exists; check reports
no new operations when schema/models match. Never downgrade development data for a test.
Frontend build already includes typecheck; there is no frontend unit-test/ESLint framework.
Redis PONG is service health, not proof of an application Redis integration.

- UI: [http://localhost:5173/](http://localhost:5173/), currently health only.
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs).
- Runtime schema: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json).
- Liveness: [health/live](http://localhost:8000/api/v1/health/live).
- Readiness: [health/ready](http://localhost:8000/api/v1/health/ready).
- Proxy readiness: [frontend health/ready](http://localhost:5173/api/v1/health/ready).

Use a cookie-aware API client with CSRF bootstrap and trusted Origin for mutations; the UI
has no business forms. To provision an organizer, replace EMAIL with an existing registered
account; no password/token is embedded in these commands:

```text
docker compose exec -T backend python -m csrs.cli promote-organizer EMAIL
docker compose exec -T backend python -m csrs.cli purge-sessions --batch-size 1000
```

Promotion revokes sessions; log in again. Cleanup is security-session maintenance, not holds.

After intentionally changing API routes/models, use the existing **host** Python environment
described in README to export contracts, then run the contract tests/full suite:

```powershell
.\.venv\Scripts\python.exe backend/scripts/export_health_contract.py
```

This writes both `docs/contracts/api.openapi.yaml` and `docs/contracts/health.openapi.yaml`.
Review changes; the health-only paths/schemas must remain compatible. The development docs
mount is read-only inside the backend, so do not assume this exporter can write there from
an ordinary docker compose exec. Unit contract tests compare runtime against checked-in YAML.

### Stop safely and local tool notes

```powershell
docker compose --profile test stop
```

This stops ordinary/test-profile services without removing containers or volumes. The README
also documents docker compose down for ordinary service teardown without volume deletion.
Do not copy CI's --volumes cleanup into local development: that workflow runs on disposable
runner data. Changing initialization credentials does not update an existing PostgreSQL volume.

On this Windows machine Docker's executable is at
`C:\Users\ASUS\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`.
If the current terminal cannot find docker or docker-credential-desktop, add that directory
to the command's PATH. Do not extract/print credentials. Restricted executor access to Docker's
named pipe may require tool escalation; it does not justify replacing PostgreSQL with SQLite.
Ignored local verification helpers/caches are not guaranteed in a fresh clone or part of the
reproducible project. No secret or generated artifact should be committed.

## K. Git, CI, and current verification status

| Item | Verified snapshot |
| --- | --- |
| Repository | [CSRS on GitHub](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System) |
| Branch | main |
| Latest verified implementation commit | 50cca058987a72adf4ac575b28cdbdc4840ca685 |
| Commit message | feat: implement concurrency-safe reservations |
| Phase 4 change manifest | 32 files: 11 added, 21 modified; 3,492 insertions, 353 deletions |
| Latest full local tests | 417 passed in 58.53s, exit 0, no failures/skips; 114 unit/contract + 303 PostgreSQL |
| Final audit follow-up | One MEDIUM test-coverage finding resolved; strengthened clock test passed 10/10 repetitions and rejected an in-memory now() mutation |
| Other Phase 4 checks | Ruff/51 formatted files, dependencies, migrations, TypeScript/build, Compose, contract equality, 33 proxy smoke and six localhost checks passed; see Phase 4 report for check provenance |
| Implemented API | Version 0.4.0; 20 paths, 22 operations; reservations and availability included, organizer dashboard absent |
| Git before this documentation update | Clean; local HEAD, origin/main, and live remote main matched the Phase 4 commit |
| GitHub Actions for Phase 4 implementation | Foundation CI completed/success; backend, frontend, compose all green |
| Next application phase | Phase 5 - Expiration & Recovery; requirements in I, not started |
| Documentation change | Only docs/PROJECT_HANDOFF.md; authorized separate documentation commit after this implementation snapshot |

The [Phase 4 Foundation CI run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40235993807)
was queried again for exact SHA `50cca058987a72adf4ac575b28cdbdc4840ca685` on 2026-10-26:
**completed/success**.
Jobs backend, frontend, and compose all completed successfully. The workflow is
`.github/workflows/ci.yml`, triggered on push/PR. It runs real PostgreSQL tests, frontend build,
Docker builds, migrations, and health/proxy smoke. It performs no production deployment.

Updating this file changes only the existing handoff document before its authorized
documentation commit, `docs: update project handoff after phase 4`. A fresh conversation must
inspect Git and current CI again: repository HEAD after that commit will differ from the
**Phase 4 implementation** SHA above. The green run cited here belongs to the implementation;
the new documentation commit's hash, remote equality, working-tree state, and separate CI
result are reported in this task's final response. Do not attribute a green run to another SHA.

No known Phase 4 correctness blocker or unresolved audit finding remains. Current limitations:
quiet events retain overdue persisted holds until request cleanup or the planned sweeper;
idempotency records have no retention cleanup; hot-event writes serialize; and commit-loss
tests use controlled simulation. There is no worker, Redis integration, organizer dashboard,
business UI, scheduled session cleanup, account recovery/verification/MFA, or cloud deployment.
Readiness proves connectivity, not migration currency. XSS can defeat CSRF; deployment hardening
is future work. Tested reservation correctness is established for the documented scenarios;
no production throughput, latency, or Phase 8 mixed-load claim is made.

## L. Development workflow for the next conversation

Preserve the user's review gate exactly:

1. Implement one authorized phase within this repository and its documented scope.
2. Run tests and verify actual behavior, including real PostgreSQL for integration/concurrency.
3. Provide a detailed implementation report: files, API/state/security/transactions, commands,
   counts/exit statuses, migration evidence, limitations, and Git status.
4. **Stop before committing or pushing.** A phase implementation request is not commit approval.
5. Have ChatGPT review the report with the user and wait for explicit approval.
6. Fix reported issues, rerun affected checks, and report the reviewed final result.
7. Commit/push only after authorization; stage only intended files, never secrets/generated data.
8. Verify local/remote hashes, clean working tree, and **green GitHub Actions** for that commit.
   If pending/unavailable, link the run and say so; do not claim green.
9. Proceed to the next phase only after that gate and the user's authorization.

Do not rewrite unrelated working code, create unnecessary migrations/services, silently
weaken tests, force-push, overwrite remote history, or delete local PostgreSQL volumes.
If a tool/dependency/check is unavailable, report the actual blocker rather than inventing
success. The approval to publish this handoff is not approval to implement or commit Phase 5.

## M. Documentation conventions and reading order

For every phase maintain these separate files:

| Document convention | Contents |
| --- | --- |
| `docs/phase-X-validation.md` | Actual scope/changed-file manifest, endpoints/security/transactions, commands/environment, test counts and exit statuses, migrations, HTTP/CI evidence, limitations, deferred work, acceptance and Git state at that review |
| `docs/phase-explanations/phase-X-explanation.md` | Beginner-friendly WHAT/HOW/WHY, technologies, flows/diagrams/examples, accurate paths/APIs/schema, security/correctness, test meaning, deferred work, interview Q&A/tradeoffs, simple summary |

The explanations use twelve numbered sections: phase overview; what we implemented;
technologies used; how everything works; important files/folders; API endpoints; database
design; security/correctness; testing/verification; not implemented yet; interview preparation;
phase summary (5-8 simple sentences). Define terms and distinguish planned from implemented.

Preserve earlier phase evidence and explanations as historical records. Reference them rather
than duplicating entire reports or altering old counts. Update architecture/API/security/state
contracts only where actual new behavior requires it; export/test OpenAPI intentionally.
No real credentials, cookie/CSRF values, database dumps, or fabricated performance claims.

Recommended next-conversation reading order:

1. This handoff, especially implemented protocol H, next-phase requirements I, and workflow L;
   then Git status/log and the current CI result.
2. [Concurrency protocol](concurrency.md), [API contract](contracts/api.md),
   [database design](database.md), [security](security.md), and [decisions](decisions.md).
3. [Phase 4 validation](phase-4-validation.md), especially its final audit-follow-up section,
   and [Phase 4 explanation](phase-explanations/phase-4-explanation.md), plus earlier phase reports
   linked in D when their historical detail is needed.
4. Actual reservation service/shared expiration helper, event/auth transaction ownership,
   models, route/HTTP guards, PostgreSQL fixtures, reservation/event race and fault tests, and
   strengthened clock test listed in C. Plan the worker from that existing implementation.
5. [README](../README.md), [Compose](../compose.yaml), and
   [CI workflow](../.github/workflows/ci.yml) before running the environment.

The next implementation is **Phase 5 - Expiration & Recovery**, after a new explicit request.
This documentation-only update implements no application functionality and does not remove
the requirement to stop for review before any future phase's commit/push.
