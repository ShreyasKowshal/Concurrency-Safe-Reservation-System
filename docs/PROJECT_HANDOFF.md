# CSRS project handoff: continue with Phase 7

**Snapshot, 2026-10-26:** Phases 1-6 are implemented, reviewed, committed, and pushed to main.
Phase 6 implementation commit `7d7c705b438437a2a63ccd7d9fbffe4d54628f17` was followed
by the CI readiness correction `d188a7e6279818a8e702bbd682fcd97765a8cd34`. The
[corrected exact-commit GitHub Actions run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40349763474)
is **green**: backend, frontend, and Compose passed, including Redis available, outage, and
recovery smoke. The final Phase 6 source suite passed **540 tests: 153 unit/contract and 387
real PostgreSQL/Redis integration**, including 66 new Phase 6 tests.
**Phase 7 - Full Frontend - is
next and has not started.** This documentation-only update prepares that phase.

Repository: [Concurrency-Safe-Reservation-System](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System).
Local workspace: `C:\Users\ASUS\OneDrive\Desktop\csrs`.

Before editing in a new conversation, read this document, inspect Git status, and read the
current source and contracts. This is a snapshot, not a replacement for the implementation.
Some older reports and explanations retain pre-commit "pending review" wording. Those are
historical review records; they do not mean approved Phases 2-6 must be implemented again.
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
detail/history, durable idempotency, request-time expiration, and an independently running
PostgreSQL expiration worker, atomic Redis quotas, and public event-detail metadata caching.
**Organizer reservation dashboard, business UI, and production deployment remain planned.**
The 50/100-attempt tests establish their
documented correctness cases; they
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
| Alembic | Explicit schema migrations; head 0002_worker_expiry adds an ordered partial expiration index |
| Redis 7.4, redis-py 8.1 | Ephemeral, shared API rate limits and public detail metadata cache; never a reservation, session, or idempotency authority |
| argon2-cffi, email-validator | Argon2id passwords and canonical validated ASCII email addresses |
| Database-backed opaque sessions | Random cookie secrets, server-side expiry/revocation, independent synchronizer CSRF tokens; no JWT/OAuth |
| Pytest, FastAPI TestClient, HTTPX2 | Unit/contract tests, real PostgreSQL integration, controlled concurrency/failure tests |
| Ruff | Backend lint and format checks |
| Docker / Docker Compose | Local development, disposable PostgreSQL/Redis test services, and opt-in worker profile |
| GitHub Actions | CI on pushes/PRs: backend, frontend, Compose, worker and Redis outage/recovery smoke; no production deployment |

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

For an existing-event mutation, the current flow is: validate HTTP input; check session,
CSRF, and role in a short SQL preflight; end that transaction; check the Redis user quota;
then begin the original service transaction. The service revalidates authorization, locks
the owned event, and rechecks after any wait. Reservation commands first claim a user-scoped
idempotency key, then lock the event, refresh authorization, sample database time, clean due
holds, and commit the transition/counter/outcome together. A flush sends SQL; it does not
commit. Redis work stays outside the event lock and does not authorize or complete a command.

