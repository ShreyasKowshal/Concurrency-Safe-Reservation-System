# Phase 4: concurrency-safe reservation verification

Baseline: `6eb9fbc` (`docs: add project handoff for phase 4`) on `main`.
Work/verification dates: 2026-10-25 to 2026-10-26, Asia/Calcutta.

**Implemented, tested, independently audited, and approved for publication.**
This document records final pre-commit evidence; publication was authorized on 2026-10-26
after strengthening the audit's one MEDIUM test-coverage finding. The final task report records
the resulting commit, push, remote equality, and GitHub Actions status.
No worker, Redis integration, business UI, or deployment was implemented.
The historical [handoff](../PROJECT_HANDOFF.md) and Phase 1-3 reports remain unchanged.

## Features and endpoint contracts

Phase 4 implements all three reservation commands plus their existing supporting read contracts.
Each reservation represents exactly one seat. A user can have one persisted HELD/CONFIRMED row
per event. Organizers retain attendee capabilities. Terminal rows remain history; rebooking
creates a new row with a new key.

All paths below have `/api/v1` prefix. Commands accept only JSON `{}` and require a valid
database-backed authenticated session, trusted Origin/Referer, matching X-CSRF-Token, and
exactly one Idempotency-Key (1-128 visible ASCII characters without spaces).

| Method/path | Success | Protection/representation |
| --- | --- | --- |
| POST `/events/{event_id}/holds` | 201 reservation | Attendee or organizer; locked admission |
| POST `/reservations/{reservation_id}/confirm` | 200 reservation | Stored reservation owner |
| POST `/reservations/{reservation_id}/cancel` | 200 reservation | Stored reservation owner |
| GET `/reservations/{reservation_id}` | 200 reservation | Owner-only effective state |
| GET `/me/reservations` | 200 items/next_cursor | Private `(created_at,id)` ascending history |
| GET `/events/{event_id}/availability` | 200 event_id/capacity/available_seats/as_of | Public PUBLISHED-only advisory snapshot |

Reservation fields are id, event_id, status, created_at, hold_expires_at, confirmed_at,
cancelled_at, expired_at, server_time. Timestamps normalize to UTC. History defaults to 20,
maximum 100, with bounded user-scoped keyset cursors. All responses use no-store.

GETs never mutate reservation state. An overdue persisted HELD projects as effective EXPIRED,
with null expired_at until cleanup. Availability uses one SQL statement/MVCC snapshot and
one materialized database time sample, counting valid HELD plus CONFIRMED; it is not cached
and never authorizes a later allocation. Dashboard remains unregistered.

Input failures use sanitized 422 detail. Existing error envelopes/codes cover 401 authentication,
403 CSRF/role, 404 missing/foreign private resources, 409 business conflicts, 415 media type,
and sanitized 503 database/timeouts. No Phase 6 rate limiter or 429 behavior was added.

## Database, transaction boundaries, and locking review

No table, constraint, index, or migration changed. The models file changed only its module
description. Alembic head/current remain **0001_foundation**; schema drift check passes.
The existing active-user partial unique index and user/key unique constraint remain defenses.
No dependency/lockfile changed; backend/API version advances to 0.4.0.

Each command owns one READ COMMITTED transaction and an independent SQLAlchemy Session:

1. Validate current session/user/CSRF and reservation ownership context.
2. INSERT a user-scoped idempotency claim with ON CONFLICT DO NOTHING RETURNING.
3. Refresh authorization after any unique-claim wait, including before replay.
4. For a new claim, SELECT the event FOR UPDATE with refreshed ORM state.
5. Recheck session expiry/revocation, user activity/role and stored ownership after the wait.
6. Sample PostgreSQL clock_timestamp once for the business decision.
7. Expire due HELD rows with UPDATE RETURNING; subtract the number actually changed.
8. Apply the command or form a business conflict; flush row/counter and completed response.
9. Commit everything together, then construct/send the HTTP response.

Lock order is **idempotency claim -> event -> reservation rows**. Confirm/cancel discover the
immutable event ID without locking the reservation and reread it after the event lock.
Reservation updates then acquire their row locks. No command spans events, holds a reservation
lock before an event lock, calls remote services, hashes passwords, or independently commits
cleanup. Event metadata/publication/close/capacity writes retain their Phase 3 event lock.

