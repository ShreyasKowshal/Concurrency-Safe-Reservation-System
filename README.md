# Concurrency-Safe Reservation System (CSRS)

A full-stack event/workshop reservation project focused on PostgreSQL transactions,
concurrent capacity allocation, idempotency, and failure recovery.

**Current implementation: Phase 5 implemented locally and awaiting review.** The API provides
health checks, session authentication/CSRF, event management, one-seat holds, confirmation,
cancellation, request-time expiration, durable idempotency, private history, and advisory
availability. Five PostgreSQL tables use the foundation schema plus the Phase 5 index migration.
React remains
a health screen. The standalone worker adds bounded cleanup and recovery. Redis limiting/caching, booking/dashboard
UI, and production deployment remain future work. See the [Phase 4 evidence](docs/phase-4-validation.md)
and [beginner explanation](docs/phase-explanations/phase-4-explanation.md).

## Repository structure

```text
csrs/
  .github/                 # GitHub Actions and dependency update configuration
  backend/
    src/csrs/              # App, models, auth/event/reservation services, CLI, API routes
    migrations/            # Foundation schema and bounded-worker index revisions
    scripts/               # Explicit health/full API contract exporter
    tests/unit/            # Configuration, crypto, health, and contract checks
    tests/integration/     # Real PostgreSQL auth, schema, migration, and race checks
    pyproject.toml         # Direct dependency constraints and test/lint configuration
    requirements-dev.lock  # Resolved transitive development constraints
    Dockerfile
  frontend/
    src/api/               # Same-origin health client
    src/App.tsx            # Foundation status screen
    package-lock.json      # Reproducible npm dependency resolution
    Dockerfile
  docs/
    contracts/             # Implemented API/OpenAPI contracts; future dashboard contract
    architecture.md
    database.md
    concurrency.md
    security.md
    decisions.md
    phases.md
    phase-1-validation.md
    phase-2-validation.md
  infra/README.md
  compose.yaml
  .env.example
```

## Local development with Docker Compose

Prerequisites: Git, Docker Engine/Docker Desktop with Linux containers, and Docker Compose v2
supporting `up --wait`. Docker must be running. Host Python and Node are optional for the
container workflow. Reserve ports 5173, 8000, 5432, and 6379; test PostgreSQL uses 5433.

From the repository root, copy the example once (PowerShell):

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 120
docker compose exec -T backend python -m alembic upgrade head
docker compose exec -T backend python -m alembic check
docker compose logs -f backend frontend
```

On macOS/Linux use `cp .env.example .env` for the copy step. Do not overwrite an existing
local `.env` without reviewing it. Example credentials are public, local-only values.
Use URL-safe local PostgreSQL credentials with this Compose interpolation; special characters
would require consistently URL-encoded connection values.

- Frontend: [localhost:5173](http://localhost:5173)
- API docs: [localhost:8000/docs](http://localhost:8000/docs)
- Liveness: [localhost:8000/api/v1/health/live](http://localhost:8000/api/v1/health/live)
- Readiness: [localhost:8000/api/v1/health/ready](http://localhost:8000/api/v1/health/ready)

Frontend dependency installation occurs at container startup to synchronize its named
`node_modules` volume. The frontend can briefly be starting after Compose reports it running;
check its logs if the page is not ready. Python source and frontend source support reload.
Rebuild the backend image after Python dependency changes.

The browser uses Vite's same-origin `/api` proxy. Use `localhost:5173` consistently with
`CSRS_PUBLIC_ORIGIN`; do not switch to a different host alias when testing later CSRF behavior.
Redis runs locally but is intentionally not queried by the application. Apply the
migration before using authentication. Readiness still checks connectivity, not schema currency.
Migrations are explicit administrative steps, never automatic per-API-process startup work.

Stop services while preserving PostgreSQL data:

```powershell
docker compose down
```

Do not add `--volumes` unless intentionally discarding local data. Changing initialization
credentials does not change an already initialized PostgreSQL volume. See [infrastructure
notes](infra/README.md).

## Tests in Docker: isolated PostgreSQL

```powershell
docker compose --profile test run --build --rm backend-test
docker compose --profile test stop postgres-test
```

The runner executes all Pytest tests. `csrs_test` on the separate `postgres-test` service is
the connection target used to create generated `csrs_phase2_<uuid>_test` databases. Tests apply
real migrations and commit transactions there, then remove only those generated databases.
The test role needs CREATEDB permission (the local/CI test role has it). The configured input
database is not truncated/dropped, and tests never point at the development application database.
No SQLite integration fallback exists. A configured but unreachable PostgreSQL server fails
the integration tests; only an absent test URL produces an explicit local skip.

## Optional host development

Use Python 3.12, Node.js 24, and npm. `.python-version` and `.nvmrc` record those runtime
choices. PostgreSQL and Redis can still be started through Compose:

```powershell
docker compose up -d --wait postgres redis
docker compose run --build --rm backend python -m alembic upgrade head
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c backend/requirements-dev.lock -e './backend[dev]'
.\.venv\Scripts\python.exe -m uvicorn csrs.main:create_app --factory --app-dir backend/src --env-file .env --reload --reload-dir backend/src
```

In another terminal at the repository root:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run dev
```