See the existing [architecture and five diagrams](architecture.md), especially the system,
application, reservation transaction, and worker lifecycle diagrams. Their labels distinguish
implemented Phase 1-6 services from planned business UI.
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
| `backend/src/csrs/api/redis_dependencies.py` | Route-level Redis support/quota dependencies |
| `backend/src/csrs/redis_support.py` | Atomic fixed-window quotas, validated metadata cache, failure policy, structured support logs |
| `backend/src/csrs/redis_connection.py` | Bounded Redis DNS/TCP caller waits and connection behavior |
| `backend/src/csrs/auth/` | Crypto, schemas, HTTP guards, service transactions, dependencies, admin commands |
| `backend/src/csrs/events/` | Event schemas, transaction services, errors, scoped pagination |
| `backend/src/csrs/reservations/service.py` | Durable claim/replay, event-locked reservation transactions, supporting reads |
| `backend/src/csrs/reservations/transitions.py` | Shared expire_due_holds helper; caller owns event lock/transaction |
| `backend/src/csrs/reservations/schemas.py` | UTC reservation/page/availability response DTOs |
| `backend/src/csrs/worker.py` | Independent expiry CLI, bounded discovery, event transactions, signals, pacing/retries, structured logs |
| `backend/src/csrs/cli.py` | Explicit local promotion/session-cleanup entrypoint |
| `backend/migrations/env.py` | Alembic metadata and supplied isolated test-connection support |
| `backend/migrations/versions/0001_foundation_foundation_schema_and_sessions.py` | Explicit initial schema upgrade/downgrade |
| `backend/migrations/versions/0002_worker_expiry_bounded_event_cleanup.py` | Partial ordered event-expiration index |
| `backend/scripts/export_health_contract.py` | Intentionally refreshes complete and health OpenAPI snapshots |
| `backend/scripts/smoke_reservations.py` | Local live HTTP verification with generated records and scoped cleanup |
| `backend/scripts/smoke_worker.py` | Local backlog, worker restart, and live API smoke verification |
| `backend/scripts/smoke_redis.py` | Local available/outage/recovery API and worker smoke verification |
| `backend/tests/unit/` | Config, health, crypto, event input/cursor, runtime-contract checks |
| `backend/tests/integration/` | Real PostgreSQL auth, events, schema, migrations, and concurrency/failure cases |
| `backend/tests/integration/test_reservations.py` | Reservation HTTP/state/deadline behavior and SQL invariants |
| `backend/tests/integration/test_reservation_transactions.py` | Two-process contention, controlled lock waits, strengthened clock test, faults |
| `backend/tests/integration/test_worker.py` | Real PostgreSQL sweeps, bounds, races, recovery, and invariant checks |
| `backend/tests/integration/test_worker_processes.py` | Independent worker process contention, crash, outage, shutdown/restart tests |
| `backend/tests/unit/test_redis_runtime.py`, `backend/tests/integration/test_redis_support.py` | Redis lifecycle, real PostgreSQL/Redis, API-process, cache, and outage checks |
| `frontend/src/App.tsx` | Health screen; latest change is Phase 4 label |
| `frontend/src/api/health.ts` | Validated readiness fetch and frontend error classification |
| `frontend/vite.config.ts` | Origin-preserving /api proxy |
| `compose.yaml`, `backend/Dockerfile`, `frontend/Dockerfile` | Development/test containers, opt-in worker, ports, volumes, startup |
| `.github/workflows/ci.yml` | Backend/PostgreSQL/Redis, frontend, Compose, worker and Redis smoke CI |
| `.github/dependabot.yml` | Dependency-update proposals; does not automatically merge changes |

The worker reuses the Phase 4 expiration transition under the same event-first lock protocol.
It runs as `python -m csrs.worker` or the opt-in Compose `worker` service and does not use Redis.
The API owns one lazy Redis pool per lifespan for quotas and public detail metadata only.

## D. Completed phases and their evidence

Counts below are historical final results, not fresh executions for this handoff. Each later
suite retains earlier behaviors; counts must not be added together as independent totals.

| Phase | Completed scope | Final recorded tests | Source |
| --- | --- | --- | --- |
| 1 | Monorepo, configuration, health backend/UI, Compose, Alembic scaffolding, CI, contracts | 24 passed: 22 unit/contract + 2 real PostgreSQL; exit 0 | [Validation](phase-1-validation.md), [explanation](phase-explanations/phase-1-explanation.md) |
| 2 | Five tables, initial migration, sessions/auth/CSRF/roles/admin CLI | 170 passed: 54 unit/contract + 116 PostgreSQL; exit 0 | [Validation](phase-2-validation.md), [explanation](phase-explanations/phase-2-explanation.md) |
| 3 | Public/owner event reads, draft create/edit/capacity/publish/close, event locks | 323 passed: 107 unit/contract + 216 PostgreSQL; exit 0 | [Validation](phase-3-validation.md), [explanation](phase-explanations/phase-3-explanation.md) |
| 4 | Holds, confirmation/cancellation, request-time expiry, durable idempotency, private history/detail, public availability | 417 passed: 114 unit/contract + 303 PostgreSQL; exit 0 | [Validation](phase-4-validation.md), [explanation](phase-explanations/phase-4-explanation.md) |
| 5 | Independent PostgreSQL expiry worker, bounded backlog catch-up, multi-worker/restart recovery, ordered index | 474 passed: 130 unit/contract + 344 PostgreSQL; exit 0 | [Validation](phase-5-validation.md), [explanation](phase-explanations/phase-5-explanation.md) |
| 6 | Atomic multi-process Redis quotas, public detail cache, outage policies, bounded connection behavior | 540 passed: 153 unit/contract + 387 PostgreSQL/Redis integration; exit 0 | [Validation](phase-6-validation.md), [explanation](phase-explanations/phase-6-explanation.md) |

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
auth screens and scheduled maintenance remain absent today; rate limiting arrived in Phase 6.
The implementation
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

