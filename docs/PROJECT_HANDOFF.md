# CSRS project handoff: Phase 8 complete as a local portfolio project

**Snapshot, 2026-10-28:** all eight planned phases are complete with the owner's revised
localhost-first Phase 8 scope. The application runs locally with Docker Compose; no cloud
hosting, public deployment or production traffic validation has occurred.
Implementation commit `19ff02c4f04a1e848225732812295f4c7b4bfbd7`
is published on main and is the verified source SHA.
The [exact-commit Foundation CI run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40707353169)
is completed/success: backend, frontend and Compose all passed. Local finalization passed
**555 backend tests (156 unit/contract and
399 PostgreSQL/Redis integration)**, **71 frontend tests** and **eight Chromium journeys**.

The owner explicitly approved implementation publication and this separate handoff update.
The handoff commit's own SHA, synchronization and independent hosted CI are verified separately
in the finalization report; implementation CI is not attributed to an untested documentation SHA.
[Phase 8 validation](validations/phase-8-validation.md) preserves the original prepublication evidence,
the supplemental 503 failure and its bounded investigation, plus fresh finalization gates.

Repository: [Concurrency-Safe-Reservation-System](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System).
Local workspace: `C:\Users\ASUS\OneDrive\Desktop\csrs`.

Before editing in a new conversation, read this document, inspect Git status, and read the
current source and contracts. This is a snapshot, not a replacement for the implementation.
Some older reports and explanations retain pre-commit "pending review" wording. Those are
historical review records; they do not mean approved Phases 2-7 must be implemented again.
Do not rewrite their results to imply tests ran at a later commit.

## A. Project overview

The **Concurrency-Safe Reservation System (CSRS)** is a student-built event/workshop application
intended to demonstrate backend engineering in Software Engineer / SDE-1 interviews.
Its central capacity guarantee is implemented and tested through the shared PostgreSQL protocol:
concurrent reservation requests do not allocate beyond an event's capacity.

An attendee can use the React browser UI to browse events and hold, confirm, or cancel one seat.
An organizer manages owned events and sees a private booking dashboard. Local administrators
provision organizer access. The project is a modular monolith, deliberately sized for one student to
understand and defend; it is not a collection of microservices.

Currently working: health checks, configuration, PostgreSQL schema/migrations, backend
registration/login/logout/current user, sessions/CSRF/roles, organizer event-management APIs,
public discovery/availability, one-seat holds, confirmation/cancellation, owner reservation
detail/history, durable idempotency, request-time expiration, and an independently running
PostgreSQL expiration worker, atomic Redis quotas, public event-detail metadata caching,
the owner-scoped booking snapshot, and the full attendee/organizer React UI.
**The revised eight-phase local portfolio roadmap is complete. Public cloud deployment is
optional future work, not part of the completed Phase 8 scope.**
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
| React 19, TypeScript 5.9, Vite 7, Node.js 24 | Full responsive browser UI and development `/api` proxy |
| React Router 7, Zod 4 | Deep links and runtime-validated API responses |
| PostgreSQL 17 | Durable source of truth for identity, events, capacity, reservations, and idempotency |
| SQLAlchemy 2.0, Psycopg 3 | Synchronous sessions, explicit transactions, connection pool, SQL, and PostgreSQL driver |
| Alembic | Explicit schema migrations; head 0002_worker_expiry adds an ordered partial expiration index |
| Redis 7.4, redis-py 8.1 | Ephemeral, shared API rate limits and public detail metadata cache; never a reservation, session, or idempotency authority |
| argon2-cffi, email-validator | Argon2id passwords and canonical validated ASCII email addresses |
| Database-backed opaque sessions | Random cookie secrets, server-side expiry/revocation, independent synchronizer CSRF tokens; no JWT/OAuth |
| Pytest, FastAPI TestClient, HTTPX2 | Unit/contract tests, real PostgreSQL integration, controlled concurrency/failure tests |
| Vitest, Testing Library, Playwright, axe | Frontend/API component tests, real Chromium journeys, accessibility checks |
| Ruff | Backend lint and format checks |
| Docker / Docker Compose | Complete local stack, serialized migration gate, persistent PostgreSQL, disposable test services and explicitly enabled worker profile |
| GitHub Actions | CI on pushes/PRs: backend, frontend, Compose/browser, worker and Redis smoke; no production deployment |

Dependency constraints live in `backend/pyproject.toml`; resolved development constraints are
in `backend/requirements-dev.lock`. Frontend reproducibility uses `frontend/package-lock.json`
and npm ci. Do not upgrade dependencies merely to begin unrelated work. HTTPX2 is the current
test client's dependency, not an application HTTP service. No Celery or broker is installed.

## C. Architecture and source map

### Components and request flow

The browser uses relative `/api/v1` URLs through a central validated client. Vite forwards
`/api` to FastAPI without rewriting Origin. The local browser trust boundary is
`http://localhost:5173`; API documentation on
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

