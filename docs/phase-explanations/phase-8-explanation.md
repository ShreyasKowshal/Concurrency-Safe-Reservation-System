# Phase 8 explained: a reproducible local demonstration

This is the final planned implementation phase. The
[validation report](../phase-8-validation.md) records local results and finalization checks;
the [handoff](../PROJECT_HANDOFF.md) records publication and exact-commit hosted CI provenance.

## 1. Phase overview

The application already supported booking. Phase 8 makes it easier to start, demonstrate,
verify and explain. The owner chose localhost instead of public cloud hosting. Localhost means
the application runs on your own computer and is reached through addresses such as
`http://localhost:5173`. Nobody needs a hosting subscription or cloud password to review it.

"Local production readiness" here means disciplined local startup/recovery and honest evidence.
It does not mean the application has been hardened, operated or load-tested on the public web.

## 2. What we implemented

- One-command startup of frontend, API, PostgreSQL, Redis and expiration worker.
- A dedicated migration step before API/worker startup, with a PostgreSQL advisory lock.
- Frontend HTTP health checking, restart policies and stable API operation without reload.
- Explicit demo setup with a private password prompt, UUID scope and guarded cleanup.
- Separate-project service restart, persistence and dependency-outage verification.
- Read-only SQL reconciliation, reproducible evidence and interview/demo/future-hosting guides.
- A production guard against reusing known public example database passwords.

Existing booking transactions, constraints and Redis failure policies remain authoritative.

## 3. Technologies used

| Technology | Plain-language role |
| --- | --- |
| Docker | Packages each service with its runtime so the host needs less manual setup |
| Docker Compose | Starts related containers and waits for their dependencies/health checks |
| PostgreSQL volume | Keeps the database files after ordinary container removal |
| Alembic | Applies the repository's versioned schema changes |
| Advisory transaction lock | Makes cooperating migration runners take turns in one database |
| PowerShell | Provides short local startup/shutdown and isolated recovery commands |
| Pytest | Checks the real database protocol and fixture/migration safety |
| Playwright/axe | Exercises the real website, browser recovery, layout and accessibility basics |

The application still uses React/TypeScript, FastAPI/SQLAlchemy, PostgreSQL and Redis.

## 4. How everything works

`./scripts/local.ps1 start` checks Docker and preserves an existing `.env`. On a fresh clone
it copies the labeled local example configuration. PostgreSQL starts with a named volume.
The one-shot migration container waits for PostgreSQL health, takes a database lock, upgrades
Alembic and verifies no schema drift. Only after success do API and worker start. Frontend
startup waits for the API and its HTTP health probe verifies the page is reachable.

The browser contacts the local Vite server. Its `/api` proxy passes requests to FastAPI while
preserving Origin. FastAPI talks to PostgreSQL and uses Redis only for quotas/public metadata.
The worker talks directly to PostgreSQL and does not need an API request or Redis connection.

Stopping with `./scripts/local.ps1 stop` removes containers/network, but keeps database storage.
Starting again reads the same ledger. Deleting a volume would be different and is deliberately
absent from normal startup/shutdown and recovery scripts.

## 5. Important files and folders

| Path | Responsibility |
| --- | --- |
| compose.yaml | Services, health, migration dependency, worker profile and persistent volume |
| compose.validation.yaml | Removes published ports for a separate recovery test project |
| scripts/local.ps1 | Start, stop and inspect the full local stack |
| scripts/verify-local.ps1 | Generate an isolated project and test real restart/outage recovery |
| backend/src/csrs/migrate.py | Transactional serialized startup migration and drift check |
| backend/src/csrs/demo.py | Explicit demo accounts/events and scope-validated cleanup |
| backend/scripts/smoke_recovery.py | Durable session/replay/expiration assertions across restarts |
| backend/scripts/reconcile.sql | Read-only counter, uniqueness and incomplete-claim checks |
| docs/DEMO_GUIDE.md | Preparation, five-minute demo, deeper demonstrations and troubleshooting |
| docs/INTERVIEW_GUIDE.md | Beginner-friendly explanations and interview questions |
| docs/FUTURE_DEPLOYMENT.md | Later hosting work, clearly separated from implemented local behavior |
| docs/evidence/ | Sanitized results/captures with their provenance and reproduction instructions |