### Phase 5: expiration and recovery

Added the standalone PostgreSQL worker (`python -m csrs.worker`) and opt-in Compose worker
profile. It discovers bounded overdue HELD candidate pages without reservation locks, then
uses an independent READ COMMITTED transaction for each event. It locks that event with
`FOR UPDATE SKIP LOCKED`, refreshes state, samples `clock_timestamp()` after the lock,
and calls the shared expiration transition. Only rows actually changed from HELD to EXPIRED
release seats; reservation updates and the event counter commit together. Duplicate workers
can discover the same candidate but safely defer a locked event or recheck committed state.

Keyset scanning with a fixed pass cutoff, per-event row limits, and short interruptible
catch-up waits drain backlogs without an arbitrary full idle poll between productive batches.
The default idle poll is 15 seconds; productive catch-up is capped at 0.25 seconds, and
scan-ahead over a full busy/stale page at one second. Completed unproductive passes use the
normal poll interval. This advances past busy events and wraps for equal-deadline groups;
it is not an expiration-latency SLA. Failed work rolls back and uses bounded backoff.
Stopping/restarting loses no durable work: PostgreSQL rediscovers overdue rows, a crash before
commit rolls back, and processing after commit is a conditional no-op. The worker has no
HTTP listener, user idempotency claim, Redis call, or process-local work queue.

Revision `0002_worker_expiry` adds only the partial index
`ix_reservations_event_held_expiry` on `(event_id, hold_expires_at, id)` for HELD rows. The
existing global expiry index remains. No application table, column, reservation state,
counter, endpoint, or response contract changed; API version remains 0.4.0.

Final local verification: **474 passed in 94.13s**, exit 0, no failures/skips: 130
unit/contract and 344 real PostgreSQL integration cases. A dedicated integration run passed
344/344. Real process and database tests cover duplicate workers, event-lock deferral,
confirmation/cancellation/capacity/request-cleanup races, exact deadlines, interruption,
restart/backlog, database outage, and SQL reconciliation. Ruff, Alembic head/current/drift,
API contract, frontend checks/build, Compose, live worker/API smoke, and invariant checks
passed as recorded in [Phase 5 validation](phase-5-validation.md).

The final correctness audit found zero BLOCKER/HIGH issues. Its MEDIUM slow-backlog finding
was resolved with bounded productive catch-up and busy-page scan-ahead. Its LOW process-test
finding was resolved with two independent workers: the first holds the event lock, while the
second demonstrably defers it before release; eventual expiration/counter equality is checked.
Catch-up and contention checks passed in three fresh executions each, and the full suite
retained Phase 1-4 coverage. The explanations and evidence are in the Phase 5 links above.

Implementation commit `03ea3108999f051887e6788e26ed9342e08a7e1b` changed 24 files:
8 added and 16 modified. It was pushed to `origin/main` with matching local/remote hashes
and a clean working tree. The exact-commit
[GitHub Actions run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40293310608)
completed successfully; backend, frontend, and Compose jobs passed, including worker smoke.
These are Phase 5 implementation results, not fresh executions for this handoff edit.

### Phase 6: Redis integration

Implemented atomic fixed-window quotas shared across API processes and a short-lived cache
for **public event detail metadata only**. PostgreSQL still owns sessions, authorization,
reservation state, capacity, deadlines, idempotency, and expiry recovery. Redis holds no seat
counter, reservation transition, private reservation, CSRF secret, or durable business outcome.
There was no PostgreSQL schema or migration change; Alembic head remains `0002_worker_expiry`.
API/package version remains 0.4.0 with 20 paths and 22 operations. Intentional OpenAPI changes
document 429 and public detail caching.

The self-audit found zero BLOCKER/HIGH issues. Its MEDIUM unbounded OS DNS caller wait was
resolved with one shared pending lookup per API client and bounded caller waits. Three LOW
findings were resolved: requiring a cache schema version, disposing the SQL engine even if
Redis cleanup fails, and preserving valid SQL detail output beyond cache input limits.
Focused real Redis/PostgreSQL, fault, and repeated race tests cover those fixes. The full
Phase 6 suite passed **540/540**: 153 unit/contract and 387 integration, including 43 new
real Redis/PostgreSQL integration cases and 23 new unit cases. See
[Phase 6 validation](phase-6-validation.md) and
[explanation](phase-explanations/phase-6-explanation.md) for test commands and limits.

