# CSRS interview demonstration

This guide demonstrates the localhost application. No cloud account, domain or hosting plan
is needed. Read [Phase 8 validation](phase-8-validation.md) for observed results and limits.
Commands below start in the repository root. Do not erase the PostgreSQL volume.

## Prepare before the interview

1. Install Git, Docker Desktop with Linux containers and Compose v2.24.4+.
   Install PowerShell 7 for the wrapper scripts. Node.js 24 is needed only for host browser
   tests; host Python is optional.
2. Open Docker Desktop from the Start menu and wait for its engine to show running.
3. Open PowerShell in the cloned repository and start everything:

   ```powershell
   ./scripts/local.ps1 start
   ./scripts/local.ps1 status
   docker compose logs --tail 20 migrate worker
   ```

4. Expect PostgreSQL, Redis, API and frontend healthy; worker running; migrate exited 0.
   Worker progress is a separate signal: inspect `worker_cycle` JSON and committed expiration.
5. Open [the application](http://localhost:5173/),
   [API readiness](http://localhost:8000/api/v1/health/ready) and
   [API docs](http://localhost:8000/docs). Use localhost, matching the configured trusted origin.

Startup copies `.env.example` only when `.env` is missing. It preserves local configuration
and database data. PostgreSQL health precedes serialized migrations, then API/worker startup;
frontend startup waits for API health. The default worker idle poll is 15 seconds and a hold
lasts at most 300 seconds. They are configurable in `.env`.

## Create isolated sample data

Choose and record a fresh demo scope once. This UUID identifies accounts created solely for
the demonstration; it is not a password or access token.

```powershell
$demoScope = [guid]::NewGuid().ToString()
$demoScope
docker compose exec backend python -m csrs.demo prepare --scope $demoScope
```

Use interactive `exec` here, without `-T`, so the password prompt is private. Choose a new
15-128 character local demo password and repeat it. Do not put it in a command, environment
variable, screenshot, Git file or chat. Setup prints three synthetic account addresses and
three event IDs; it does not print the password. The accounts are organizer, attendee and
rival. They share the privately supplied demo password solely for this local fixture.
Never reuse a personal password.

Setup creates a published 20-seat workshop, a published final-seat event and a draft, scheduled
relative to current PostgreSQL time. Repeating prepare with the same UUID preserves existing
passwords, schedules, reservations and edits. It does not reset an old interview's bookings.
Use a fresh scope for a fresh demonstration, or safely clean/recreate the old scope.

```powershell
docker compose exec -T backend python -m csrs.demo status --scope $demoScope
```

Use two browser profiles or a normal/private window for attendee and organizer accounts.
Avoid many rapid login/registration retries: the real combined quota is 10 per peer/minute.
The Vite proxy means local browser users share that peer quota.

## Five-minute walkthrough

| Time | Action | Explain |
| --- | --- | --- |
| 0:00-0:40 | Browse discovery and open the demo workshop | Public metadata and advisory availability come from real APIs |
| 0:40-1:50 | Organizer login, Organizer, Create an event, fill future schedule/capacity, Create draft, edit location/capacity, Publish | Role/ownership and lifecycle are enforced by FastAPI; publication makes the event public |
| 1:50-2:40 | Attendee login in another browser profile, open that event, Hold one seat | A PostgreSQL transaction decides admission; the countdown is an estimate |
| 2:40-3:20 | Reload the hold page, then Confirm reservation | The session and reservation persist; confirmation does not allocate a second seat |
| 3:20-4:00 | Open My reservations, inspect the confirmed row | Private history comes from the backend, including after reload |
| 4:00-4:40 | Organizer opens owned event dashboard | Stored allocation and valid/overdue holds are explicitly distinguished |
| 4:40-5:00 | Attendee cancels through the confirmation dialog; refresh availability | Cancellation releases once; displayed availability never promises a future allocation |

When explaining closure, note that it prevents new holds without cancelling valid existing
holds or confirmed reservations. Closed events disappear from public detail; private history
retains an event-ID fallback. Public registration creates only attendees; sample organizer
access is explicit local administration.

## Optional technical demonstration

### Final-seat races, duplicate keys and same-user uniqueness

These commands use the existing real PostgreSQL test infrastructure, two independent Uvicorn
processes, separate sessions and bounded pools. They create/drop only generated disposable
databases on `postgres-test`; quotas are intentionally disabled in these SQL correctness
fixtures so a 429 cannot masquerade as a capacity decision.

```powershell
docker compose --profile test run --build --rm backend-test python -m pytest tests/integration/test_reservation_transactions.py -k 'final_seats_across_two_api_processes or concurrent_duplicates_across_api_processes' -q -s -p no:cacheprovider
```

Read the structured scenario lines. Capacity 1/50 attempts must produce 1 created and
49 EVENT_FULL; capacity 20/100 attempts must produce 20 created and 80 EVENT_FULL.
Ten matching-key requests must produce one new execution and nine replays of one reservation.
Ten same-user/different-key requests must produce one allocation and nine
ACTIVE_RESERVATION_EXISTS conflicts. The different-path case also verifies fingerprint reuse.
SQL assertions reconcile counters, bounds, active uniqueness and completed claims.
This is a fixed correctness exercise, not a production traffic benchmark.

Show `backend/src/csrs/reservations/service.py`: claim key, lock event `FOR UPDATE`, refresh
authorization, sample `clock_timestamp()`, expire due holds, update state/counter/outcome,
commit. Explain why two API processes still agree: they lock the same PostgreSQL row.

### Worker expiration without waiting five minutes

The integration/process tests cover exact boundaries, repeated sweeps, confirmed preservation,
worker overlap, actual process crashes, rollback, restart, overdue work and SQL reconciliation:

```powershell
docker compose --profile test run --rm backend-test python -m pytest tests/integration/test_worker.py tests/integration/test_worker_processes.py -q -p no:cacheprovider
```

For a visible local backlog demo, stop only the worker, prepare generated overdue holds,
restart it and verify committed results. Run on a quiet local stack:

```powershell
docker compose --profile worker stop worker
$scenario = docker compose exec -T backend python scripts/smoke_worker.py prepare
docker compose --profile worker up -d worker
docker compose exec -T backend python scripts/smoke_worker.py verify $scenario
docker compose logs --tail 20 worker
```

The helper makes only its five generated holds overdue and cleans its six users/event after
verification. It observes EXPIRED and allocated 0 before calling availability; an API read
does not perform the expiration. Keep the UUID if interrupted and rerun verify after recovery.
For ordinary data, wait naturally for the configured deadline instead of editing SQL.

### Redis and restart recovery without disturbing your demo

```powershell
./scripts/verify-local.ps1
```

This creates a separate project with a separate database volume and no published ports.
It exercises service restarts, ordinary down/up, a persistent authenticated session, exact
same-key replay, preserved confirmed reservation, overdue worker recovery, and real Redis
stop/cold API start/recovery. Read the PASS lines and JSON, not secrets or raw session state.
The verifier retains isolated volumes and stops its own containers. The normal `csrs`
application is unaffected. Initial builds can take several minutes; prepare before an interview.

The dedicated Redis suite separately proves all four quota scopes, 429/503, real TTL expiry,
cache hit/miss/fallback, SQL publication gating, invalidation and independent-process behavior:

```powershell
docker compose --profile test run --rm backend-test python -m pytest -m redis -q -p no:cacheprovider
```

### Read-only SQL reconciliation

```powershell
Get-Content backend/scripts/reconcile.sql | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
```

Expect zero counter/bounds mismatches, duplicate active pairs and incomplete idempotency claims.
The transaction uses one read-only repeatable-read snapshot. Persisted overdue HELD counts
until a worker/request commits the matching transition; advisory availability can differ.

## Cleanup and shutdown

Log out of demo browsers. Preview status, then remove only the selected demo scope:

```powershell
docker compose exec -T backend python -m csrs.demo status --scope $demoScope
docker compose exec -T backend python -m csrs.demo cleanup --scope $demoScope
./scripts/local.ps1 stop
```

Cleanup validates deterministic UUIDs and account addresses, locks demo events before removing
reservations, and refuses identity collisions or bookings involving other accounts/events.
Events created by that scoped organizer during the walkthrough are included. Do not use a
demo account to book genuine events. Cleanup does not truncate tables or delete a volume.
Anonymous pre-sessions not owned by the demo accounts expire normally; bounded session purge
is the existing administrative maintenance command in README. Account removal invalidates
their sessions. Rerunning cleanup is safe.

## Troubleshooting

| Symptom | Check and recovery |
| --- | --- |
| Docker not found/engine unavailable | Start Docker Desktop, use Linux containers, reopen terminal; `docker version` must show Server |
| Port already in use | Check `docker compose ps -a` and the other application; free the conflicting port before startup |
| Container unhealthy | `docker compose logs --tail 50 postgres migrate backend frontend worker`; inspect the first failure |
| Migration exited nonzero | Check PostgreSQL credentials/history and competing migration; rerun `docker compose run --rm migrate` after fixing the cause; do not downgrade/reset development data |
| PostgreSQL authentication failed | `.env` must match credentials in the existing volume; changing initialization variables does not rotate them |
| Backend delay | Wait for readiness and inspect logs; startup gates traffic on migrations and DB health |
| Redis unavailable; login 503 | `docker compose up -d --wait redis`; public reads/authenticated commands still use PostgreSQL |
| Worker absent/no cleanup | Start with `--profile worker`; inspect `worker_cycle` and `worker_backoff`; verify DB health and schema |
| CSRF/origin failure | Use `http://localhost:5173`; match `CSRS_PUBLIC_ORIGIN`; refresh the security token/login; do not weaken source checks |
| Expired session | Log in again; inspect private history before retrying a booking |
| Stale page or approximate timer | Reload; use the authoritative reservation status; countdown and availability are advisory |
| Backend edits not visible | `docker compose restart backend worker`; normal API reload is disabled |
| Dependency changes | Rerun `./scripts/local.ps1 start` to rebuild; frontend startup synchronizes its dependency volume |
| Isolated verifier failure | It prints its project name and returns failure; inspect that project's logs/retained volume, not the application database |

Do not expose PostgreSQL or Redis publicly to troubleshoot local connectivity. See
[future deployment](FUTURE_DEPLOYMENT.md) for the distinct hosting requirements.