The shared expire_due_holds helper never commits. Capacity edits invoke it inside their owned
event transaction before comparing capacity with allocated_seats; useful cleanup commits even
if the reduction is refused. A CLOSED event remains read-only. Closing itself preserves holds.

Every committed test snapshot checks:

```text
allocated_seats = count(persisted HELD + CONFIRMED)
0 <= allocated_seats <= capacity
at most one active reservation per (user_id,event_id)
no committed incomplete idempotency claims
```

Counter-versus-row equality/bounds are checked in one SQL statement, not inconsistent reads
across concurrent commits. Overdue persisted HELD rows count until cleanup. The event CHECK
bounds the counter but cannot prove cross-table equality. Correctness assumes writers obey
this protocol; arbitrary administrator SQL can bypass it. Per-event serialization prevents
overselling across API processes and deliberately serializes a hot event. No deadlock appeared
in the executed scenarios; this is not a claim that arbitrary future lock orders are safe.

## Idempotency and failure behavior

Fingerprint = SHA-256 of canonical JSON containing POST, canonical UUID resource path, and
validated `{}`. Keys are user-wide across command paths. Current valid bodies are always
empty, so different-path tests exercise valid fingerprint mismatch; different nonempty bodies
are rejected before claiming a key.

PostgreSQL uniqueness arbitrates concurrent insert claims. Matching duplicates wait and replay
the original committed status/body with Idempotency-Replayed true. New execution sends false.
A different fingerprint returns 409 IDEMPOTENCY_KEY_REUSED without replacing the original.
Business conflicts such as EVENT_FULL/HOLD_EXPIRED are stored. Security, validation, missing/
foreign-resource failures and transient database failures do not complete a new claim.

The claim, mutation/counter, cleanup, and response share one transaction. No pending claim
commits independently. Records are retained in this MVP; there is no cleanup/key reuse policy.
Replayed bodies can be stale: fetch current reservation state afterward. A new intentional
attempt following a stored business conflict needs a new key.

Lost HTTP responses recover with the same key. Commit connection loss is uncertain; the
server never guesses rollback, generates a replacement key, or automatically retries. Tests
inject errors both before commit and after an acknowledged durable commit, recovering through
the same key in both cases. These model ambiguous client knowledge; they do not physically
cut a network connection during COMMIT. Statement timeout is exercised against a real held
PostgreSQL lock, returns 503, rolls back the claim, and permits the same-key retry.

## State transitions and time

CSRS_HOLD_TTL_SECONDS defaults to 300, configurable from 1 to 3600 seconds. Deadline is
min(decision_time + TTL, booking_closes_at). Admission requires PUBLISHED, decision_time strictly
before booking close, no active row after cleanup, and allocation strictly below capacity.

| Starting state | Command/condition | Ending state | Delta/result |
| --- | --- | --- | --- |
| No row | Admitted hold | HELD | +1, 201 |
| HELD | Confirm before deadline | CONFIRMED | 0, 200 |
| HELD | Confirm at/after deadline | EXPIRED | -1, stored 409 HOLD_EXPIRED |
| HELD | Cancel before deadline | CANCELLED | -1, 200 |
| HELD | Cancel at/after deadline | EXPIRED | -1, 200 |
| CONFIRMED | Confirm again | CONFIRMED | 0, 200, even after old deadline |
| CONFIRMED | Cancel before event start | CANCELLED | -1, 200; retain confirmed_at |
| CONFIRMED | Cancel at/after event start | CONFIRMED | 0, 409 CANCELLATION_CLOSED |
| CANCELLED/EXPIRED | Cancel again | Unchanged | 0, 200 |
| CANCELLED | Confirm | Unchanged | 0, 409 INVALID_RESERVATION_STATE |
| EXPIRED | Confirm | Unchanged | 0, 409 HOLD_EXPIRED |

Equality at the hold deadline is expired; equality at event start closes confirmed cancellation.
Confirmed rows never expire. Closing blocks new holds while valid existing holds can confirm.
One post-lock database decision instant determines transitions/timestamps; browser time and
transaction-start now() do not determine admission. A valid decision may commit after expiry.

## Deterministic concurrency and failure evidence

Test files: test_reservations.py (46 cases) and test_reservation_transactions.py (40 cases).
All execute real PostgreSQL; no SQLite or mocked lock proves concurrency. Controlled boundary
tests override only the decision clock while executing actual database writes. Real post-wait
tests separately use PostgreSQL clock_timestamp and observed lock state.