Implementation commit `7d7c705b438437a2a63ccd7d9fbffe4d54628f17` changed 32 files:
8 added and 24 modified. Its first CI run exposed a startup-probe race after backend
recreation: curl exited on a transient empty reply before it could retry. The one-file
correction `d188a7e6279818a8e702bbd682fcd97765a8cd34` adds bounded retries for those
errors while still requiring a real 200 response, plus Compose/backend diagnostics on failure.
The [corrected Foundation CI run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40349763474)
completed successfully for the correction SHA: backend, frontend, and Compose passed. Hosted
Compose reported **540 passed**, worker backlog/restart smoke, and three Redis modes:
available, outage, recovered. Each mode reported 13 HTTP checks, one worker expiration, and
zero invariant mismatches. The Phase 6 application source was unchanged by the CI correction.

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
the user/key idempotency constraint. Phase 5 adds a partial HELD
`(event_id,hold_expires_at,id)` index for bounded cleanup of one locked event. See actual names
in `backend/src/csrs/models.py`.

### Migrations and transactions

Alembic head is **0002_worker_expiry**, after `0001_foundation`. Phases 3-4 changed no schema;
Phase 5 added the index above and no table/column. Migrations are explicit admin steps, not
startup create_all or an automatic task in API/worker processes. Preserve current migrations;
add a revision only for a necessary reviewed schema change. Downgrade is tested only against
generated disposable databases; do not downgrade development data.

READ COMMITTED, explicit service transactions, and `SELECT ... FOR UPDATE` are established.
User commands claim idempotency, lock the event, then lock/update reservation rows. Worker
transactions need no user key and lock the event before reservation updates, skipping busy
events. Both sample database time after that lock. Never commit row/counter/idempotency pieces
independently or use a nested service's independent commit.

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

All six operations above are implemented. Phase 5 added no HTTP operation. The organizer dashboard
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
   The Phase 6 Redis quota check runs after a short SQL auth/CSRF/role preflight and outside
   the capacity transaction. The original service repeats authorization inside its transaction.
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
the event and reread the reservation and ownership. Never reverse this ordering. Current
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
- Authentication, CSRF, ownership, and Phase 6 throttling apply before replay. Idempotency is
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
Phase 6 implements 429/RATE_LIMITED with `Retry-After` when a quota is exceeded. A required
Redis limiter outage produces a controlled 503; optional quota failures continue through SQL.

### H6. Request-time expiration and Phase 5 worker

Phase 4 reclaims due holds for the locked event before admission and uses the shared cleanup
in capacity edits. It rejects expired confirmations at the boundary even when no worker runs.
Cleanup decrements only rows actually transitioned. Cancellation of an overdue
hold results in EXPIRED, not a second release or an invented CANCELLED transition.

Useful cleanup may coexist with a business failure. Confirming an expired hold must commit
expiration/counter change **and the stored 409 response**. Throwing a rollback-triggering HTTP
exception inside the transaction would undo both; construct/return the outcome after commit.
Faults before commit must roll back reservation, counter, and idempotency together.

Phase 5 adds a standalone polling process using the same shared transition. It discovers
bounded candidate pages without locking reservation rows, locks one event per transaction
with `FOR UPDATE SKIP LOCKED`, refreshes state, samples post-lock database time, and commits
conditional row/counter changes atomically. Other workers defer a busy event. Productive
passes use bounded catch-up waits; idle passes use the configured normal interval. No Celery,
per-hold timer, or in-process API scheduler is required. Worker lag/outage may delay stored
cleanup, but cannot permit an expired confirmation or prevent an active request from
reclaiming due capacity. Restart, duplicate sweeps, stale candidates, and worker/API races
are covered by the Phase 5 tests described in D. Unvisited events may retain conservative
stored HELD rows until request cleanup or the worker runs.

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
connection-cut experiment. Worker restart/stale sweep/duplicate sweep recovery was added in
Phase 5. Phase 6 separately tests Redis quotas/cache, independent API processes, SQL
invariants during outage, and live stop/restart/recovery without weakening these races.

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
  changed-file manifest, and the then-deferred Phase 5-8 work.