On POSIX use `.venv/bin/python` and `npm` instead. Settings do not implicitly search for
`.env`: the server command above explicitly loads it. Compose overrides host connection URLs
with container service DNS names. Never pass database credentials to the frontend.

Backend checks from the repository root:

```powershell
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m ruff format --check backend
.\.venv\Scripts\python.exe -m pytest backend/tests -m 'not integration'
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini heads
```

Host PostgreSQL integration checks:

```powershell
docker compose --profile test up -d --wait postgres-test
$env:CSRS_TEST_DATABASE_URL = 'postgresql+psycopg://csrs_test:csrs_test_local_only@localhost:5433/csrs_test'
.\.venv\Scripts\python.exe -m pytest backend/tests/integration
```

On POSIX set the URL with `export CSRS_TEST_DATABASE_URL='...'`. The test database name must
end in `_test`. Treat that guard as an additional check, not permission to point at shared data.
Integration tests create disposable databases/schema/data on the test server. On Windows,
prefer containerized tests if host PostgreSQL port forwarding is unavailable; do not point
tests at the application database as a workaround.

Frontend verification:

```powershell
npm.cmd --prefix frontend run build
```

That runs strict TypeScript checking followed by a Vite build. There is no frontend unit-test
framework yet. The health screen has no business actions or authentication placeholders.

## Contracts and implementation decisions

- [Architecture and component responsibilities](docs/architecture.md)
- [Implemented relational foundation and constraints](docs/database.md)
- [Transactions, capacity invariant, states, expiration, and retries](docs/concurrency.md)
- [Anonymous and authenticated CSRF/session design](docs/security.md)
- [Implemented health/auth/events/reservations and planned dashboard API](docs/contracts/api.md)
- [Decision records](docs/decisions.md)
- [Phase gates and future concurrency evidence](docs/phases.md)
- [Completed Phase 1 validation](docs/phase-1-validation.md)
- [Phase 2 verification and limitations](docs/phase-2-validation.md)

To intentionally refresh the health and complete implemented OpenAPI after reviewing changes:

```powershell
.\.venv\Scripts\python.exe backend/scripts/export_health_contract.py
```

Tests detect differences between the checked-in specifications and runtime schema.
Alembic `heads` should show `0002_worker_expiry`; `current` and `check` verify the target database
has been migrated and matches model metadata. Downgrade is destructive and is exercised only
on disposable test databases. Never downgrade development data to test a migration.

## Authentication and local administration

Use a cookie-aware client against `/api/v1/auth/csrf` before registering/logging in. Send its
csrf_token as `X-CSRF-Token`, preserve the cookie, and send `Origin: http://localhost:5173`
on JSON mutations. Registration returns a new anonymous token and does not log in; login
returns a new authenticated token. Use the newly returned token after every rotation.
`GET /api/v1/auth/me` returns id/email/role; logout uses `POST /api/v1/auth/logout` with `{}`.
Passwords and session cookies never appear in response JSON. No public role selection exists.

Provision an organizer from an existing registered attendee through the local admin CLI:

```powershell
docker compose exec -T backend python -m csrs.cli promote-organizer attendee@example.com
docker compose exec -T backend python -m csrs.cli purge-sessions --batch-size 1000
```

Promotion revokes existing sessions; log in again. Cleanup deletes one bounded batch of
expired/revoked security sessions; repeat as needed. Host CLI commands support `--env-file .env`
before the subcommand. CLI access is administrative database access, not a public API.
Redis rate limiting and automatic cleanup scheduling are deferred; see the security limitations
in [Phase 2 verification](docs/phase-2-validation.md).

Python direct requirements are bounded in `pyproject.toml`; `requirements-dev.lock` constrains
resolved development versions. Frontend dependencies use `npm ci` and the committed lockfile.
Update constraints and locks intentionally and rerun checks. The current Starlette test client
uses `httpx2`; it is a development dependency, not an application HTTP integration.

## CI and security hygiene

GitHub Actions defines backend lint/format/unit/contract checks, required real PostgreSQL
integration tests, a frontend build, Docker image builds, and a Compose health/proxy smoke check.
The workflow also applies/checks development migrations and exercises migrations in isolated
PostgreSQL tests. Phase 4 is committed with green CI. Phase 5 checks run locally before review;
hosted CI for Phase 5 requires a later authorized commit/push. No deployment secret is required.

`.env`, local environments, package caches, build output, and common key files are ignored.
`.env.example` contains public local examples only. No production credentials are required.
Do not log settings dumps with revealed secret values or commit database backups.

Phase 4 includes reproducible PostgreSQL contention/failure tests with two independent API
processes. These establish the tested correctness scenarios; they are not production load
or latency/throughput measurements. Phase 4 is committed; Phase 5 changes remain uncommitted for review.

## Reservation API and retry keys