See the existing [architecture and diagrams](architecture.md), especially the system,
application, reservation transaction, and worker lifecycle diagrams. Their labels distinguish
implemented local services from optional future hosting.
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
| `backend/src/csrs/events/dashboard.py` | Read-only owner booking counts and paginated rows |
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
| `backend/scripts/frontend_fixture.py` | Scoped real-browser fixture setup, verification, and cleanup |
| `backend/tests/unit/` | Config, health, crypto, event input/cursor, runtime-contract checks |
| `backend/tests/integration/` | Real PostgreSQL auth, events, schema, migrations, and concurrency/failure cases |
| `backend/tests/integration/test_reservations.py` | Reservation HTTP/state/deadline behavior and SQL invariants |
| `backend/tests/integration/test_reservation_transactions.py` | Two-process contention, controlled lock waits, strengthened clock test, faults |
| `backend/tests/integration/test_worker.py` | Real PostgreSQL sweeps, bounds, races, recovery, and invariant checks |
| `backend/tests/integration/test_worker_processes.py` | Independent worker process contention, crash, outage, shutdown/restart tests |
| `backend/tests/integration/test_dashboard.py` | Real PostgreSQL dashboard authorization, counts, and pagination |
| `backend/tests/unit/test_redis_runtime.py`, `backend/tests/integration/test_redis_support.py` | Redis lifecycle, real PostgreSQL/Redis, API-process, cache, and outage checks |
| `frontend/src/App.tsx` | Router, layout, role guards, and supported screen paths |
| `frontend/src/api/client.ts`, `frontend/src/api/models.ts` | Typed runtime validation, CSRF, errors, retries, booking intents |
| `frontend/src/session.tsx`, `frontend/src/hooks.ts` | Session context and page-local resource loading |
| `frontend/src/pages/`, `frontend/src/components/` | Public, account, attendee, organizer, shared UI and countdown |
| `frontend/e2e/journeys.spec.ts`, `frontend/playwright.config.ts` | Real browser journeys and scoped fixtures |
| `frontend/src/api/health.ts` | Validated readiness fetch and frontend error classification |
| `frontend/vite.config.ts` | Origin-preserving /api proxy |
| `compose.yaml`, `backend/Dockerfile`, `frontend/Dockerfile` | Development/test containers, opt-in worker, ports, volumes, startup |
| `backend/src/csrs/migrate.py` | Database advisory transaction lock, Alembic upgrade and drift verification before API/worker startup |
| `backend/src/csrs/demo.py` | Explicit UUID-scoped demo setup/status/guarded cleanup and private password prompt |
| `backend/scripts/smoke_recovery.py` | Durable session/replay, worker and database-outage assertions across real service restarts |
| `backend/scripts/reconcile.sql` | Read-only repeatable-read counter/bounds/active-uniqueness/completion checks |
| `scripts/local.ps1` | Prerequisite-aware complete local start/stop/status; preserves .env and database volume |
| `scripts/verify-local.ps1`, `compose.validation.yaml` | Generated isolated recovery project/volume, verified zero host ports and reliable failure propagation |
| `backend/tests/integration/test_local_operations.py` | Seven real PostgreSQL startup/fixture/failure-cleanup cases |
| `docs/DEMO_GUIDE.md`, `docs/INTERVIEW_GUIDE.md` | Beginner-friendly interview walkthrough, technical explanation and troubleshooting |
| `docs/FUTURE_DEPLOYMENT.md`, `docs/evidence/` | Deferred hosting requirements, sanitized captures/results and reproduction provenance |
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
| 1 | Monorepo, configuration, health backend/UI, Compose, Alembic scaffolding, CI, contracts | 24 passed: 22 unit/contract + 2 real PostgreSQL; exit 0 | [Validation](validations/phase-1-validation.md), [explanation](phase-explanations/phase-1-explanation.md) |
| 2 | Five tables, initial migration, sessions/auth/CSRF/roles/admin CLI | 170 passed: 54 unit/contract + 116 PostgreSQL; exit 0 | [Validation](validations/phase-2-validation.md), [explanation](phase-explanations/phase-2-explanation.md) |
| 3 | Public/owner event reads, draft create/edit/capacity/publish/close, event locks | 323 passed: 107 unit/contract + 216 PostgreSQL; exit 0 | [Validation](validations/phase-3-validation.md), [explanation](phase-explanations/phase-3-explanation.md) |
| 4 | Holds, confirmation/cancellation, request-time expiry, durable idempotency, private history/detail, public availability | 417 passed: 114 unit/contract + 303 PostgreSQL; exit 0 | [Validation](validations/phase-4-validation.md), [explanation](phase-explanations/phase-4-explanation.md) |
| 5 | Independent PostgreSQL expiry worker, bounded backlog catch-up, multi-worker/restart recovery, ordered index | 474 passed: 130 unit/contract + 344 PostgreSQL; exit 0 | [Validation](validations/phase-5-validation.md), [explanation](phase-explanations/phase-5-explanation.md) |
| 6 | Atomic multi-process Redis quotas, public detail cache, outage policies, bounded connection behavior | 540 passed: 153 unit/contract + 387 PostgreSQL/Redis integration; exit 0 | [Validation](validations/phase-6-validation.md), [explanation](phase-explanations/phase-6-explanation.md) |
| 7 | Full attendee/organizer UI and owner booking snapshot | 545 backend, 71 frontend, 7 Chromium journeys; exit 0 | [Validation](validations/phase-7-validation.md), [explanation](phase-explanations/phase-7-explanation.md) |
| 8 | Local startup/migration gating, safe demos, persistence/recovery, security review and portfolio evidence | 555 backend, 71 frontend, 8 Chromium journeys; hosted backend/frontend/Compose green | [Validation](validations/phase-8-validation.md), [explanation](phase-explanations/phase-8-explanation.md) |

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