- [x] Independent audit completed; the MEDIUM clock-test finding resolved and mutation-checked.
- [x] User approved publication; implementation committed/pushed with matching hashes and green CI.
- [x] At Phase 4 completion, the worker and later phases remained deferred. The worker was
  delivered in Phase 5 and Redis support in Phase 6. Full UI and deployment remain planned;
  payments are outside the current roadmap.

### H8. Implemented Phase 6 Redis support

The API constructs one lazy redis-py pool per lifespan; startup and PostgreSQL readiness do
not require a Redis connection. A Lua operation atomically checks/increments each fixed
window across API processes. The window starts on its first accepted request; rejection does
not extend it. Quota identity uses the connection peer or the current authenticated user,
hashed in namespaced keys. Forwarded identity headers are ignored; supported Uvicorn commands
disable proxy-header trust. Shared proxies/NAT share a peer quota until a separately reviewed
trusted-proxy deployment design exists.

| Scope | Default per 60 seconds | Identity | Redis unavailable |
| --- | --- | --- | --- |
| New anonymous session bootstrap | 30 | Connection peer | Controlled 503, Retry-After: 1; no new row |
| Login/register combined | 10 | Connection peer | Controlled 503, Retry-After: 1 |
| Public event list/detail/availability combined | 120 | Connection peer | Continue through PostgreSQL |
| Hold/confirm/cancel/replay and organizer mutations combined | 60 | Authenticated user | Continue through original PostgreSQL transaction |

A real quota exceedance returns 429 `RATE_LIMITED` with a rounded-up positive `Retry-After`.
Valid existing CSRF-token retrieval, logout, health, current-user/private reservation/history,
and organizer reads are unthrottled. A required auth quota failure never creates a new
anonymous session. Mutation routes finish a short SQL auth/CSRF/role preflight before Redis;
the original business transaction rechecks those guards after any waits. Quota rejection is
not stored as an idempotent booking outcome. Redis calls never hold an event-row lock.

Only `GET /api/v1/events/{event_id}` may use the metadata cache. It stores a versioned,
validated public DTO under a namespace/environment/event key for at most 15 seconds by
default. Every hit first checks the event's current PUBLISHED visibility in PostgreSQL;
draft, closed, and missing events remain unavailable. A miss or malformed/wrong-version/
oversized entry loads SQL detail. Public lists and availability always use SQL, and the
cache never includes live allocations, private state, or durable command outcomes.
Edit/capacity/publish/close invalidation runs after commit. An older in-flight fill or
failed invalidation can leave public metadata stale until its original absolute expiry;
neither can authorize a reservation. Hits do not renew TTL, and late fills are skipped.

Defaults: cache enabled with TTL 15 seconds (range 1-60); rate limits enabled with a
60-second window (range 1-3600); combined DNS/TCP caller budget 0.2 seconds and socket
timeout 0.2 seconds (each range 0.05-2); pool maximum 10 (range 1-40), no automatic
Redis command retries. One pending OS DNS lookup is shared by an API client; callers and
shutdown remain bounded even if that lookup itself cannot be cancelled. Redis restart
discards ephemeral quotas/cache. See [Phase 6 validation](phase-6-validation.md) and
[security](security.md) for exact settings and failure policies.

## I. Next phase: Phase 7 - Full Frontend

**Planned only; no Phase 7 implementation has started.** The current React/TypeScript/Vite
frontend displays PostgreSQL/API health and a retry button. It has no account, event, booking,
or organizer screens, router, business API client, or frontend test framework. Build the
browser experience on the already implemented API, and keep PostgreSQL as the sole booking
authority. The existing backend contract is 20 paths / 22 operations at version 0.4.0.

### Dependencies, screen scope, and API gaps

- Read [phase gates](phases.md), [API contract](contracts/api.md), its
  [OpenAPI snapshot](contracts/api.openapi.yaml), [security](security.md),
  [concurrency](concurrency.md), and Phase 4-6 validation before implementation. Preserve
  the current Vite origin-preserving `/api` proxy, React 19, TypeScript 5.9, and Node 24.
  Add routing, state, or test dependencies only when their need is demonstrated.
- Provide public event discovery with keyset pagination, published event details, and
  advisory availability. List/detail may show fully booked or past-deadline published
  events; only the server can decide whether a new hold is allowed. Closed/draft events
  must not appear in public discovery. Refresh current detail/availability after actions.
