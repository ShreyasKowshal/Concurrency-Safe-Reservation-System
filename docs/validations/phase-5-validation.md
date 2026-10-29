# Phase 5: expiration worker and recovery validation

Date: 2026-10-26, Asia/Calcutta. Baseline: `592ab46bad385c58f1964a21fc9fc4bb00c9d791`
on main; Phase 4 implementation is `50cca058987a72adf4ac575b28cdbdc4840ca685`.

**Implemented and verified locally; uncommitted and awaiting external review.** No commit,
push, merge, or Phase 6 work was performed. PROJECT_HANDOFF.md is unchanged and remains the
approved Phase 4 snapshot. Historical Phase 1-4 reports/explanations are unchanged.

## Features, lifecycle, and scope

The worker automatically persists expiration without an API request. It uses the existing
PostgreSQL/SQLAlchemy infrastructure and shared expiration transition. It supports independent
processes, bounded work, safe duplicate processing, restart, graceful signals, JSON logs,
and recoverable database errors with paced retries. No broker, Redis client, HTTP maintenance
endpoint, new dependency, or product feature was added. API/OpenAPI version remains 0.4.0,
with the existing 20 paths/22 operations and idempotency/security contracts unchanged.

Entry point: `python -m csrs.worker`, optionally `--env-file .env` for explicit host configuration.
The opt-in Compose worker uses the backend Dockerfile and the same PostgreSQL settings as the
API. It has no exposed port/HTTP health endpoint, restart unless-stopped, and a 20-second stop
grace period. Worker progress is verified through logs and committed database state, not merely
container Running status. Startup does not execute migrations or require a healthy HTTP API.

SIGTERM/SIGINT request stop. Idle/backoff waits wake immediately; the loop checks stop between
event transactions. An active transaction completes before clean exit; forced termination
rolls back unfinished work. Main disposes its engine and restores signal handlers on exit.
The process can start while database connections are unavailable and recover when restored.
Nonrecoverable programming/schema errors exit with a sanitized failure record.

## Scanning, batching, and transaction design

Discovery opens a read transaction, samples database time for an advisory cutoff, and reads
at most worker_batch_size HELD entries with deadline <= cutoff, ordered by (deadline,event_id).
It acquires no reservation locks and loads only a bounded page. Event IDs are deduplicated.
The existing partial `(hold_expires_at,event_id)` index supports this global page.

Navigation uses a keyset position plus a fixed cutoff for the pass. New future deadlines do
not extend that pass indefinitely. Discovery advances past busy groups and wraps after the
finite pass. Equal-deadline rows for one event can be passed together because their event is
already a candidate; later passes handle remaining chunks. The cursor is not durable work
state. A restart resets navigation and rediscovers unfinished work directly from PostgreSQL.
There is no global distributed claim, in-memory seat ownership, or Redis dependency.

The final audit's MEDIUM backlog-latency finding is resolved with adaptive pacing. The normal
configured poll interval applies to an idle or unproductive completed pass. After at least one
successful expiration, the next scan waits at most 0.25 seconds. A pass that made progress
also wraps after at most 0.25 seconds, so equal `(deadline,event_id)` rows skipped by the
cursor get another bounded transaction promptly. A full page of busy or stale candidates
scans ahead after at most one second, allowing later events to progress. If no work was
released by the end of that pass, the worker uses the normal poll interval rather than
spinning on an unavailable lock. Every wait is interruptible. Errors retain their separate
capped retry/backoff policy. These fixed caps are also limited by a shorter configured poll
interval; no new setting or schema change was needed.

For illustration, 10,000 equal-deadline holds on one event with batch size 100 require 100
productive pages and up to 99 empty cursor-wrap pages. With no contention, the prior 15-second
delay contributed approximately 49.5 minutes between the first and last chunks. The new
0.25-second catch-up cap contributes at most 49.5 seconds of deliberate waiting across those
198 intervals. This is a derivation from the algorithm, **not** a measured completion time or
production SLA; database execution, competing work, and failures add time.

For each candidate, expire_event opens an independent READ COMMITTED transaction:

