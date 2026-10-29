# Phase 1 validation record

Final independent verification date: 2026-10-25 (Asia/Calcutta).
Implementation tested: `ed939ad6e6b2ab53e9051ab53a76b8a89918a6fa` on `main`.

**Phase 1 verification passed.** The earlier Docker/PostgreSQL and hosted-CI acceptance
exceptions are resolved. This update records verification evidence only; no application,
infrastructure configuration, dependency, or migration changes were required.

## Environment

| Component | Observed version |
| --- | --- |
| Host | Windows with Docker Desktop's Linux/WSL2 engine |
| Docker Desktop / Engine | 4.96.3 / 29.9.2 |
| Docker Compose | 5.6.1 |
| Container Python / Pytest | 3.12.15 / 9.1.1 |
| PostgreSQL | 17.11 |
| Redis | 7.4.11 |
| Container Node.js / npm | 24.22.1 / 11.19.1 |
| Vite | 7.3.7 |

The CLI was found under the user's Docker Desktop installation. Its bin directory was
added to the validation process PATH only; repository configuration was not changed.
Docker engine access required execution outside the restricted Windows named-pipe sandbox.

## Independently rerun checks

All commands ran from the repository root against the existing local `.env`. Connection
secrets and expanded Compose configuration were not printed or committed.

| Command/check | Actual result |
| --- | --- |
| Docker client/server version query | Connected successfully to the Linux engine; exit 0 |
| `docker compose config --quiet` | Semantic configuration validation passed; exit 0 |
| `docker compose up --build -d --wait --wait-timeout 120` | Backend/frontend image builds and development startup passed; exit 0 |
| `docker compose --profile test run --build --rm backend-test` | **24 passed in 0.65s**; process exit **0**; no skips or failures |
| `docker compose exec -T backend python -m ruff check --no-cache .` | All checks passed; exit 0 |
| `docker compose exec -T backend python -m ruff format --check --no-cache .` | 13 files already formatted; exit 0 |
| `docker compose exec -T backend python -m pip check` | No broken requirements; exit 0 |
| `docker compose exec -T backend python -m alembic heads` | Exit 0; no schema revisions, as intended |
| `docker compose exec -T frontend npm run build` | Strict TypeScript check and Vite build passed; exit 0 |
| `docker compose exec -T redis redis-cli ping` | PONG; exit 0 |

The full test run used the separate `postgres-test` PostgreSQL service and included both
integration tests: readiness against real PostgreSQL and PostgreSQL/READ COMMITTED verification.
It also ran all 22 configuration, health, and contract tests. No SQLite fallback or mocked
database was substituted for the integration tests. The elapsed time is Pytest's reported
test duration, not a reservation performance measurement.

## HTTP and development service verification

Every endpoint below returned **HTTP 200 both before and after the PostgreSQL restart**:

- `http://localhost:8000/api/v1/health/live`
- `http://localhost:8000/api/v1/health/ready`
- `http://localhost:8000/docs`
- `http://localhost:8000/openapi.json`
- `http://localhost:5173/`
- `http://localhost:5173/api/v1/health/live`
- `http://localhost:5173/api/v1/health/ready`
- `http://localhost:5173/src/main.tsx`

Liveness returned `{"status":"alive"}`. Both direct and proxied readiness returned
`{"status":"ready","dependencies":{"postgresql":"up"}}` with `Cache-Control: no-store`.
The OpenAPI document exposed only the two planned Phase 1 health routes. The frontend
HTML and transformed entry module were served successfully.

Final service state:

| Service | State | Health evidence |
| --- | --- | --- |
| backend | Running | Docker healthcheck healthy; direct and proxied readiness pass |
| postgres | Running | Docker healthcheck healthy; read-only SQL succeeds |
| redis | Running | Docker healthcheck healthy; PONG |
| frontend | Running | HTTP checks pass; no Docker healthcheck is configured |
| postgres-test | Running | Docker healthcheck healthy; full integration suite passes |

Compose's wait output can label a running service healthy even without a configured probe.
The frontend's Docker health field is empty; its availability was independently checked by HTTP.

## Read-only PostgreSQL persistence check

The development PostgreSQL service was restarted safely with:

```text
docker compose restart --timeout 30 postgres
```

Before and after the restart, `psql` executed catalog queries inside a
`REPEATABLE READ READ ONLY` transaction. The snapshot checked `pg_control_system()`,
`pg_database`, `pg_class`/`pg_namespace`, `pg_postmaster_start_time()`, and the current database.
Container inspection independently checked the named volume and data-directory mount.

| Observation | Before | After |
| --- | --- | --- |
| PostgreSQL server start, UTC | 2026-10-25 12:58:39.559375+00 | 2026-10-25 13:07:22.923215+00 |
| Cluster system identifier | 7700589106042421282 | 7700589106042421282 |
| Development database / OID | csrs / 16384 | csrs / 16384 |
| Database catalog comparison fingerprint | d9ee277b91859db15cc09b6d4aa1bfc3 | d9ee277b91859db15cc09b6d4aa1bfc3 |
| Public relation comparison fingerprint | d41d8cd98f00b204e9800998ecf8427e | d41d8cd98f00b204e9800998ecf8427e |
| Public relations | 0 | 0 |
| Named volume | csrs_postgres_data | csrs_postgres_data |
| Mount destination | /var/lib/postgresql/data | /var/lib/postgresql/data |
| Snapshot transaction_read_only | on | on |

The catalog fingerprint was MD5 of ordered database OID/name/encoding/collation metadata;
the public relation fingerprint was MD5 of ordered public relation OID/name/kind metadata.
The changed server start time proves an actual restart; unchanged identity, metadata,
container ID, and volume attachment confirm the existing cluster was retained. The database
became healthy and HTTP readiness recovered afterward.

No volumes were removed, no initialization was repeated, and no application rows, schema,
temporary marker tables, or verification databases were created or changed. Phase 1 has no
application tables, so this verifies existing cluster/catalog persistence across a restart,
not business-data backup/restore or disaster recovery.

## GitHub Actions

The original **Foundation CI** run for the implementation commit was independently queried
using GitHub's API with existing Git authentication. Credentials remained in process memory
and were not logged or written to the repository.

- Run: [Foundation CI 40193506937](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40193506937)
- Head: `ed939ad6e6b2ab53e9051ab53a76b8a89918a6fa`
- Workflow: completed, success.
- Jobs: backend, frontend, and compose all completed successfully.

This confirms the original implementation workflow. The subsequent documentation commit
triggers a separate run; that run is not the evidence cited above.

## Repository hygiene and scope

Before editing this record, the working tree was clean and `main` matched `origin/main`.
Only this documentation file is intended for the verification commit. Existing ignore rules
exclude `.env`, local environments/caches, generated frontend output, and common key files.
PostgreSQL data remains outside Git in the named Docker volume.

The earlier host-only foundation run produced 22 passed / 2 skipped because Docker/PostgreSQL
were unavailable then. That historical limitation is superseded by the complete real-PostgreSQL
run above. Initial DNS and Windows asyncio sandbox restrictions did not require application
changes; no test assertions were weakened.

There are no remaining Phase 1 verification blockers. No paid infrastructure was deployed,
and no authentication, event, reservation, Redis caching, worker, or Phase 2 schema work was started.