- Provide registration, login, logout, current-session restore, and role-aware navigation.
  Registration returns a user and a fresh anonymous CSRF token; it does not log the user
  in. Organizer status comes from `/auth/me`, never from client input.
- Provide attendee hold, confirmation, cancellation, private reservation detail/history,
  and clear status, deadline, and server-time displays. A browser countdown is advisory:
  `decision_time < hold_expires_at` is enforced by PostgreSQL, and equality is expired.
  A 200 response may arrive after a visible countdown reaches zero. Refresh the private
  resource after replay or uncertain results; never infer a committed transition from a
  timer or a cached public detail response.
- Provide organizer own-event list/detail, draft creation/edit, publish, close, and separate
  capacity edits within actual Phase 3 rules. Published start/deadline are immutable;
  CLOSED is read-only, and closing does not cancel otherwise valid holds. Allocation and
  ownership are server fields. A reservation dashboard for an organizer needs the
  **planned but unregistered** `GET /api/v1/organizer/events/{event_id}/dashboard`
  endpoint, owner-scoped pagination, and count semantics reviewed in the API contract.
  Implement and review that minimal backend contract before building the dashboard;
  attendee history cannot substitute for organizer bookings. Preserve booking authority
  and lock order.
- The reservation DTO contains `event_id` but no embedded event title/start. Public
  detail is 404 after closure, even for a reservation owner. Plan a safe event-ID /
  unavailable-metadata fallback or explicitly review a minimal enrichment contract; do
  not use another organizer's private event route to fill that gap.

### Browser correctness and failure handling

Use cookie credentials on same-origin requests and fetch the synchronizer CSRF token before
mutations. Keep token and pending private state in memory; do not put session cookies, CSRF
values, passwords, or idempotency keys in localStorage, URLs, logs, or telemetry. Respect
trusted Origin checks. Clear private state and abort/ignore stale responses on logout,
session loss, or account change so one user's data cannot appear in another's view.

Hold/confirm/cancel require a distinct `Idempotency-Key` for each new intent. Retain the
same key, method, path, and body while retrying an uncertain outcome, including network loss
after commit; do not mint a new key automatically. A replay can return an earlier response,
so fetch current state afterward. After a page reload loses an in-memory pending intent,
reconcile private detail/history before a new action. Organizer mutations do not have
reservation idempotency semantics; handle uncertain responses by rereading owner state.

Show explicit loading, empty, validation, conflict, retry, and unavailable states. Handle
401 session loss, 403 role/CSRF, 404 inaccessible resources, 409 business/idempotency
conflicts, 415 media type, 422 field errors, 429 `RATE_LIMITED` with `Retry-After`,
503 transient PostgreSQL or required Redis failures, and network uncertainty. Never treat
fail-open Redis quota behavior as a successful booking. Keep accessibility and responsive
layout as functional requirements: keyboard navigation, visible focus, semantic labels,
associated field errors, live status messages, adequate contrast, and no color-only status.

### Phase 7 verification and acceptance criteria

- [ ] Public discovery/detail/availability, registration/login/logout/session restore,
  attendee reservation flows/history, organizer event management, and an owner-only
  bookings dashboard work in the browser against actual API contracts. The dashboard's
  minimal backend endpoint, pagination, counts, and authorization have separate tests.
- [ ] CSRF/cookie and trusted-origin behavior is correct. Role and ownership checks remain
  server-enforced; logout/account changes cannot leak stale private UI data.
- [ ] A held countdown is advisory; exact deadline, confirmed-after-deadline replay,
  cancelled/expired terminal states, worker delay, and closed-event history are presented
  from current server responses without promising seats.
- [ ] Uncertain command retries retain the same idempotency key and reconcile after replay;
  new intents use new keys. Errors 401/403/404/409/415/422/429/503 and network loss have
  accessible recovery paths, including `Retry-After`.
- [ ] Responsive keyboard and screen-reader flows pass meaningful component tests and
  browser end-to-end checks. Add the smallest suitable frontend test tooling. Include real
  Compose PostgreSQL/Redis/worker journeys and deterministic timer/error cases; use separate
  transactions and observable synchronization for any backend race additions.
- [ ] Backend regression suite (currently 540), real PostgreSQL/Redis integration,
  contracts/OpenAPI, Ruff, Alembic head/drift, frontend typecheck/build, Compose, live
  worker/Redis smokes, and SQL counter/uniqueness reconciliation still pass. Report actual
  counts and any check that could not run.