1. SELECT the event FOR UPDATE SKIP LOCKED, populating fresh ORM state.
2. Defer a missing/busy event; never lock reservations first or wait indefinitely for its row.
3. Sample PostgreSQL clock_timestamp after lock acquisition.
4. Call shared expire_due_holds with an optional worker row limit. It selects due HELD IDs
   ordered by (hold_expires_at,id), updates only those still matching the conditional predicate,
   obtains changed IDs with RETURNING, and subtracts exactly that number from allocated_seats.
5. Flush and commit row/counter changes together; return the changed count only after commit.

The same batch setting caps discovery entries and expired rows per event transaction. A page
can process up to that many distinct events, each separately committed; it is not one large
multi-event transaction. API callers omit the optional limit, retaining their Phase 4 cleanup
behavior. Explicit constant HELD predicates retain partial-index eligibility for prepared plans.

Only the event lock coordinates capacity. A second worker may discover identical candidates,
but it either skips the held event or rereads its committed state later. Already EXPIRED,
CANCELLED, or CONFIRMED rows cannot release again. CLOSED events are included: closing does
not release their holds. Worker and API share event-before-reservation ordering, and worker
transactions neither create nor modify user idempotency outcomes.

Every committed reconciliation checks bounds and equality to persisted HELD plus CONFIRMED,
including overdue HELD until cleanup commits. Active-user uniqueness and absence of incomplete
request claims are also checked. Database CHECKs bound the counter; application protocol and
SQL reconciliation establish cross-table equality for the tested scenarios.

## Recovery, retry policy, and logging

Before-commit failure rolls back rows and counter. After-commit interruption leaves EXPIRED
rows; repeated processing changes zero rows. An uncertain commit can be retried using the
same conditional expiration transition. Discovery failures reset navigation safely.

OperationalError, InterfaceError, and pool timeout failures are recoverable. Each failed event
is paced by the initial retry delay so an already discovered page cannot cause a reconnect
burst. Later candidates remain eligible. Failed cycles use capped exponential backoff; success
resets it. All waits are interruptible, with no tight retry loop. Separate sessions ensure an
aborted transaction is not reused. Engine pool pre-ping handles stale pooled connections.

JSON records include timestamp, event, pid, cycle scanned/processed/expired/skipped/failed
counts, chosen next delay, and error class/SQLSTATE. Exception strings, SQL, URLs,
cookie/CSRF values, and settings
are excluded. A cycle metric is operational evidence, not capacity authority or a throughput
benchmark; an unknown commit acknowledgement can undercount reported work while state is safe.

## Configuration and commands

| Setting | Default | Bounds |
| --- | --- | --- |
| CSRS_WORKER_POLL_INTERVAL_SECONDS | 15 | 0.05-3600 seconds while idle; catch-up caps above |
| CSRS_WORKER_BATCH_SIZE | 100 | 1-1000 |
| CSRS_WORKER_RETRY_INITIAL_SECONDS | 1 | 0.05-60 seconds |
| CSRS_WORKER_RETRY_MAX_SECONDS | 30 | 0.05-300 seconds; >= initial |

Set values in .env or the worker process environment. Existing Settings still validates a
required Redis URL; the worker never contacts Redis. No implicit .env search was introduced.

```powershell
docker compose exec -T backend python -m alembic upgrade head
docker compose --profile worker up --build -d worker
docker compose --profile worker logs --tail 20 worker
docker compose --profile worker stop worker
.\.venv\Scripts\python.exe -m csrs.worker --env-file .env
```

Default database timeouts bound individual statements/connections, not total cycle latency.
If timeout settings increase, review the Compose stop grace period too. A forced stop still
rolls back unfinished work. The worker profile keeps ordinary startup/migration steps intact.

## Database changes and migrations

New revision **0002_worker_expiry**, parent 0001_foundation, creates only:

```sql
CREATE INDEX ix_reservations_event_held_expiry
ON reservations (event_id, hold_expires_at, id) WHERE status = 'HELD';
```