## 6. API endpoints and running the system

No business endpoint or OpenAPI shape is added in Phase 8. Existing health, authentication,
events, reservations and owner dashboard endpoints remain at `/api/v1`.

```powershell
./scripts/local.ps1 start
./scripts/local.ps1 status
./scripts/local.ps1 stop
```

Open `http://localhost:5173` for the UI and `http://localhost:8000/docs` for API documentation.
The [demo guide](../DEMO_GUIDE.md) includes exact fixture and verification commands.
The worker remains an explicit Compose profile, enabled by the full-stack startup command.

## 7. Database design

There are still five application tables. No new migration is needed; Alembic head remains
`0002_worker_expiry`. PostgreSQL keeps accounts, sessions, events, reservations, counters,
deadlines and retry outcomes. Redis is ephemeral and can restart with an empty cache/quota set.

For example, a confirmed reservation stays confirmed after API/PostgreSQL container restart.
Replaying its original hold key can return the original HELD body, so the browser then reads
its current CONFIRMED state. This demonstrates both durable retry history and current truth.
Read-only reconciliation checks the counter equals persisted HELD plus CONFIRMED rows.

## 8. Security and correctness

Published container ports bind to loopback. Example database credentials are explicitly local;
production settings reject those known examples and require an HTTPS origin. That guard does
not replace future secret rotation, least privilege, TLS and deployment review.

Demo accounts are explicitly created with a privately entered password. They use deterministic
UUID ownership boundaries. Repeated setup preserves them; cleanup refuses identity collisions
and reservations crossing into other accounts/events. Tests use separate generated databases.
The recovery verifier creates its own project/volume and never deletes the normal app's data.

Authentication, exact-origin CSRF, role/ownership, event locks, database-clock deadlines,
idempotency and single-release transitions are preserved. Redis outage cannot grant a seat.

## 9. Testing and verification

The complete suite retains real PostgreSQL contention, exact deadline, rollback, response-loss,
worker/crash and Redis cases. New tests prove migration serialization/rollback, safe repeatable
demo setup and cleanup guards. Browser journeys use real backend responses, session restoration,
actual session expiry, concurrent final-seat admission and lost-response same-key recovery.

The separate recovery project restarts services, stops/restarts dependencies and performs
ordinary down/up with persistent data. It checks stored sessions, replay bodies, confirmed rows,
overdue worker cleanup and SQL counters. A passing health check alone is not that evidence.

GitHub Actions runs the added checks on publication. The handoff records actual exact-commit
hosted conclusions; local passing results alone never establish a green hosted run.

## 10. What was NOT implemented yet

Public cloud hosting, a production static/proxy tier, managed services, HTTPS termination,
backup/restore operations, production alerts and load benchmarks remain future work.
Payments, email/SMS, seat maps, waitlists and new business features remain outside scope.
Non-Chromium browsers, physical devices and manual screen readers need further verification.

Cloud is optional for this portfolio demonstration. Later deployment can reuse the transaction
protocol, but requires the concrete infrastructure/security work in the future-deployment guide.

## 11. Interview preparation

Show why starting five containers is not enough: schema readiness, a reachable frontend and
worker progress must also be checked. Explain that a persistent volume preserves database
files while Redis contents are disposable. Show a final-seat race and its SQL reconciliation,
then explain why it proves that workload's correctness rather than production scalability.

Explain why startup migration runs separately, why the worker can recover overdue rows after
being stopped, and why a lost HTTP response requires the same key. Use the interview guide
for short answers about event locks, post-lock time, CSRF, quotas and tradeoffs.

## 12. Phase summary

CSRS can now be launched and demonstrated locally with a short, documented procedure.
PostgreSQL remains the durable reservation ledger.
The independent worker recovers unfinished expiration work.
Redis supports the application without owning seats.
Safe fixtures and isolated recovery tests make demonstrations reproducible.
Evidence and interview guides explain what was actually verified and what remains untested.
Cloud deployment is deferred; the handoff identifies the verified publication state.