- [ ] Update Phase 7 validation/explanation, architecture/contracts where behavior changes,
  review the final manifest and limitations, then stop for external review before any
  Phase 7 commit or push.

### Remaining roadmap and boundaries

| Phase | Delivery | Gate |
| --- | --- | --- |
| 5 (complete) | PostgreSQL expiration worker and recovery | 474-test historical suite, worker/race evidence, green CI |
| 6 (complete) | Redis quotas and public detail metadata cache | 540-test suite, multi-process/outage evidence, corrected green CI |
| 7 (next) | Full attendee and organizer browser UI | API/CSRF/retry correctness, accessibility, browser journeys, full regressions |
| 8 (planned) | Deployment, full mixed-load evidence, backup/restore | Earlier gates complete; reproducible load and durable-data recovery evidence |

Phase 8 hosting direction is a Docker web service with persistent managed PostgreSQL plus
appropriate Redis and worker infrastructure. Nothing is deployed or purchased. Keep the
monolith. Phase 7 excludes payments, quantities/seat maps, event-wide cancellation, Redis
inventory or locks, account recovery/verification/MFA, and production infrastructure.
Session cleanup remains a manual bounded admin command.

## J. Running and checking this repository

Commands are from the repository root unless stated otherwise. They were checked against
README, Compose/Dockerfile configuration, package scripts, CI, and prior validation evidence.
The final Phase 6 source run recorded 540 passing tests (153 unit/contract, 387 integration);
the corrected hosted Compose run also passed 540. These are implementation/CI results, not
new tests run for this documentation-only update. This update validates Markdown, local
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

The worker is opt-in and uses the same migrated PostgreSQL database. Start it separately
after the migration, inspect logs, and stop it without deleting volumes:

```powershell
docker compose --profile worker up --build -d worker
docker compose --profile worker logs --tail 20 worker
docker compose --profile worker stop worker
```

For a host installation with backend dependencies and explicit settings, run
`python -m csrs.worker --env-file .env` from the backend working directory. Defaults are
`CSRS_WORKER_POLL_INTERVAL_SECONDS=15`, `CSRS_WORKER_BATCH_SIZE=100`, retry initial 1 second,
and retry maximum 30 seconds; see [Phase 5 validation](phase-5-validation.md) for bounds,
catch-up behavior, restart/smoke commands, and operational limits. The worker's lack of an
HTTP health endpoint means progress should be checked in logs and committed database state.

The backend needs migrations even if readiness passes. Settings have no implicit .env search;
Compose injects it and supplies service-name connection URLs. Host Uvicorn instructions in
README use explicit --env-file .env. Never send database settings through `VITE_*` variables.
Ports bind to 127.0.0.1: frontend 5173, API 8000, PostgreSQL 5432, Redis 6379; test PostgreSQL
is 5433 and test Redis is 6380. The dedicated test Redis uses logical database 15.
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
and remove them. That historical prefix is still used through Phase 6. Never truncate the configured
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