The global expiry index is retained. An event/status index cannot provide expiry/ID order;
the global expiry/event index can walk unrelated events. The new event-first index supports
ordered limited cleanup for a large event without sorting all its active rows. No columns,
tables, constraints, or business data are changed. Tests cover clean upgrade, metadata parity,
non-destructive reupgrade, explicit 0001-to-0002-to-0001 round trip preserving an existing row,
and drift. An EXPLAIN eligibility check confirms the ordered index can serve the cleanup.
This is ordinary transactional CREATE INDEX, not concurrent production index deployment.

## Actual verification results

Environment: Docker Desktop Linux containers on Windows, Python 3.12.15, PostgreSQL 17.11,
Pytest 9.1.1, Node 24.22.1, Vite 7.3.7. Existing dependency locks are unchanged. The dedicated
test database fixture creates generated `csrs_phase2_*_test` databases, never truncates the
configured input/development database, and removes its generated databases afterward.
Docker named-pipe access required executor escalation. No credential values were printed.

| Check/command | Actual result |
| --- | --- |
| `docker compose config --quiet` | Passed, exit 0 |
| Worker/API image builds and development stack startup | Passed; API, frontend, PostgreSQL, Redis, and opt-in worker coexist |
| Focused worker unit/integration/process run | 46 passed in 34.48s before the final extra cases, exit 0 |
| Audit-fix focused unit/PostgreSQL/process run | **20 passed in 8.41s**, exit 0; image rebuilt for the current code beforehand |
| `docker compose --profile test run --rm backend-test python -m pytest -q -p no:cacheprovider --tb=short` | **474 passed in 94.13s**, zero failures/skips, exit 0 |
| Full-suite breakdown | 130 unit/contract + 344 real PostgreSQL integration cases; 57 added to the earlier 417 |
| Dedicated `pytest -m integration` container run | **344 passed, 130 deselected in 142.22s**, exit 0 |
| Three fresh executions of five catch-up and independent-process contention checks | 5 passed each in 7.57s, 7.38s, and 7.38s; all exits 0 |
| Three fresh executions of registration contention, 100-attempt admission, two-worker overlap, and worker post-lock clock tests | 4 passed each in 14.01s, 13.48s, and 13.00s; all exits 0 |
| Host and container Ruff lint/format | All checks passed; host `backend` 57 and container workspace 84 Python files already formatted, exits 0 |
| Container `python -m pip check` | No broken requirements, exit 0 |
| Alembic upgrade/head/current/check | 0002_worker_expiry installed/current/head; no new upgrade operations, exits 0 |
| Full-suite API/OpenAPI equality and security checks | Passed; no API contract change or export required |
| Focused API/OpenAPI contract tests | 9 passed in 2.80s, exit 0 |
| Frontend `npm run typecheck` and `npm run build` | Passed; Vite 30 modules, final build 1.76s, exits 0 |
| Live stopped-worker backlog/start/verify | Five generated overdue holds persisted as EXPIRED; allocation 0, active-row equality, three live HTTP checks passed |
| Compose stop/restart | Graceful stop exit 0; restarted successfully |
| Existing live reservation smoke with worker running | 33 HTTP checks passed; original table counts restored |
| Final development database reconciliation | Zero counter mismatches, duplicate active user/event pairs, or incomplete idempotency claims; scoped smoke data cleaned |

Supplemental repetitions are not additional unique tests. Collection confirms the 130/344
breakdown; execution evidence is the actual full container run. Hosted CI for Phase 5 has not
run because changes remain uncommitted. CI configuration now includes the worker smoke, but
this report claims only its equivalent local execution, not an unpublished green Actions run.

### Concurrency and recovery evidence

