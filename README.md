# Concurrency-Safe Reservation System (CSRS)

A full-stack event/workshop reservation project focused on PostgreSQL transactions,
concurrent capacity allocation, idempotency, and failure recovery.

**Current implementation: Phase 1 only.** The API provides liveness/readiness checks and the
React app shows development-environment health. Authentication, CSRF enforcement, events,
reservations, Redis limiting/caching, and the expiration worker are not implemented yet.
Their contracts are documented for phased review. No cloud infrastructure is provisioned.

## Repository structure

```text
csrs/
  .github/                 # GitHub Actions and dependency update configuration
  backend/
    src/csrs/              # FastAPI application, settings, database engine, health routes
    migrations/            # Alembic runner/templates; no schema revisions yet
    scripts/               # Explicit health-contract exporter
    tests/unit/            # Configuration, health, and contract checks
    tests/integration/     # Real PostgreSQL health/isolation checks
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
Redis runs locally but is intentionally not queried by the Phase 1 application.

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

The runner executes all Pytest tests. Its database is `csrs_test` on the separate
`postgres-test` service with disposable storage. It never points at the application database.
No SQLite integration fallback exists. A configured but unreachable PostgreSQL server fails
the integration tests; only an absent test URL produces an explicit local skip.

## Optional host development

Use Python 3.12, Node.js 24, and npm. `.python-version` and `.nvmrc` record those runtime
choices. PostgreSQL and Redis can still be started through Compose:

```powershell
docker compose up -d --wait postgres redis
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
The current integration tests are read-only; later phases will create disposable schema/data.

Frontend verification:

```powershell
npm.cmd --prefix frontend run build
```

That runs strict TypeScript checking followed by a Vite build. There is no frontend unit-test
framework yet. The health screen has no business actions or authentication placeholders.

## Contracts and implementation decisions

- [Architecture and component responsibilities](docs/architecture.md)
- [Planned relational schema and constraints](docs/database.md)
- [Transactions, capacity invariant, states, expiration, and retries](docs/concurrency.md)
- [Anonymous and authenticated CSRF/session design](docs/security.md)
- [Implemented health and planned domain API](docs/contracts/api.md)
- [Decision records](docs/decisions.md)
- [Phase gates and future concurrency evidence](docs/phases.md)
- [Actual Phase 1 validation and outstanding blockers](docs/phase-1-validation.md)

To intentionally refresh the health OpenAPI after reviewing endpoint changes:

```powershell
.\.venv\Scripts\python.exe backend/scripts/export_health_contract.py
```

A test detects differences between the checked-in health contract and the runtime schema.
Alembic currently has no domain metadata/revisions; `heads` should print nothing. Do not run
autogeneration or create business tables until Phase 2 has been reviewed.

Python direct requirements are bounded in `pyproject.toml`; `requirements-dev.lock` constrains
resolved development versions. Frontend dependencies use `npm ci` and the committed lockfile.
Update constraints and locks intentionally and rerun checks. The current Starlette test client
uses `httpx2`; it is a development dependency, not an application HTTP integration.

## CI and security hygiene

GitHub Actions defines backend lint/format/unit/contract checks, required real PostgreSQL
integration tests, a frontend build, Docker image builds, and a Compose health/proxy smoke check.
The workflow is configured locally; a successful hosted GitHub run cannot be claimed before
the repository is pushed. There is no remote or deployment secret configured by this phase.

`.env`, local environments, package caches, build output, and common key files are ignored.
`.env.example` contains public local examples only. No production credentials are required.
Do not log settings dumps with revealed secret values or commit database backups.

Phase 1 does not establish reservation correctness or performance metrics. Those claims
require the later transaction implementation and reproducible PostgreSQL race/failure tests.
