# Infrastructure boundary

`compose.yaml` at the repository root is the local development entry point. Dockerfiles
live in `backend/` and `frontend/`. The backend uses the repository root as its build context
so the same contract documentation is available to containerized tests. This directory holds
infrastructure notes and, in Phase 8, reviewed deployment configuration.

There is no cloud provisioning, paid service, deployment credential, expiration worker,
Celery broker, or production deployment in Phase 1. Redis is started for later phases
but the application does not connect to it yet.

PostgreSQL uses a named volume; normal `docker compose down` preserves it. Never use
`down --volumes` unless intentionally discarding local data. The test profile uses a
separate PostgreSQL service backed by temporary memory storage.

All host ports bind to loopback. The development PostgreSQL password is a public example.
Use it only on the local Compose network/loopback. Redis has no password locally and must
not be exposed beyond this development environment.

Do not change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` expecting an existing
database volume to be reinitialized: PostgreSQL image initialization applies only to an
empty data directory. Plan a migration or consciously recreate disposable development data.

Node dependency volume: the frontend entry command runs `npm ci` to synchronize the named
`node_modules` volume with the lockfile. Backend dependency changes require an image rebuild.