| Required scenario | Evidence |
| --- | --- |
| Unvisited expiration, multiple due holds, unexpired/confirmed/terminal preservation | Actual PostgreSQL state-table tests and standalone CLI backlog run |
| Repeated sweeps and duplicate workers | Zero repeat release; two independent CLI processes gated after identical candidate pages |
| Independent-process event lock contention | One CLI worker pauses after row/counter flush while holding the event lock; another discovers the same committed candidate and reports SKIP LOCKED deferral before the first releases; after release exactly one expiration commits |
| Confirmation and cancellation races | API-first worker skip/stale recheck and worker-first observed API blocking; correct terminal outcomes |
| Capacity editing, event closure, request-time cleanup races | Both relevant lock orders; CLOSED holds reclaimed and request outcomes preserved |
| Exact deadline and post-lock time | -1/equality/+1 microsecond decisions plus a real transaction-start/deadline/clock ordering test |
| Crash before commit | Real child process killed after row/counter flush; PostgreSQL rollback preserves HELD/counter; fresh worker recovers |
| Interruption after commit | Child exits immediately after successful event transaction; restart does not release twice |
| Shutdown/restart | SIGTERM/SIGINT interrupt idle wait; SIGTERM during a controlled active transaction exits cleanly after commit |
| Temporary database outage | Connections denied to only the generated test database, its connections terminated, then access restored; startup/running worker survives and drains work |
| Recoverable statement timeout | A real PostgreSQL table lock triggers SQLSTATE 57014; the live worker backs off, then expires the hold after lock release |
| Backlog bounds and fairness | 17-row CLI backlog with two-row limits; busy oldest 12-row event does not starve a later five-row event; fixed pass cutoff tested |
| Invariants and uniqueness | Consistent SQL counter reconciliation, active-user uniqueness, and no incomplete request claims after races/recovery; all Phase 1-4 cases retained |

Coordination uses signals, pipes, transaction control, observed pg_blocking_pids, and committed
database/log observations. Short polling sleeps observe progress; they do not prove race order.
The outage experiment denies database connections rather than stopping the shared PostgreSQL
container. Crash hooks gate actual uncommitted or committed transactions; they are test-only.
There is no claim of arbitrary network-partition testing or production load performance.

The final audit's LOW coverage finding is resolved by the independent-process lock test above.
The earlier identical-candidate two-process test remains unchanged. Unit tests also check idle
polling, productive and equal-key wrap catch-up, full busy-page scan-ahead fairness, clean
shutdown during catch-up, and failure backoff followed by productive recovery. A real worker
process test drains five same-deadline holds in three bounded transactions separated by two
short cursor wraps while the normal poll interval is set to 60 seconds.

### Reproducing live recovery

```powershell
docker compose --profile worker stop worker
$scenario = docker compose exec -T backend python scripts/smoke_worker.py prepare
docker compose --profile worker up -d worker
docker compose exec -T backend python scripts/smoke_worker.py verify $scenario
docker compose --profile worker restart worker
docker compose exec -T backend python scripts/smoke_reservations.py
```

The local-only helper creates its own six users/event/five due holds while the worker is
stopped. Verification observes stored expiration and equality before live API/proxy readiness
and availability reads. It validates scenario ownership and deletes only generated records,
with event-first cleanup locking. It never truncates development tables or prints credentials.

## Problems encountered and fixes

- Initial focused collection failed because unit/integration files shared test_worker.py.
  The unit file was renamed test_worker_runtime.py; no warning/test was disabled.
- Initial full run: 463 passed, two failed. The registration test hit concurrent lazy
  FastAPI/Pydantic schema construction across TestClient apps. Clients and invalid-body schema
  warmup now run sequentially before the actual database race; the shared pre-session and
  assertions of exactly one user/one replacement session remain intact.
- A later full run had 466 passed and one concurrent-login failure from the same lazy
  FastAPI/Pydantic route setup. The login contenders now materialize invalid-body route
  metadata sequentially before racing valid requests; the one-success/one-rejection and
  one-authenticated-session assertions are unchanged. The worker cases passed in that run.
- The initial 100-attempt capacity test observed 20 created and 79 EVENT_FULL outcomes; one
  unexpected response was not retained by its old assertion. Concurrent image builds were
  active, but that log cannot establish the cause. Diagnostics now include unexpected outcomes,
  without weakening capacity/conflict assertions. The final full run and three targeted
  repetitions pass. Tests remain subject to configured infrastructure timeouts under overload.
- Initial live recovery drained the backlog but its Vite probe used an untrusted Host value.
  The helper now uses the configured browser host, matching the established smoke convention.
  Generated records were cleaned even on that failed probe; the corrected smoke passes.
- Review added pacing for failed events inside an already discovered page, preventing a
  reconnect burst during outage. A unit test proves the failed event cannot starve the next.
