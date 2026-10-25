# Concurrency-Safe Reservation System (CSRS)

A full-stack event/workshop reservation project focused on PostgreSQL transactions,
concurrent capacity allocation, idempotency, and failure recovery.

**Current implementation: Phase 2, pending review.** The API provides health checks,
registration/login/logout/current user, database-backed sessions, CSRF protection, and role
guards. Five PostgreSQL tables are managed by Alembic. The React app remains a health screen;
there is no authentication UI yet. Event management, booking operations, Redis limiting/caching,
and the expiration worker remain future phases. No cloud infrastructure is provisioned.

## Repository structure

```text
csrs/
  .github/                 # GitHub Actions and dependency update configuration
  backend/
    src/csrs/              # App, settings, models, auth services/guards, CLI, health/auth routes
    migrations/            # Alembic runner and 0001_foundation revision
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
    contracts/             # Implemented health OpenAPI and planned domain API
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
Redis runs locally but is intentionally not queried by the Phase 2 application. Apply the
migration before using authentication. Readiness still checks connectivity, not schema currency.
Migrations are explicit administrative steps, never automatic per-API-process startup work.

Stop services while preserving PostgreSQL data:

```powershell
docker compose down
```

Do not add `--volumes` unless intentionally discarding local data. Changing initialization
credentials does not change an already initialized PostgreSQL volume. See [infrastructure notes](infra/README.md).

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
- [Implemented health/auth and planned domain API](docs/contracts/api.md)
- [Decision records](docs/decisions.md)
- [Phase gates and future concurrency evidence](docs/phases.md)
- [Completed Phase 1 validation](docs/phase-1-validation.md)
- [Phase 2 verification and limitations](docs/phase-2-validation.md)

To intentionally refresh the health and complete implemented OpenAPI after reviewing changes:

```powershell
.\.venv\Scripts\python.exe backend/scripts/export_health_contract.py
```

Tests detect differences between the checked-in specifications and runtime schema.
Alembic `heads` should show `0001_foundation`; `current` and `check` verify the target database
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
PostgreSQL tests. Phase 1 hosted CI passed; Phase 2 hosted CI cannot run until the reviewed
changes are committed/pushed. No deployment secret is required for these checks.

`.env`, local environments, package caches, build output, and common key files are ignored.
`.env.example` contains public local examples only. No production credentials are required.
Do not log settings dumps with revealed secret values or commit database backups.

Phase 2 does not establish reservation correctness or performance metrics. Those claims
require the later transaction implementation and reproducible PostgreSQL race/failure tests.
