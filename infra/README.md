# Local infrastructure

The full localhost stack is frontend/Vite, FastAPI, PostgreSQL, Redis and an independent
expiration worker. Run `./scripts/local.ps1 start`, or after preparing `.env`,
`docker compose --profile worker up --build -d --wait --wait-timeout 180`.

PostgreSQL health gates the one-shot `migrate` service. Its database advisory transaction
lock serializes cooperating migration attempts; upgrade and drift check share the connection
and transaction. API/worker wait for migration success. API health gates frontend startup;
frontend has an HTTP health probe. A completed migration container with exit code 0 is normal.
The API process itself never applies schema migrations.

API reload is disabled for stable demos. Restart backend/worker after Python source edits;
rebuild after dependencies change. Vite supports local frontend edits and synchronizes its
named node_modules volume with npm ci at startup. These are local development/test images,
not hardened public deployment images.

PostgreSQL uses postgres_data. `./scripts/local.ps1 stop` includes worker/test profiles and
preserves named volumes. Never use volume deletion as ordinary shutdown. Initialization
credentials in POSTGRES_* apply only to an empty directory; changing .env does not rotate
an existing PostgreSQL password. Keep existing local credentials private.

All published ports bind to loopback. Public example passwords are local-only. Redis has
no local password, ephemeral data, 64 MiB maximum memory and noeviction; never expose it or
PostgreSQL to external networks. Production settings require HTTPS and reject known example
database passwords, but that does not constitute a complete public-deployment security policy.

The test profile has a separate PostgreSQL tmpfs service and dedicated Redis database 15.
Fixtures create/drop only generated csrs_phase2_*_test databases and scoped Redis keys.
The separate recovery verifier uses compose.validation.yaml and a fresh project/volume
without host ports. It verifies isolation before downtime experiments and never deletes volumes.

See [demo operations](../docs/DEMO_GUIDE.md), [local validation](../docs/phase-8-validation.md)
and [future deployment planning](../docs/FUTURE_DEPLOYMENT.md). Cloud hosting is deferred.