All paths use `/api/v1`. Hold, confirm, and cancel accept JSON `{}` and require the authenticated
cookie, trusted Origin, session-bound `X-CSRF-Token`, and `Idempotency-Key` (1-128 visible ASCII
characters without spaces). A successful hold returns 201; confirmation/cancellation return 200.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/events/{event_id}/holds` | Hold one seat for up to five minutes |
| POST | `/reservations/{reservation_id}/confirm` | Confirm an owned valid hold |
| POST | `/reservations/{reservation_id}/cancel` | Cancel an owned reservation |
| GET | `/reservations/{reservation_id}` | Read owned current effective state |
| GET | `/me/reservations` | Private paginated history, limit 20 by default, maximum 100 |
| GET | `/events/{event_id}/availability` | Public PUBLISHED-event advisory snapshot |

`CSRS_HOLD_TTL_SECONDS` defaults to 300 (range 1-3600). A hold is capped by the event's
booking deadline. Database time after the event lock decides validity; equality is expired.
Capacity edits reclaim due holds under that same lock. Closing stops new holds and preserves
valid confirmations. Terminal rows remain history.

Retain the **same key** after a lost response or uncertain 503/network outcome. Replays return
the original status/body and `Idempotency-Replayed: true`; new executions return false.
Fetch the reservation after replay to see current state. Stored business conflicts replay too;
a new intentional attempt uses a new key. Security/validation/transient database failures do
not create completed outcomes. No background expiration worker or key-retention cleanup exists.

Live Compose smoke with generated temporary accounts/event and scoped cleanup:

```powershell
docker compose exec -T backend python scripts/smoke_reservations.py
```

The helper is for the local environment and requires running backend, frontend proxy, and
migrations. It prints only status labels and restores the original application table counts.

## Expiration worker (Phase 5)

The independently runnable worker uses PostgreSQL and the shared event-lock protocol. It has
no HTTP listener and does not connect to Redis. The API contract/version remains 0.4.0.
The new partial index is installed by revision `0002_worker_expiry`; migrate before starting:

```powershell
docker compose exec -T backend python -m alembic upgrade head
docker compose --profile worker up --build -d worker
docker compose --profile worker logs --tail 20 worker
docker compose --profile worker stop worker
```

Host equivalent using the existing virtual environment and explicit configuration:

```powershell
.\.venv\Scripts\python.exe -m csrs.worker --env-file .env
```

The worker profile is opt-in, keeping ordinary Compose startup compatible with explicit
migrations. The worker uses the same PostgreSQL URL/image conventions as the API, restarts
unless stopped, and has a 20-second Compose stop grace period. SIGTERM/SIGINT request graceful
shutdown; active transactions finish, and forced termination rolls back uncommitted work.
If database timeout settings are raised, review the stop grace period accordingly.

| Setting | Default | Bounds/purpose |
| --- | --- | --- |
| CSRS_WORKER_POLL_INTERVAL_SECONDS | 15 | 0.05-3600 seconds while idle; catch-up delays are capped below |
| CSRS_WORKER_BATCH_SIZE | 100 | 1-1000 scanned entries per page and expired rows per event transaction |
| CSRS_WORKER_RETRY_INITIAL_SECONDS | 1 | 0.05-60 seconds; failure pacing and initial backoff |
| CSRS_WORKER_RETRY_MAX_SECONDS | 30 | 0.05-300 seconds; at least the initial delay |

Set these in .env or the worker's process environment. Existing Settings still requires a
valid Redis URL, but the worker never contacts it. Logs are JSON with event, timestamp, pid,
cycle counts, and sanitized error class/SQLSTATE. Settings, SQL text, and credentials are excluded.
Known database/connection/pool errors retry; unexpected errors terminate for operator attention.

Discovery reads a bounded index page without reservation locks. Each candidate event gets
FOR UPDATE SKIP LOCKED, a fresh database clock, bounded shared cleanup, and an atomic commit.
Busy events are deferred; fixed-cutoff keyset passes advance and wrap so a busy oldest group
cannot monopolize discovery. PostgreSQL holds unfinished work; restarting loses no expiration
obligation. Multiple workers can safely discover the same event. There is no fixed expiration
latency SLA: backlog size, configured page/row limits, and event lock availability matter.
After successful expiration, the worker scans again after at most 0.25 seconds. A productive
pass also wraps after at most 0.25 seconds so equal-deadline holds get another bounded chunk.
A full page containing only busy or stale candidates advances after at most one second; an
idle or unproductive completed pass uses the normal poll interval. These are delay caps,
not throughput or completion-time guarantees.

Live Compose recovery smoke (PowerShell, worker stopped while generating overdue test holds):

```powershell
docker compose --profile worker stop worker
$scenario = docker compose exec -T backend python scripts/smoke_worker.py prepare
docker compose --profile worker up -d worker
docker compose exec -T backend python scripts/smoke_worker.py verify $scenario
```

The local-only helper creates its own event/users, checks committed expiration/counter equality
and live API/proxy readiness plus availability, then removes only its generated records.
See [Phase 5 validation](docs/phase-5-validation.md) and the
[twelve-section explanation](docs/phase-explanations/phase-5-explanation.md) for evidence and limits.