Head/current should be 0002_worker_expiry; check reports
no new operations when schema/models match. Never downgrade development data for a test.
Frontend build already includes typecheck; there is no frontend unit-test/ESLint framework.
Redis PONG is only service health. The Phase 6 real Redis/PostgreSQL tests and live smoke
exercise the limiter, metadata cache, outage, cold API startup, worker independence, and recovery.
The smoke sequence is documented in [Phase 6 validation](phase-6-validation.md#live-outagerecovery-reproduction).
Host Uvicorn and Compose disable proxy-header trust, preserving peer-based quota identity.

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

This stops ordinary/test-profile services without removing containers or volumes. Stop the
opt-in worker with `docker compose --profile worker stop worker` when it is running. The README
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
| Repository/branch | [CSRS on GitHub](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System), main |
| Phase 5 historical implementation | `03ea3108999f051887e6788e26ed9342e08a7e1b`; 474 tests; [green CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40293310608) |
| Phase 6 implementation commit | `7d7c705b438437a2a63ccd7d9fbffe4d54628f17` — `feat: integrate Redis rate limiting and event caching` |
| Phase 6 manifest | 32 files: 8 added, 24 modified; see [manifest](phase-6-validation.md#changed-file-manifest) |
| CI correction commit | `d188a7e6279818a8e702bbd682fcd97765a8cd34` — `ci: harden backend readiness probe after container restart`; CI workflow only |
| Final Phase 6 source suite | 540 passed: 153 unit/contract + 387 PostgreSQL/Redis integration; 66 new Phase 6 tests |
| Final audit | Zero BLOCKER/HIGH; one MEDIUM and three LOW self-audit findings resolved with focused/repeated checks |
| Corrected hosted CI | [Foundation CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40349763474) completed/success for exact correction SHA; backend, frontend, Compose green |
| Hosted Compose evidence | 540 passed; worker smoke expired five holds; Redis available/outage/recovered each passed 13 HTTP checks, one expiry, zero counter mismatches |
| Other checks | Ruff, Alembic 0002/head/drift, contracts, TypeScript/build, Compose, live API/worker/Redis smokes, database reconciliation; provenance in Phase 6 validation |
| Implemented API | Version 0.4.0; 20 paths / 22 operations; organizer reservation dashboard remains unregistered |
| Git before this documentation update | Clean; local HEAD, tracking, and live remote main all matched CI correction SHA |
| Next application phase | Phase 7 - Full Frontend; requirements in I, not started |
| Documentation change | Only `docs/PROJECT_HANDOFF.md`; separate authorized documentation commit and CI gate |

The original [Phase 6 implementation CI run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40347628733)
failed in the Compose Redis smoke step when a new backend container briefly returned
`curl: (52) Empty reply from server`. Backend and frontend jobs passed; Redis available mode
passed, but outage and recovery never ran. The corrected readiness probe retries transient
connection errors for at most 20 retries/60 seconds, limits each attempt to five seconds, and
still requires HTTP success. On failure CI prints backend status and Compose logs. Local
reproduction observed two empty replies followed by a real 200; persistent 503 and empty
replies remained nonzero. Local and hosted Redis available/outage/recovery smokes then passed.
The correction changed no application source. The corrected hosted run is green for its own
SHA, including actual outage and recovery output.

This handoff is a separate documentation update. Its commit hash, remote equality,
working-tree state, and independent CI result belong in the final report; a green result for
the correction commit must not be attributed to the later documentation SHA.

No known Phase 6 correctness blocker or unresolved self-audit finding remains. Documented
limits: Redis restart resets quotas/cache; fixed windows can burst at boundaries; public
reads and authenticated writes fail open on Redis outage, while new anonymous sessions and
login/register fail closed. A shared proxy/NAT peer shares a quota. Old fills or failed
invalidation may leave public metadata stale for at most its original TTL; publication is
still checked in SQL. No cache stampede control, production load/latency SLA, live TLS-server
test, Redis cluster/failover, or automated session/idempotency retention cleanup exists.
An OS DNS lookup itself cannot be cancelled, though callers/shutdown are bounded and at
most one lookup remains pending per API client. The worker has no health endpoint or
production alerting; its cleanup latency depends on polling, contention, backlog, and
database availability. Phase 5's ordered index migration was not an online production
migration. Readiness checks PostgreSQL connectivity, not migration currency, Redis health,
or worker progress. Organizer dashboard, business UI, account recovery/verification/MFA,
and deployment remain planned or outside this phase. No Phase 8 mixed-load or backup/restore
claim is made.

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
success. The approval to publish this handoff is not approval to implement or commit Phase 7.

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

1. This handoff, especially implemented protocols H/H8, next-phase requirements I, and workflow L;
   then Git status/log and the current CI result.
2. [Concurrency protocol](concurrency.md), [API contract](contracts/api.md),
   [database design](database.md), [security](security.md), and [decisions](decisions.md).
3. [Phase 6 validation](phase-6-validation.md), including quota/cache boundaries, audit
   fixes, and corrected CI evidence, and its
   [explanation](phase-explanations/phase-6-explanation.md). Read
   [Phase 5 validation](phase-5-validation.md), [Phase 4 validation](phase-4-validation.md),
   and their explanations for worker and booking guarantees; D links earlier records.
4. Actual frontend `App.tsx`, health API client, package scripts, Vite proxy, and current
   auth/event/reservation routes and schemas. Verify the organizer dashboard and closed-event
   metadata gaps in I before designing those screens. Preserve the PostgreSQL transaction
   and Redis failure boundaries described in C/H/H8.
5. [README](../README.md), [Compose](../compose.yaml), and
   [CI workflow](../.github/workflows/ci.yml) before running the environment.

The next implementation is **Phase 7 - Full Frontend**, after a new explicit request.
This documentation-only update implements no application functionality and does not remove
the requirement to stop for review before any future phase's commit/push.
