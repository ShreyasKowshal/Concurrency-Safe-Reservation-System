# Phase 1 validation record

Date: 2026-10-25. Environment: Windows, Python 3.12.10, Node.js 24.21.0, npm 11.19.0.
This file records actual local evidence; GitHub-hosted jobs have not been run.

## Completed checks

| Command/check | Actual result |
| --- | --- |
| `python -m ruff check backend` using the project venv | Passed |
| `python -m ruff format --check backend` using the project venv | Passed |
| `python -m pytest backend/tests -o faulthandler_timeout=15` using the project venv | 22 passed, 2 skipped |
| `python -m pip check` using the project venv | No broken requirements |
| `python -m alembic -c backend/alembic.ini heads` using the project venv | Exit 0; no revisions, as intended |
| `npm run build` in frontend | TypeScript and Vite build passed |
| `npm ci --offline --cache ../.cache/npm --audit=false` followed by `npm run build` | Lockfile-based reinstall and repeat build passed |
| Initial `npm install` audit | 0 reported vulnerabilities at installation time |
| Local HTTP smoke (temporary API/Vite processes, deliberately unreachable PostgreSQL) | Liveness 200; readiness 503; frontend 200; proxied readiness 503; unimplemented events route 404 |
| Parse Compose, workflow, and dependency-update YAML | All 3 parsed; syntax check only, not Compose semantic validation |
| Git ignore checks | Local env files, venv, caches, node_modules, and dist are excluded |
| Review source files for common private-key/cloud-token patterns | No matching credentials found; example DB passwords are explicitly public/local-only |
| Source/config/document whitespace review | 52 files reviewed; no trailing whitespace |

The 22 passing tests cover configuration, health responses using unit-test doubles, engine
disposal, absence of business routes, and health OpenAPI contract consistency. They do not
prove a successful live PostgreSQL connection. The 2 skipped tests require
`CSRS_TEST_DATABASE_URL` and real PostgreSQL; no replacement database was used.

## Environment issues resolved during validation

Initial package downloads were blocked by sandbox DNS. Project-local installation completed
after network access was allowed. Python temporary/cache paths were kept in the project for
installation. The current Starlette TestClient requires `httpx2`; the dev dependency was
updated after strict-warning test collection exposed the old client's deprecation.

Restricted Windows execution hung while creating asyncio's internal loopback socket, before
application code. Rerunning tests outside that restriction completed in under one second of
reported test time. The hung validation processes were stopped. This is not an application
workaround or a relaxation of test assertions.

## Outstanding acceptance exceptions

- Docker CLI/Desktop is not installed/available on this host (`docker --version` fails).
- No local PostgreSQL server/test URL was available. Both real-database tests are skipped.
- Docker image builds, Compose semantic validation, fresh stack startup, containerized tests,
  and PostgreSQL volume persistence have not been executed here.
- The GitHub Actions workflow is configured but has not run on GitHub.

Before declaring Phase 1 fully verified, use a Docker-enabled host to run the README setup,
the test-profile command, and the configured CI workflow. Verify readiness becomes 200 and
the UI proxy reports PostgreSQL up. PostgreSQL data persistence across normal down/up remains
an infrastructure check to perform there; no domain tables exist in this phase.

No cloud infrastructure was deployed or purchased. No authentication/event/reservation/cache
implementation or Phase 2 migration was started. No Git commit was created automatically.