| Scenario | Observed/asserted final result |
| --- | --- |
| Capacity 1, 50 barrier-released HTTP attempts | Exactly 1 allocation, 49 EVENT_FULL |
| Capacity 20, 100 barrier-released HTTP attempts | Exactly 20 allocations, 80 EVENT_FULL |
| Ten concurrent same-user/same-key HTTP requests | One new execution, nine exact replays, one reservation |
| Ten concurrent same-user/different-key requests | One allocation, nine ACTIVE_RESERVATION_EXISTS |
| Same key concurrently used on two event paths | One claim/fingerprint wins; five matching 201 outcomes, five key-reuse conflicts; one allocation |
| Confirm versus cancel, both event-lock orderings | Final CANCELLED; exactly one release; cancelled-first confirm conflicts |
| Duplicate confirm/cancel, same and different keys | No double allocation/release; same-key replay preserved |
| Expiry cleanup versus confirm/cancel, both orderings | No expired confirmation or double release; terminal rows stay terminal |
| Hold deadline -1 microsecond/equality/+1 microsecond | Strict documented confirm/cancel outcomes and timestamps |
| Confirmed cancellation at event start boundaries | Strictly-before succeeds; equality/after returns CANCELLATION_CLOSED |
| Capacity reduction versus admission, both orderings | Reduction-first rejects admission; admission-first rejects unsafe reduction |
| Closing versus admission/valid confirmation | Closing blocks admission; valid held confirmation survives both orderings |
| Event lock wait with session/user/deadline/status changes | Fresh auth/time/state determines outcome; no stale allocation |
| Duplicate key wait with revocation | First authorized operation can finish; waiter rechecks and cannot replay |
| Due-hold effective reads/new admission/capacity edits | Read is write-free; actual cleanup releases once; same-user rebooking works |
| Fault after row/counter/outcome writes or before commit | New row/counter/key and any due cleanup roll back together |
| Lost response after commit before HTTP send | Same key recovers exactly one committed reservation |
| Simulated uncertain commit, committed/uncommitted cases | Same-key replay or new execution respectively; one final allocation |
| Real statement timeout during lock wait | Safe 503, no completed claim; same-key retry succeeds |
| Cross-user/private and malformed/security requests | 401/403/404/415/422 as documented; no unauthorized mutation |
| SQL reconciliation after contention | Bounds, persisted-count equality, uniqueness, completed claims all pass |

Process evidence uses multiprocessing spawn to start **two independent Uvicorn API processes**,
each with its own app/engine and default pool size 5 plus overflow 5. Client thread barriers
release 50/100 attempts together; active database connections are bounded by those pools,
not 50/100 pre-opened connections. Each request owns its database session/connection.
The test database role's PostgreSQL server uses its standard connection limits.

Other races coordinate with signals/explicit gates and poll pg_blocking_pids to observe the
expected real wait. Short polling sleeps observe lock state; arbitrary sleeps do not establish
operation order. Startup uses readiness pipes from the child API servers. The workload is
fixed, with generated UUID/email identities; no random workload seed or latency/throughput
claim applies. Environment is local Docker Desktop Linux containers on Windows, PostgreSQL
17.11, Python 3.12.15, Pytest 9.1.1, Node 24.22.1, Vite 7.3.7. Baseline SHA is above, with the
uncommitted change manifest below. This is a correctness workload, not Phase 8 load reporting.

## Verification commands and actual results

Commands run from repository root unless noted. Docker's executable directory was added to
the command PATH: C:\Users\ASUS\AppData\Local\Programs\DockerDesktop\resources\bin.
Access to the Docker named pipe required executor escalation; all checks then ran successfully.
No local credentials were printed or changed. No development volume was removed.