No event or reservation command existed yet. Rate limiting arrived in Phase 6 and auth
screens in Phase 7; password recovery, email verification, MFA, and scheduled maintenance
remain absent today.
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
passed as recorded in [Phase 5 validation](validations/phase-5-validation.md).

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
[Phase 6 validation](validations/phase-6-validation.md) and
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

### Phase 7: full React frontend

React Router now connects public discovery/detail, account forms, private reservations, and
organizer management to the real API. Zod validates response DTOs at the central API boundary;
the client uses same-origin paths, cookies, CSRF, no-store reads, bounded timeouts, controlled
errors, numeric `Retry-After`, and no automatic mutation retry. Session context restores
`/auth/me`, clears private state on logout/401/account change, and ignores stale completions.
Page-local resource hooks own loading, error, and refresh state. Shared components provide
headings, statuses, pagination, dialogs, and a server-time-anchored countdown. Forest-green
and cream CSS adapts to narrow screens without an external component framework.

| Browser route | Implemented screen |
| --- | --- |
| `/` | Published event discovery and keyset pagination |
| `/events/:id` | Published detail, advisory availability, and hold action |
| `/login`, `/register` | Cookie/CSRF account forms; registration requires later login |
| `/reservations`, `/reservations/:id` | Private history, current detail, timer, confirm/cancel |
| `/organizer`, `/organizer/events/new` | Owned-event list and draft creation |
| `/organizer/events/:id`, `/organizer/events/:id/edit` | Owner controls, dashboard, editing |

Unknown paths show a fallback; protected paths show login-required or organizer-denied states.
Attendees can browse, register, log in/out, restore a session, hold one seat, view the
five-minute maximum countdown, confirm, cancel, and inspect history. The browser retains one
idempotency key per uncertain hold/confirm/cancel intent and fetches current private detail
after success or replay. After reload, it checks all history pages before a new hold. A final
seat conflict displays the server's 409 feedback. Availability and the timer are **advisory**;
PostgreSQL alone decides admission, deadline validity, state, and allocated capacity.

Organizers can create drafts, edit allowed metadata, change capacity through its separate
endpoint, publish, close, and view owned bookings. Published start/deadline fields stay
immutable; CLOSED is read-only. Phase 7 adds only
`GET /api/v1/organizer/events/{event_id}/dashboard` to the backend. It is owner-scoped,
write-free, no-store, keyset-paginated, and returns count categories plus effective
reservation statuses without customer identities. A single PostgreSQL statement shares one
clock/snapshot across counts and rows. API version remains 0.4.0; OpenAPI has **21 paths and
23 operations**. No migration or reservation/worker lock-protocol change was required.

The browser keeps session-related tokens and pending booking keys in memory. Backend role,
ownership, cookie, trusted-Origin, CSRF, and PostgreSQL checks remain authoritative. A
departed screen ignores command callbacks, and account changes remount private UI state.
Structured failures cover 401/403/404/409/415/422/429/503 and network uncertainty.

Local final verification passed **545 backend tests** (153 unit/contract, 392 real
PostgreSQL/Redis integration), **71 frontend tests**, and seven real Chromium journeys.
The journeys exercise attendee and organizer forms, two independent last-seat sessions,
deadline rejection, lost-response same-key recovery, keyboard/focus behavior, axe checks,
390/768/1440-pixel layouts, cross-account denial, and SQL reconciliation. Live reservation
smoke passed 35 HTTP checks with table counts restored. The source self-audit resolved one
HIGH and several MEDIUM/LOW findings; [Phase 7 validation](validations/phase-7-validation.md) records
each correction and the local commands. Hosted
[Foundation CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40505497985)
passed for exact correction SHA `10be01a591567b2198b4dd38db8e96047ff872e4`:
backend/frontend/Compose green, 545 Compose tests, 35 reservation checks, seven browser
journeys, worker expiration of five holds, and Redis available/outage/recovered modes with
13 HTTP checks, one worker expiration, and zero invariant mismatches each.

Implementation commit `99a3c7c3909a53abcee55fee6294938db1328ca9` changed 45 files
(22 added, 23 modified). CI correction `908a23675e1403317904d144cffc6ec8bcab1369`
moved browser dependencies before Compose's frontend bind mount and added reservation smoke.
Browser-test correction `10be01a591567b2198b4dd38db8e96047ff872e4` tied each 201/409
response to its originating page and retained failure-only Playwright evidence in CI. The
first two hosted runs failed at dependency permissions and a test navigation race; neither
was reported green. The final exact-commit run above passed all gates.

Limits: Firefox, Safari, physical devices, manual screen readers, extreme zoom, formal WCAG
certification, and production performance have not been verified. Network delay makes the
countdown approximate. Closed-event history may show an event-ID fallback. History recovery
can read many pages and pagination is not a frozen multi-request snapshot. HTTP-date
`Retry-After`, automated session/idempotency retention, account recovery/verification/MFA,
and production deployment remain outside the completed Phase 7 scope.

### Phase 8: local production readiness and portfolio evidence

The owner replaced the cloud roadmap with a reproducible localhost stack. The migration
service waits for PostgreSQL, takes a database advisory transaction lock, upgrades/checks
Alembic and gates API/worker startup. Frontend startup waits for API readiness and has an
HTTP probe. The wrapper enables the worker profile, preserves existing configuration/data,
and stops all application/test profiles without volume deletion. Runtime restart policies,
bounded logs and stable non-reloading API behavior support local demonstrations.