- Review retained static HELD predicates for partial-index eligibility. Reservation/API
  transitions, CSRF, ownership, and idempotency behavior remain unchanged and regressions pass.
- Final correctness audit found no BLOCKER or HIGH issue. Its MEDIUM backlog-latency finding
  led to productive catch-up and bounded busy-page scan-ahead; the LOW process-test finding
  led to a deterministic two-process event-lock hold/skip test. Existing duplicate-candidate
  coverage remains. The new focused, repeated, and full-suite results are recorded above.

## Changed-file manifest

**Eight added files:**

- `backend/src/csrs/worker.py`
- `backend/migrations/versions/0002_worker_expiry_bounded_event_cleanup.py`
- `backend/scripts/smoke_worker.py`
- `backend/tests/unit/test_worker_runtime.py`
- `backend/tests/integration/test_worker.py`
- `backend/tests/integration/test_worker_processes.py`
- `docs/validations/phase-5-validation.md`
- `docs/phase-explanations/phase-5-explanation.md`

**Sixteen modified files:**

- `.env.example`: worker configuration defaults.
- `.github/workflows/ci.yml`: worker startup/backlog/shutdown smoke and profile cleanup.
- `README.md`: entry point, configuration, migrations, lifecycle, local smoke, scope.
- `compose.yaml`: separate opt-in worker service.
- `backend/src/csrs/config.py`: validated poll/batch/retry settings.
- `backend/src/csrs/models.py`: partial ordered event-expiration index.
- `backend/src/csrs/reservations/transitions.py`: optional bounded cleanup, same conditional transition.
- `backend/tests/integration/conftest.py`: consistent multi-hold fixtures.
- `backend/tests/integration/test_auth.py`: schema setup before login race.
- `backend/tests/integration/test_migrations.py`: new head and data-preserving index round trip.
- `backend/tests/integration/test_auth_edges.py`: schema setup before registration race.
- `backend/tests/integration/test_reservation_transactions.py`: unexpected-response diagnostics only.
- `docs/architecture.md`: worker boundary, lifecycle, and diagram.
- `docs/concurrency.md`: implemented worker protocol and bounded cleanup.
- `docs/database.md`: new index/migration justification.
- `docs/decisions.md`: event-first bounded worker decisions.

Total: **24 files**. No frontend source, dependency lock, API contract snapshot, handoff, or
historical phase document changed. Local logs/tools/build artifacts are ignored, not staged.

## Limitations and acceptance checklist

Cleanup latency depends on poll interval, finite-pass navigation, backlog, and event lock
availability. A single large equal-deadline event needs repeated bounded transactions/passes;
there is no expiration-latency SLA or production throughput claim. Busy events are retried on
later passes; progress requires eventual database/lock availability. The optional row limit
bounds worker writes, not the existing API cleanup workload. One page can process multiple
bounded event transactions, so the whole cycle has no single request-latency bound.

Ordinary CREATE INDEX can block concurrent writes during migration; this is local development,
not an online production migration. No new worker health endpoint or production alerting exists.
Keep logs/progress visible and run one worker initially. Redis integration, business dashboard,
deployment, account recovery, payments, and idempotency retention cleanup remain deferred.

- [x] Independent worker expires unvisited holds using PostgreSQL and shared locked transitions.
- [x] Bounded indexed discovery and per-event changes; busy-group forward progress tested.
- [x] Multiple processes and all required API/worker races preserve state/counter invariants.
- [x] Exact deadlines and actual post-lock clock tested; confirmed rows never expire.
- [x] Real process crashes, restart/backlog, duplicate processing, and database recovery tested.
- [x] Clean startup, interruptible backoff, graceful signals, and sanitized structured logs.
- [x] Explicit migration, upgrade/downgrade/drift, unchanged API contracts, regression suite pass.
- [x] TypeScript/build, Compose, live worker/API, restart and reconciliation verified.
- [x] Beginner-friendly twelve-section explanation and complete validation/manifest supplied.
- [x] PROJECT_HANDOFF.md remains unchanged pending review; Phase 6 has not started.
- [x] Nothing staged, committed, pushed, or merged; stop here for external review.