| Command/check | Final result |
| --- | --- |
| `docker compose config --quiet` | Passed, exit 0 |
| `docker compose up --build -d --wait --wait-timeout 120` | Built/recreated development app services; dependencies ready, exit 0 |
| Initial `docker compose --profile test run --build --rm backend-test python -m pytest -q -p no:cacheprovider --tb=short` | 417 passed in 51.81s, zero failures/skips, exit 0 |
| Host `python -m pytest backend/tests --collect-only -q -m 'not integration' -p no:cacheprovider` | 114/417 collected, 303 deselected, exit 0; collection only |
| Host `python -m pytest backend/tests --collect-only -q -m integration -p no:cacheprovider` | 303/417 collected, 114 deselected, exit 0; collection only |
| Host `python -m ruff check backend --no-cache` | All checks passed, exit 0 |
| Host `python -m ruff format --check backend --no-cache` | 51 Python files formatted, exit 0 |
| `docker compose exec -T backend python -m ruff check --no-cache .` | All checks passed, exit 0 |
| `docker compose exec -T backend python -m ruff format --check --no-cache .` | 51 files formatted, exit 0 |
| `docker compose exec -T backend python -m pip check` | No broken requirements, exit 0 |
| `docker compose exec -T backend python -m alembic heads` | 0001_foundation (head), exit 0 |
| `docker compose exec -T backend python -m alembic current` | 0001_foundation (head), exit 0 |
| `docker compose exec -T backend python -m alembic check` | No new upgrade operations detected, exit 0 |
| `docker compose exec -T frontend npm run typecheck` | Passed, exit 0 |
| `docker compose exec -T frontend npm run build` | TypeScript + Vite, 30 modules, passed in 1.93s, exit 0 |
| Host `python backend/scripts/export_health_contract.py` | Both OpenAPI snapshots intentionally exported, exit 0 |
| Full-suite OpenAPI equality/security/reference tests | Pass; 0.4.0, 20 paths / 22 operations; health paths/schemas compatible |
| `docker compose exec -T backend python scripts/smoke_reservations.py` | **33 live HTTP checks**, original application table counts restored, exit 0 |
| Live `/openapi.json` versus checked-in YAML from host Python | Exact equality, 20 paths / 22 operations, exit 0 |
| Six localhost URLs: health/live, health/ready, docs, openapi.json, frontend root/proxy readiness | All HTTP 200, exit 0 |
| `docker compose exec -T redis redis-cli ping` | PONG, exit 0; service health only |
| Test-server pg_database query for generated csrs_phase2 databases | Zero remaining disposable databases, exit 0 |
| Markdownlint on the eight changed/new Markdown documents | Zero errors, exit 0 |
| Mermaid parser on architecture/explanation | Four diagrams parsed successfully, exit 0 |
| `git diff --check`, local Markdown references, staged-diff review | Passed; no staged files |

The host Python shorthand refers to `.venv\Scripts\python.exe`. Actual execution counts are
114 unit/contract and 303 PostgreSQL integration cases, totaling 417. The old 323 cases remain
represented; Phase 4 adds 94 cases including the added overdue/valid capacity parameter.
Do not add historical/preliminary suite totals together. Migration upgrade/downgrade round
trips run only in generated disposable test databases, never against development data.

The live smoke covers frontend/proxy readiness, direct API readiness/docs/schema, registration/
login, event publication, holds, exact replay, same-user conflict, full capacity, ownership,
CSRF-before-replay, effective availability, confirmation/cancellation repeats, history,
rebooking, expiration conflict/reclamation, close, and stored EVENT_FULL after release. It
generates its own accounts/event and cleans only those IDs/digests in foreign-key-safe order.
To exercise expiry immediately, it makes only its generated hold overdue under the event lock.

No standalone frontend unit-test/ESLint framework exists. The initial verification above
preceded commit/push authorization and therefore included no hosted Phase 4 CI run. Following
the user's final authorization, publication and exact-commit CI results are verified separately
and reported in the final task response; no CI success is inferred from local tests.
Host localhost checks also required executor escalation after a sandbox socket denial; the
rerun passed. Documentation checks used the existing ignored `.local/doc-validation` tools:
markdownlint-cli2-bin.mjs with its existing config, and check-mermaid.mjs. Those local tooling
copies are not new project dependencies. A sequence-diagram punctuation parsing error and
seven Markdown wrapping/blank-line findings were fixed before the final documentation checks.

## Final audit follow-up and publication verification

The independent correctness audit found zero BLOCKER/HIGH/LOW issues and one MEDIUM
test-coverage issue: the old post-wait test moved the deadline one second into the past,
which could let an incorrect transaction-start clock pass. The production decision clock
was already correct and has not changed during this follow-up. No API, schema, configuration,
or behavior changed, so the Phase 4 explanation required no update.

The strengthened test is
`test_confirm_uses_post_wait_time_not_transaction_start` in
`backend/tests/integration/test_reservation_transactions.py`.
It holds the event row, observes the contender's real lock wait, and queries that contender's
actual xact_start from pg_stat_activity using pg_blocking_pids. It sets the hold deadline to
the midpoint between transaction start and a later database-clock observation, flushes that
deadline while retaining the event lock, and explicitly asserts:

```text
transaction_start < hold_deadline < observed_at <= before_lock_release
persisted_expired_at >= before_lock_release
```

Thus transaction-start now() sees a still-valid hold, while clock_timestamp() after the event
lock sees an expired hold. The test requires 409 HOLD_EXPIRED, persisted EXPIRED with no
confirmed_at, and a completed idempotency outcome containing that same 409 body and decision
timestamp. Existing invariant checks remain. No arbitrary sleep establishes the ordering.

| Final check on 2026-10-26 | Actual result |
| --- | --- |
| Rebuilt test image; targeted strengthened test | 1 passed in 0.89s, exit 0 |
| Ten fresh pytest executions of that target against disposable PostgreSQL | 10/10 passed; each execution 0.66-0.77s |
| In-memory negative control replacing only reservation service database_time with SELECT now() | Expected pytest exit 1: HTTP 200 versus required 409; 1 failed in 0.85s, proving regression sensitivity |
| Complete backend suite using the rebuilt image | **417 passed in 58.53s**, zero failures/skips, exit 0 |
| Host and container Ruff lint/format checks | All checks passed; 51 Python files formatted, exits 0 |
| Container Alembic drift check | No new upgrade operations detected, exit 0 |

The initial targeted command was:

```powershell
docker compose --profile test run --build --rm backend-test python -m pytest tests/integration/test_reservation_transactions.py::test_confirm_uses_post_wait_time_not_transaction_start -q -p no:cacheprovider --tb=short
```

The complete final run used:

```powershell
docker compose --profile test run --rm backend-test python -m pytest -q -p no:cacheprovider --tb=short
```

Repetition used ten separate subprocess invocations of the same target. For the negative
control, a temporary pytest plugin changed only the in-memory reservation clock to
`lambda db: db.scalar(select(func.now()))`, then ran the exact same test. That intentionally
incorrect clock returned 200 and was rejected by the existing 409 assertion. Production
sources were never edited for the mutation. The ignored verification harness and logs under
.local are excluded from Git; they are not new dependencies or committed tests.

The suite still contains 114 unit/contract and 303 real PostgreSQL integration cases: the
existing test was strengthened, with no added or removed cases. All Phase 1-3 regressions and
OpenAPI equality tests pass in that full run. Migration tests also execute there; no new
migration or contract export was needed. Earlier frontend/live-smoke evidence remains the
initial verification evidence above; those checks were not rerun for this test-only change.

The final manifest remains 32 intended Phase 4 files (21 modified, 11 added). Publication uses
the authorized message `feat: implement concurrency-safe reservations` on main. The report
captures pre-commit verification rather than embedding its own commit hash. The final task
response supplies the published hash and exact-commit CI link/status after remote verification.

## Failures found, fixes, and regression review

- Initial behavior run: 43 passed, 3 TTL tests failed. The fixed decision clock preceded
  claim creation, violating completed_at >= created_at. The test clock was corrected to a
  valid decision instant; no constraint was weakened.
- Expanded run: 74 passed, 1 organizer/admission test failed. Its closure still used the
  original user's session. The test now passes the actual contender and runs both real
  transaction services in an observed lock order.
- Initial full run: 413 passed, 2 old Phase 3 assertions failed. One assumed holds were
  unregistered; it now checks a missing event with valid mutation credentials/key. The other
  assumed capacity edits never expire holds; it now separately covers valid holds refusing an
  unsafe reduction and due holds permitting cleanup/reduction. Existing contract/route scope
  assertions were also extended for the newly registered endpoints.
- Review found reservation updated_at could inherit transaction-start time before its
  post-lock created_at. New/transitioned reservation timestamps now use the decision instant.
- Review tightened reservation/availability timestamps to the existing UTC-normalizing type,
  so a non-UTC database connection cannot change the API representation. A unit test covers it.
- Business conflicts return values until commit; this preserves expiry and durable 409s.
  Security/transient failures roll back the claim. Fault tests verify these boundaries.

Final review covered overselling, lock refresh/order, atomic commit/rollback, same-key and
different-key contention, replay security, exact state boundaries, single release, capacity
edits, current-count equality, event close semantics, and retained Phase 1-3 protections.
All final tests pass. No unresolved Phase 4 correctness failure is known from these checks.