The explicit demo CLI uses deterministic UUID ownership, a private password prompt and
idempotent setup. Cleanup rejects collisions and reservations crossing into other accounts
or events. A generated separate Compose project verifies zero host ports/its volume scope,
then exercises five service restarts, ordinary down/up and PostgreSQL/Redis outages. Sessions,
exact durable replay, confirmed rows, overdue worker cleanup and SQL equality recover.

Fresh finalization passed 555 backend tests in 108.46 seconds, 71 frontend tests, eight
Chromium journeys in 42.7 seconds, all retained security/contract/worker/Redis checks,
35 reservation smoke checks, five worker expirations and zero SQL invariant issues.
Each Redis available/outage/recovered mode passed 13 HTTP checks, one expiration and zero
mismatches. Ruff/Prettier/build, Alembic head/current/drift, advisory scans, six rendered
Mermaid diagrams and documentation/reference checks passed. Seven real masked PNGs total
584,868 bytes; no traces, credentials or recordings were committed.

The earlier supplemental 20-capacity run's unexpected 503s remain documented. Three prior
quiet repetitions and two fresh diagnostic repetitions passed unchanged strict assertions
and timeout budgets. New diagnostics observed no database-503 event and no PostgreSQL timeout,
connection-limit or unexpected-shutdown messages; test services stayed healthy. The original
exception/SQLSTATE was not retained, so its precise cause is unproven. No reproducible
BLOCKER/HIGH defect or production performance claim was established.

The source audit resolved operational/configuration/fixture findings and preserved existing
booking/auth/worker protocols, constraints and locks. Production settings now reject known
public example database passwords. A generated disposable database role preserves every
original HTTPS-cookie assertion. Non-Chromium/manual-screen-reader/physical-device coverage,
public runtime hardening, backups/restore, production monitoring and benchmarks remain absent.

Implementation `19ff02c4f04a1e848225732812295f4c7b4bfbd7` changes 39 files (17 modified, 22 added).
That exact source has [green hosted CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40707353169).
See section I and the Phase 8 guides for operations and scope.
The Phase 1-7 narratives above remain historical evidence for their original commits.

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

All six operations above are implemented. Phase 5 added no HTTP operation. Phase 7 added the
owner-only, write-free `GET /organizer/events/{event_id}/dashboard` with count categories,
paginated reservation rows, no customer identities, and no side effects. Dashboard/business
UI work was outside Phase 5 and is now delivered.

Reservation output is id/event_id/effective status/created_at/hold_expires_at/confirmed_at/
cancelled_at/expired_at/server_time. UUID IDs, UTC RFC 3339 times, sanitized validation, and
the existing error envelope are retained. Reject client-supplied user/owner/state/counter fields.
History pagination orders `(created_at,id)` ascending with user-scoped cursors, default 20 and max 100.
An overdue stored HELD reads as effective EXPIRED without a GET-side write; expired_at remains
null until cleanup persists it. Availability is computed in one consistent database query
from valid holds plus confirmed rows, is not cached, and never guarantees a later hold succeeds.
The implemented dashboard distinguishes valid holds, overdue HELD awaiting cleanup,
confirmed, cancelled, expired, and the stored counter rather than presenting incompatible
counts as equal.

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
  delivered in Phase 5, Redis support in Phase 6, and the full UI in Phase 7. Deployment
  remains planned; payments are outside the current roadmap.

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
discards ephemeral quotas/cache. See [Phase 6 validation](validations/phase-6-validation.md) and
[security](security.md) for exact settings and failure policies.

## I. Completed Phase 8 and optional future hosting

**Complete and verified as a local portfolio project.** The owner explicitly chose localhost
and Docker instead of public hosting. No Render/Vercel/Railway deployment, paid service,
domain, public database/Redis endpoint or production traffic validation exists.

### Delivered local architecture and operations

- React/Vite serves localhost:5173 and preserves Origin through its same-origin API proxy.
- FastAPI serves localhost:8000 with opaque sessions, CSRF, roles and ownership. API reload
  is disabled for stable demos; explicit restart applies source edits.
- PostgreSQL 17 owns durable users/sessions/events/reservations/capacity/deadlines/idempotency
  in the existing persistent postgres_data volume. Head remains 0002_worker_expiry; no model,
  constraint, table, business endpoint or migration changed in Phase 8.
- A separate advisory-locked migration service upgrades/checks schema before API/worker.
  Competing cooperating runners serialize or fail within the configured statement timeout;
  rollback leaves no partial startup schema. Do not race raw Alembic against this entry point.
- Redis 7.4 supports quotas/public detail metadata only, with bounded memory/timeouts and
  the existing fail-open/fail-closed policies. It never owns seats or durable outcomes.
- The independently supervised PostgreSQL worker is enabled by the complete-stack wrapper.
  Progress is verified with logs and committed expiration, not generic Running status.
- Runtime services have unless-stopped policies and bounded json-file logs. Published ports
  bind to loopback. Images/Vite remain local tooling, not hardened public production packaging.

### Verification, fixtures and evidence

Local gates passed 555 backend cases (156 unit/contract + 399 integration), 71 frontend tests,
eight real Chromium journeys, lint/format/typecheck/build, Alembic/metadata, SQL reconciliation,
scoped reservation/worker smoke and isolated dependency recovery. Final-seat races across two
API processes produced 1/49 and 20/80 outcomes; ten matching keys gave one execution/nine
replays; ten different keys for one user gave one allocation. No assertion or timeout was
weakened. Lost browser response delivery and server-side session expiry are exercised.

The generated recovery project has a separate volume and verified zero host ports. Real
API/frontend/Redis/worker/PostgreSQL restarts and ordinary down/up preserve sessions, replay,
confirmed state and counters. Stopped PostgreSQL yields liveness 200, readiness/private-read
503 and recovers afterward. Redis available/outage/recovered each passed 13 checks, one worker
expiration and zero invariant mismatches. A separate worker backlog smoke expired five holds;
reservation smoke passed 35 HTTP checks and restored table counts.

Demo setup is explicit and local-only (`python -m csrs.demo prepare --scope UUID`), with a
private 15-128-character password prompt and no committed default account password. Repeat
setup preserves state. Cleanup validates deterministic identities, locks scoped events and
refuses foreign reservations. Test databases/keys are disposable and separate from application
data. Neither local wrapper nor recovery verifier deletes volumes.

Seven real PNGs under docs/evidence show public discovery/detail, held countdown, confirmation,
history and organizer creation/dashboard. Account-address elements are masked. No real
credentials/cookies/CSRF values or browser traces were committed. Six Mermaid diagrams rendered
in Chromium. Known-token/private-key-pattern and staged-manifest reviews passed; dependency
advisory checks found zero npm and no known pinned Python vulnerabilities. These are bounded
checks, not complete vulnerability absence, formal WCAG or physical-device certification.

### Supplemental 503 and remaining limits

The earlier capacity-20 run created 20 holds and returned 74 EVENT_FULL plus unexpected responses
including controlled 503. Its strict assertion failed and its complete remaining histogram was
not retained. Three original quiet runs and two finalization diagnostic runs passed unchanged.
The new observer saw no database-503 event; correlated PostgreSQL logs had no statement-timeout,
connection-limit or unexpected-shutdown messages; test services remained healthy. Redis is
outside these SQL correctness fixtures. The original exception/SQLSTATE is unavailable, so
its precise cause remains unproven. Do not hide the failure or turn these fixed workloads into
a production performance claim. No reproducible BLOCKER/HIGH defect was found.

Hot-event writes serialize; availability/countdown are advisory; old metadata may remain stale
within its absolute TTL; Redis restart resets quotas/cache; proxy peers share quotas. Worker
cleanup latency depends on backlog/locks/outages. Readiness proves PostgreSQL connectivity,
not schema currency, Redis, worker progress or backups. Session/idempotency retention schedules,
account recovery/verification/MFA, public HTTPS, managed failover/backups/observed restore,
production monitoring, Firefox/Safari, manual screen readers and physical devices remain outside
verified scope. Original Phase 1-7 counts/narratives retain their historical meaning.

### Publication and documentation

Implementation: `19ff02c4f04a1e848225732812295f4c7b4bfbd7`.
Message: `feat: finalize local deployment readiness and demo evidence`.
The verified source is this implementation SHA. Its
[hosted implementation Actions run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40707353169)
completed/success
for that exact SHA; backend, frontend and Compose jobs all passed. This handoff is a separate
publication and its own hosted run must be verified independently, as reported at finalization.

- [Demo guide](DEMO_GUIDE.md): setup, five-minute walkthrough, deeper tests and troubleshooting.
- [Interview guide](INTERVIEW_GUIDE.md): accurate concurrency/retry/worker/Redis explanations.
- [Phase 8 validation](validations/phase-8-validation.md): original/fresh evidence, failures and audit.
- [Phase 8 explanation](phase-explanations/phase-8-explanation.md): twelve beginner sections.
- [Evidence](evidence/README.md): capture provenance, reproduction and sanitized output/hashes.
- [Future deployment](FUTURE_DEPLOYMENT.md): optional hosting work, clearly not executed.

### Optional future Render or similar hosting

A later explicitly authorized assignment may reuse configurable SQL/Redis URLs, exact public
origin, same-origin API path, secure cookie/session behavior, quotas/cache and worker settings.
It still needs a reviewed built-frontend/static/proxy tier, HTTPS, private durable managed
PostgreSQL/Redis with verified TLS, secrets/least privilege, independently supervised worker,
controlled migrations, trusted proxy identity/CORS review, backups with observed restore,
monitoring, rollback and actual hosted verification. Recheck official costs/plan restrictions
at that time; no current prices/free-tier features are assumed. Reservation transactions,
idempotency and expiration do not require redesign simply to change service connections.
No cloud accounts, manifests, infrastructure or deployment are silently authorized here.

## J. Running and checking this repository

Commands start in the repository root. Use Docker Desktop with Linux containers, a modern
Compose supporting --wait and !reset, and PowerShell 7 for wrappers. Host Node.js 24/npm is
needed for host browser/frontend checks; host Python is optional for the container workflow.
Local verification used Docker 29.9.2, Compose 5.6.1, Python 3.12.16 and Node.js 24.22.1.
The frontend and PostgreSQL/Redis host ports are loopback-only. Preserve existing volumes.

### Complete startup and safe shutdown

```powershell
./scripts/local.ps1 start
./scripts/local.ps1 status
docker compose logs --tail 20 migrate worker
./scripts/local.ps1 stop
```

Start preserves an existing .env, copying the labeled public local example only if missing.
It checks Docker/config and runs the equivalent complete-stack command:

```powershell
docker compose --profile worker up --build -d --wait --wait-timeout 180
```