## Changed-file manifest

**11 added files:**

- `backend/scripts/smoke_reservations.py`
- `backend/src/csrs/api/reservations.py`
- `backend/src/csrs/reservations/__init__.py`
- `backend/src/csrs/reservations/schemas.py`
- `backend/src/csrs/reservations/service.py`
- `backend/src/csrs/reservations/transitions.py`
- `backend/tests/integration/test_reservations.py`
- `backend/tests/integration/test_reservation_transactions.py`
- `backend/tests/unit/test_reservation_contract.py`
- `docs/validations/phase-4-validation.md`
- `docs/phase-explanations/phase-4-explanation.md`

**21 modified files:**

- `.env.example` and `README.md`: hold TTL configuration, current scope, retry/API guidance.
- `backend/pyproject.toml`: package version/description only.
- `backend/src/csrs/api/events.py`: module description only.
- `backend/src/csrs/api/openapi.py`: reservation cookie/CSRF declarations; retain parameters.
- `backend/src/csrs/config.py`: bounded hold TTL setting.
- `backend/src/csrs/events/service.py`: shared due cleanup and commit on refused reduction.
- `backend/src/csrs/main.py`: router registration, API metadata, no-store scope.
- `backend/src/csrs/models.py`: module description only; no schema change.
- `backend/tests/integration/conftest.py`: reusable booking identities/real sessions fixture.
- `backend/tests/integration/test_events.py`: documented Phase 4 capacity/route expectations.
- `backend/tests/unit/test_event_inputs.py`: keep public GET security assertion on GET paths.
- `backend/tests/unit/test_health.py`: implemented route-set assertion.
- `docs/architecture.md`: current boundaries and three updated diagrams.
- `docs/concurrency.md`, `docs/contracts/api.md`: implemented protocol/API clarification.
- `docs/contracts/api.openapi.yaml`, `docs/contracts/health.openapi.yaml`: generated snapshots.
- `docs/database.md`, `docs/security.md`: implemented service/security boundaries.
- `frontend/src/App.tsx`: phase label only; no booking UI.

Ignored local verification logs/tools/build caches are not part of this manifest. No secrets,
database dumps, dependency upgrades, migration edits, or historical report rewrites are included.

## Remaining limitations and deferred phases

Request-time expiration works, but quiet events retain overdue persisted HELD until a relevant
request arrives. Reads project effective expiry meanwhile. Phase 5 will add the standalone
bounded sweeper; no scheduler, worker process, polling loop, or sweep outage/restart claim exists.
Phase 6 Redis limiting/cache remains absent, as do Phase 7 business screens/dashboard and
Phase 8 deployment, backup/restore, broad mixed load and performance reporting. No cloud service
was provisioned. Payments, quantities, seat maps, and event-wide reservation cancellation remain
outside scope. Idempotency retention is unbounded in this MVP; hot-event writes serialize.

## Phase 4 acceptance checklist and Git state

- [x] Hold/confirm/cancel, response DTOs, supporting reads, and OpenAPI follow the contracts.
- [x] Existing sessions, CSRF/source/JSON guards, roles, ownership, and sanitized errors reused.
- [x] One-seat admission, capped configurable five-minute TTL, boundaries, terminal history tested.
- [x] Shared event-lock protocol and due cleanup on reservation commands/capacity edits.
- [x] Persisted-count equality/bounds and active-user uniqueness checked after contention.
- [x] Durable fingerprint/claim/replay, concurrent duplicates, stored business conflicts tested.
- [x] Rollback, response loss, simulated uncertain commit, and real lock timeout tested.
- [x] Independent connections and two API processes; controlled lock races without sleep ordering.
- [x] Full Phase 1-4 suite, lint/format, migrations, frontend, Compose, HTTP, and contracts pass.
- [x] Validation and beginner-friendly twelve-section explanation supplied.
- [x] Worker, Redis integration, dashboard/business UI, deployment remain deferred.
- [x] Original review gate honored; audit completed and final test improvement verified.
- [x] User explicitly authorized commit/push after successful final checks; no Phase 5 work.

Pre-commit baseline: branch main, HEAD 6eb9fbc. The intended change contains 21 modified and
11 added files (32 total), with no temporary verification tools, secrets, or generated caches.
No merge or new branch is needed. The authorized commit/push, clean working-tree check,
local/remote hash equality, and exact-commit GitHub Actions result are reported after publication.