PostgreSQL health gates migrations; migration success gates API/worker; API readiness gates
frontend startup and its HTTP health probe. An exited migrate container with code 0 is normal.
The worker remains an opt-in profile at raw Compose level but the wrapper always enables it.
Check worker-cycle logs/committed expiration separately. Stop includes worker/test profiles
and executes down without volume deletion. Do not copy CI's disposable --volumes cleanup
into ordinary local operation. Changing initialization passwords does not rotate an existing
PostgreSQL volume's credentials. Restart backend/worker after Python edits; rebuild for
changed dependencies. Vite's dependency volume is synchronized by npm ci on startup.

- UI: [localhost:5173](http://localhost:5173/).
- API docs: [localhost:8000/docs](http://localhost:8000/docs).
- Runtime schema: [OpenAPI](http://localhost:8000/openapi.json).
- API [liveness](http://localhost:8000/api/v1/health/live) and
  [readiness](http://localhost:8000/api/v1/health/ready).
- [Proxy readiness](http://localhost:5173/api/v1/health/ready).

Use localhost consistently with CSRS_PUBLIC_ORIGIN. The browser path is configurable through
public VITE_API_BASE_URL (normally /api/v1), with no frontend secrets or permissive CORS.
Compose injects service-DNS connection URLs; Settings never implicitly searches for .env.

### Verification commands

```powershell
docker compose --profile test run --build --rm backend-test
docker compose exec -T backend python -m ruff check --no-cache .
docker compose exec -T backend python -m ruff format --check --no-cache .
docker compose exec -T backend python -m pip check
docker compose exec -T backend python -m alembic heads
docker compose exec -T backend python -m alembic current
docker compose exec -T backend python -m alembic check
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run format:check
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend exec playwright install chromium
npm.cmd --prefix frontend run test:e2e
./scripts/verify-local.ps1
```

On Linux use npm and install Chromium OS dependencies with --with-deps. The test runner uses
separate PostgreSQL/Redis services, generated csrs_phase2_*_test databases and scoped Redis
keys/database 15, never development table truncation. A missing host URL can skip integration;
required full Compose/CI verification must actually run the real services. The supplied test
role has administrative permissions needed to create disposable databases/test roles.

The recovery verifier generates a separate project/volume with no host ports. It validates
isolation before restarting/stopping dependencies, keeps fixture credentials only in memory/
stdin, asserts persistence/replay/worker/SQL recovery and returns failure reliably. It stops
its own project and retains its volume afterward; normal csrs data is untouched.

Read-only reconciliation and live smoke:

```powershell
docker compose exec -T backend python scripts/smoke_reservations.py
Get-Content backend/scripts/reconcile.sql | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
docker compose --profile worker stop worker
$scenario = docker compose exec -T backend python scripts/smoke_worker.py prepare
docker compose --profile worker up -d worker
docker compose exec -T backend python scripts/smoke_worker.py verify $scenario
```

The local helpers create/clean only scoped records. Keep the scenario UUID if interrupted.
The demo guide supplies repeatable account/event setup, cleanup guards and final-seat commands.
Organizer promotion and bounded session maintenance remain explicit administrative operations:

```text
docker compose exec -T backend python -m csrs.cli promote-organizer EMAIL
docker compose exec -T backend python -m csrs.cli purge-sessions --batch-size 1000
```

Promotion revokes sessions; log in again. Purge is security-session maintenance, not hold expiry.
If deliberately changing API DTOs/routes, export contracts using the explicit host Python
entrypoint backend/scripts/export_health_contract.py, then review/run equality tests.
The docs mount is read-only inside the development backend. No export was needed in Phase 8.

On this Windows machine Docker's executable lives under
C:\Users\ASUS\AppData\Local\Programs\DockerDesktop\resources\bin.
Add it to the current command PATH if needed, without extracting credentials. Docker socket
access may require executor escalation. Ignored .local validation tools/logs are not clone
prerequisites and must not be staged. Never replace PostgreSQL with SQLite to avoid a test gate.

## K. Git, CI, and current verification status

| Item | Verified snapshot |
| --- | --- |
| Repository/branch | [CSRS on GitHub](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System), main |
| Phase 5 historical implementation | `03ea3108999f051887e6788e26ed9342e08a7e1b`; 474 tests; [green CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40293310608) |
| Phase 6 implementation commit | `7d7c705b438437a2a63ccd7d9fbffe4d54628f17` — `feat: integrate Redis rate limiting and event caching` |
| Phase 6 manifest | 32 files: 8 added, 24 modified; see [manifest](validations/phase-6-validation.md#changed-file-manifest) |
| CI correction commit | `d188a7e6279818a8e702bbd682fcd97765a8cd34` — `ci: harden backend readiness probe after container restart`; CI workflow only |
| Final Phase 6 source suite | 540 passed: 153 unit/contract + 387 PostgreSQL/Redis integration; 66 new Phase 6 tests |
| Final audit | Zero BLOCKER/HIGH; one MEDIUM and three LOW self-audit findings resolved with focused/repeated checks |
| Corrected hosted CI | [Foundation CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40349763474) completed/success for exact correction SHA; backend, frontend, Compose green |
| Hosted Compose evidence | 540 passed; worker smoke expired five holds; Redis available/outage/recovered each passed 13 HTTP checks, one expiry, zero counter mismatches |
| Other checks | Ruff, Alembic 0002/head/drift, contracts, TypeScript/build, Compose, live API/worker/Redis smokes, database reconciliation; provenance in Phase 6 validation |
| Phase 7 implementation | `99a3c7c3909a53abcee55fee6294938db1328ca9` — `feat: build complete React reservation frontend`; 45 files (22 added, 23 modified) |
| Phase 7 dependency CI correction | `908a23675e1403317904d144cffc6ec8bcab1369` — `ci: fix frontend browser test dependency permissions` |
| Phase 7 browser CI correction | `10be01a591567b2198b4dd38db8e96047ff872e4` — `test: fix final-seat browser race synchronization` |
| Final Phase 7 suite | 545 backend tests: 153 unit/contract + 392 PostgreSQL/Redis integration; 71 frontend tests; seven Chromium journeys |
| Final Phase 7 CI | [Foundation CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40505497985) completed/success for exact browser-correction SHA; backend, frontend, Compose green |
| Phase 7 hosted smoke | 35 reservation HTTP checks with table counts restored; worker expired five holds; Redis available/outage/recovered each passed 13 HTTP checks, one expiry, zero invariant mismatches |
| Phase 8 implementation | `19ff02c4f04a1e848225732812295f4c7b4bfbd7` — `feat: finalize local deployment readiness and demo evidence`; 39 files (17 modified, 22 added) |
| Phase 8 verified source | `19ff02c4f04a1e848225732812295f4c7b4bfbd7`; [exact-commit green CI](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40707353169), backend/frontend/Compose success |
| Phase 8 final tests | 555 backend (156 unit/contract + 399 integration), 71 frontend, eight Chromium journeys |
| Phase 8 operations/evidence | Full wrapper startup/shutdown and persistence; five worker expirations; 35 reservation checks; three Redis modes; isolated recovery; seven masked PNGs |
| Phase 8 remaining observation | Earlier supplemental 503 not reproduced by unchanged bounded checks; exact original cause unproven, no benchmark claim |
| Implemented API | Version 0.4.0; 21 paths / 23 operations, including owner-only booking dashboard |
| Historical Phase 7 handoff preparation | Clean; local HEAD, tracking, and live remote main all matched Phase 7 browser-correction SHA |
| Planned roadmap | All eight phases complete as a local portfolio project; optional future cloud work in I/FUTURE_DEPLOYMENT.md |
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
the verified implementation commit must not be attributed to an untested documentation SHA.

The first Phase 7 hosted attempt failed while installing Chromium dependencies inside the
bind-mounted frontend container. The dependency correction moved installation before
Compose startup. Its [hosted run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40503511630)
passed backend/frontend but failed the final-seat browser test: server evidence contained
one 201 and one 409, while the test selected the losing page by transient navigation state.
The browser correction selects the page that actually received the 409 and asserts its
specific conflict alert. Three focused local repetitions, the full seven-journey local
suite, and the exact-commit hosted run passed. A temporary negative-control test hiding
the alert failed at that assertion, confirming it checks the user-visible outcome. CI now
uploads Playwright traces/screenshots on browser failure for diagnosis.

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
or worker progress. Account recovery/verification/MFA and optional public hosting remain
outside the completed local scope. No production mixed-load or backup/restore claim is made.

## L. Workflow for future explicitly authorized changes

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
9. The eight-phase local roadmap is complete. Start future changes only with explicit user authorization.

Do not rewrite unrelated working code, create unnecessary migrations/services, silently
weaken tests, force-push, overwrite remote history, or delete local PostgreSQL volumes.
If a tool/dependency/check is unavailable, report the actual blocker rather than inventing
success. This completion handoff does not authorize future cloud deployment or unrelated work.

## M. Documentation conventions and reading order

For every phase maintain these separate files:

| Document convention | Contents |
| --- | --- |
| `docs/validations/phase-X-validation.md` | Actual scope/changed-file manifest, endpoints/security/transactions, commands/environment, test counts and exit statuses, migrations, HTTP/CI evidence, limitations, deferred work, acceptance and Git state at that review |
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

1. This handoff, especially implemented protocols H/H8, completed local scope I, and workflow L;
   then Git status/log and the current CI result.
2. [Concurrency protocol](concurrency.md), [API contract](contracts/api.md),
   [database design](database.md), [security](security.md), and [decisions](decisions.md).
3. [Phase 8 validation](validations/phase-8-validation.md), [demo guide](DEMO_GUIDE.md),
   [interview guide](INTERVIEW_GUIDE.md), and [future deployment plan](FUTURE_DEPLOYMENT.md).
   Then [Phase 7 validation](validations/phase-7-validation.md), including browser journeys, owner dashboard,
   self-audit, and exact-commit CI evidence, and its
   [explanation](phase-explanations/phase-7-explanation.md). Read
   [Phase 6 validation](validations/phase-6-validation.md), [Phase 5 validation](validations/phase-5-validation.md),
   and [Phase 4 validation](validations/phase-4-validation.md) with their explanations for Redis, worker,
   and booking guarantees; D links earlier records.
4. Actual frontend router, central API client, session context, pages, Playwright journeys,
   package scripts, Vite proxy, and backend dashboard route. Preserve the PostgreSQL
   transaction and Redis failure boundaries described in C/H/H8 while designing hosting.
5. [README](../README.md), [Compose](../compose.yaml), and
   [CI workflow](../.github/workflows/ci.yml) before running the environment.

All eight planned phases are complete for the localhost portfolio project. Optional future
Render/similar hosting has not been performed and needs a new explicit request plus its own
security/infrastructure/verification work. Stop after finalization; do not start another phase
or deploy simply because this handoff exists.

## N. Post-Phase-8 maintenance: session and scroll stability

**Verified 2026-10-28.** Manual testing found unsaved organizer event inputs disappearing
and scroll positions jumping after switching tabs/windows. Focus revalidation set loading
on every check, so private guards unmounted the active page and discarded uncontrolled form
inputs. Removing content also collapsed document height and let Chromium clamp scroll.
Separately, anonymous-to-anonymous /auth/me 401 responses reset the API and incremented the
main subtree's revision, unnecessarily remounting public pages. Observed reproductions had
no document reload or URL change; they were not focus-triggered Vite reloads.

The provider now blocks only initial restoration and keeps pages mounted during background
checks. An unchanged anonymous 401 no longer resets the API or revision. Genuine expiry,
account/role changes, logout and failed authenticated revalidation still invalidate private
state. Navigation, backend security/reservation transactions, Redis and worker code are unchanged.

The implementation changes exactly three files:

- [session.tsx](../frontend/src/session.tsx): background restoration and identity handling.
- [App.test.tsx](../frontend/src/App.test.tsx): six additional session/state regression cases.
- [view-stability.spec.ts](../frontend/e2e/view-stability.spec.ts): thirteen additional browser
  tests covering ten public/private views, all seven create-event fields, pending and ordinary
  refreshes, repeated tab activation, navigation/Back and real server session expiry.

Fresh local and corrected hosted checks passed **77 frontend tests** and **21 Chromium tests**,
plus TypeScript, Prettier and the production build. Hosted backend/Compose checks also passed.
Scoped browser cleanup restored counts; read-only PostgreSQL cluster/count/full-row hashes
matched the pre-test snapshot across all five tables. Existing configuration/data were preserved.

Implementation: `15f666e88bb6bd41f2859312037a0217d18f7375`.
Message: `fix: preserve frontend state during session refresh`.
Its first [hosted run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40740121421)
failed in fixture login after the shared peer auth quota returned 429 with Retry-After.
The separate test-only correction `0ba5440b596277890c3a1dc265cad17a46c8decf` makes setup honor
the existing UI cooldown and retry once, with validated Retry-After bounded to 60 seconds.
Only the setup hook gets 120 seconds for that wait; test deadlines/assertions, real login and
security limits remain unchanged.
The [corrected exact-source CI run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40741946048)
completed/success for this correction SHA: backend, frontend and Compose all green.

Automated verification uses headless Chromium tab activation plus supplemental focus events;
manual OS-window-switch behavior has not been independently verified. Drafts are not persisted
across intentional reload/navigation or genuine session changes. Existing native Back restoration
and scroll anchoring may adjust offsets while content reloads. The project remains localhost-only;
no cloud deployment occurred. All earlier Phase 1-8 text above is retained as historical evidence.
The handoff publication's own SHA and independent hosted CI are verified in the final report.

## O. Post-Phase-8 documentation: comprehensive screenshot gallery

**Verified 2026-10-29.** The [application gallery](screenshots/README.md) contains
**73 images across seven categories**: 72 genuine local Chromium captures and one
labeled composition of two genuine final-seat captures. PNGs total **5,304,071 bytes**;
the gallery folder, including its four Markdown documents, totals **5,363,965 bytes**.
The root [README](../README.md#application-screenshots) adds five representative
previews and links to the complete collection. Prior README content is preserved.

Coverage includes public discovery, authentication, organizer create/edit/publish/
capacity/close workflows, owner booking snapshots, HELD/CONFIRMED/CANCELLED/EXPIRED
reservation lifecycles, actual worker expiration after the five-minute deadline,
final-seat accepted/rejected outcomes, safe retry recovery, access controls, and
1440/768/390px layouts. Category counts are public 5, authentication 4, organizer 20,
reservations 12, concurrency 6, errors/security 10, and responsive 16.
Screenshots demonstrate browser behavior; the 1-of-50 and 20-of-100 correctness
evidence remains separately attributed to automated tests. Neither the screenshots
nor those bounded workloads establish production traffic performance.

Screenshot publication commit: `82da4c1979c747782a0535da28d9fe358ff36e2c`.
Message: `docs: add comprehensive application screenshot gallery`.
Its [exact-commit Foundation CI run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40877559646)
completed/success: **backend, frontend, and Compose all passed**.

Final review decoded and visually inspected all images, matched the manifest,
confirmed the comparison's unaltered source pixels, found no exposed credentials
or private user data, and passed Markdown lint, links/anchors, and Git diff checks.
GitHub's authenticated Markdown renderer confirmed five README images and all
73 gallery images; remote Git blob hashes matched the published files. The
repository remains private, so viewers need repository access.

UUID-scoped demo accounts, events, reservations, and retry outcomes were cleaned
safely. Fresh read-only comparisons preserved every original row across all five
PostgreSQL tables and the cluster identity; reconciliation returned zero issues.
The sole added session is an expired, unowned anonymous pre-session left for normal
maintenance. Local Docker volumes were preserved; no destructive cleanup occurred.

The [coverage matrix](screenshots/COVERAGE.md) records uncaptured public-empty and
pagination states, natural eight-hour authentication expiry, and other boundaries.
The minor mobile login heading join remains documented. The [capture report](screenshots/REPORT.md)
preserves its prepublication review checkpoint; [MANIFEST.md](screenshots/MANIFEST.md)
lists all final dimensions and hashes. No application/frontend/backend code,
migration, dependency, security setting, or worker logic changed. **No public cloud
deployment occurred.** Earlier handoff history is retained in full.
