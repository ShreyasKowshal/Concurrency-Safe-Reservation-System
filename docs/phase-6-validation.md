# Phase 6: Redis support validation and self-audit

Date: 2026-10-26, Asia/Calcutta. Baseline: main at
`f8b4819414cf1cd5815b3b312e14685d41abc5cb`. Phases 1-5 are committed with green CI.
**Phase 6 is implemented locally and remains uncommitted for external review.** No staging,
commit, push, merge, Phase 7 UI, or deployment is authorized. PROJECT_HANDOFF.md and historical
phase reports/explanations remain unchanged. Hosted Phase 6 CI has not run.

## Requirements, delivered features, and boundaries

The handoff requires atomic multi-process rate limits and short-lived public event metadata
caching. It explicitly excludes availability caching. Implemented scope follows that boundary:

| Requirement | Implementation/evidence |
| --- | --- |
| Atomic shared quotas | One Lua decision/increment/expiry operation; independent API-process quota test |
| Anonymous session abuse control | New anonymous bootstrap and login/register quotas fail closed on Redis errors; existing valid token reads do not create rows |
| Safe public metadata cache | Public detail only; SQL publication gate, validated public DTO, absolute expiry, post-commit invalidation |
| Explicit outage policies | Required auth operations return controlled 503; authenticated mutations/public reads continue with SQL; real stopped-Redis smoke |
| Preserve PostgreSQL correctness | Existing command/worker algorithms unchanged; regressions, outage races, reconciliation |
| Maintainable lifecycle/configuration | One lazy redis-py pool per API, finite DNS/TCP/socket waits, no automatic retries, cleanup, sanitized logs |
| Real tests and CI configuration | Dedicated test Redis plus PostgreSQL, scoped keys/databases, process races and outage/recovery smoke |
| Documentation/review gate | This report, twelve-section explanation, current contracts/architecture/configuration; handoff untouched |

PostgreSQL remains authoritative for users/sessions, authorization, reservation state,
capacity, clock decisions, idempotency, and expiration recovery. Redis contains no seat counter,
reservation transition, private reservation, cookie/CSRF secret, password, or durable outcome.
No new API path/body shape, PostgreSQL schema, migration, frontend feature, or cloud service.
API/package version remains 0.4.0; OpenAPI intentionally adds 429 and detail-cache documentation.

## Architecture and request flow

`RedisSupport` owns one synchronous redis-py 8.1 pool per API lifespan. It is constructed lazily
without a startup connection and closed at shutdown. The database engine is disposed even
if Redis cleanup raises. The worker never constructs RedisSupport or opens a Redis connection.
Settings still requires a syntactically valid Redis URL, as before.

Authenticated mutation flow: HTTP source/media/body/key validation; short SQL session/CSRF/
role preflight; end that transaction; user quota; original business service transaction.
The service still validates authorization inside its transaction and after lock/claim waits.
Quotas neither authorize operations nor change durable replay behavior. No support call occurs
under an event lock. Successful organizer edit/capacity/publish/close commits before invalidation.
Independent SQL NOWAIT acquisition during invalidation proves the event lock is already released.

Public detail flow: optional peer quota; SQL ID-only PUBLISHED check; Redis lookup; return a
valid hit or load public SQL detail and attempt a fill. A cache hit cannot hide PostgreSQL
failure or authorize publication. A read concurrent with close can observe the pre-close
visibility at its SQL query, as an ordinary read can. Lists/availability always use SQL.

### Connection and logging behavior

Default DNS/TCP connection budget: 0.2 seconds combined. Default socket timeout: 0.2 seconds
per operation. Pool exhaustion fails immediately, and automatic command retries are disabled.
These bounds do not promise an entire HTTP latency SLA; protocol/TLS setup can involve multiple
bounded socket operations and SQL has its own timeouts.

The live Redis-stop experiment exposed OS DNS resolution outside redis-py's socket timeout.
The connection adapter now bounds DNS callers too. One pending daemon lookup is shared by all
connections in that API client; no unbounded executor queue or growing blocked thread pool.
Successful DNS results are reused for one second and TCP failure requests refresh. A blocked
OS lookup itself cannot be cancelled; it does not block caller fallback or process shutdown,
and new DNS work resumes after it completes. TLS retains the original hostname and certificate
verification. Configuration preservation is tested; no live TLS server was exercised.

JSON support records identify cache hit/miss/fill/invalidation/invalid data and quota rejection/
unavailability, operation/scope, and error class. URLs, exception strings, settings, cached bodies,
and quota identities are excluded. Normal Uvicorn access logs remain separate.

## Quotas, identity, and degraded behavior

Each fixed window starts with its first accepted request. A saturated counter is not incremented
again, and rejection does not renew expiry. 429 RATE_LIMITED includes ceil(remaining milliseconds
/ 1000), minimum 1, in Retry-After. A throttle is never stored as a completed booking outcome.

| Routes/scope | Default / window | Identity | Redis error policy |
| --- | --- | --- | --- |
| Bootstrap that would create a new anonymous session | 30 / 60 seconds | Connection peer | 503 TEMPORARILY_UNAVAILABLE, Retry-After: 1; no new session |
| Login/register combined | 10 / 60 seconds | Connection peer | Same controlled 503 |
| Public event list/detail/availability combined | 120 / 60 seconds | Connection peer | Continue with SQL |
| Hold/confirm/cancel/replays and organizer mutations combined | 60 / 60 seconds | Current authenticated user | Continue with original SQL transaction |

Valid existing CSRF-token retrieval, logout, health, current-user, private reservation/history,
and organizer reads are unthrottled. Existing token retrieval is checked without creating a row;
if creation is necessary, the route must pass the quota before invoking normal bootstrap.
HTTP source/media/input validation still applies; validated login/register attempts count even
when credentials/CSRF later fail. Mutation preflight validates session/CSRF/role before Redis.

Identity uses the connection peer, not an HTTP identity header. Compose/image/host commands
disable Uvicorn proxy-header trust. Forged X-Forwarded-For does not evade the shared quota
in the independent-process test. Vite/shared proxies make users share a peer IP quota; trusted
proxy deployment is deferred. Quota keys hash the peer/user ID; hashes are pseudonymous and
not a claim of anonymity. No user email or cookie is included.

During Redis failure or uncertain acknowledgement, optional quota/cache work does not affect
reservation commits. Required auth work fails closed. Redis restart resets quotas and cache;
this application limiter is not a production DDoS defense. SQL failures retain their separate
controlled error and cannot be disguised by a cached response.

## Cache specification and concurrency

| Property | Actual design |
| --- | --- |
| Cached route | GET /api/v1/events/{event_id} only |
| Key | NAMESPACE:ENVIRONMENT:v1:event:UUID; default csrs:local:v1:event:UUID |
| Quota key | NAMESPACE:ENVIRONMENT:v1:quota:SCOPE:SHA256(identity) |
| Data | Required version: 1 plus the existing public EventDetail fields; no allocation/occupancy |
| Validation | Correct UUID/PUBLISHED/schema/version, forbidden extra fields, bounded fields and payload |
| TTL | Default 15, configurable 1-60 seconds; hits never renew |
| Fill | Redis TIME at lookup plus TTL, then SET PXAT to that absolute deadline; expired fills skipped |
| Invalidation | Successful edit/capacity/publish/close route, after SQL commit, best effort |
| Visibility | Fresh SQL PUBLISHED check on every request, including Redis hit |
| Failure | Miss/Redis error/invalid or oversized value falls back to SQL; an SQL DTO outside cache limits bypasses filling; failed fill/invalidation does not undo SQL |
| Size/memory | Maximum 64 KiB payload; 64 MiB local Redis, noeviction, no persistence; expiring keys |

The classic old-read/new-invalidation race is explicitly permitted only within the original
absolute cache lifetime. Tests gate a real SQL read, commit an edit/invalidate, then release the
older fill and assert its exact original Redis expiry. A fill after that deadline is rejected.
An unavailable invalidation can leave stale public metadata, including displayed capacity,
for the remaining lifetime. SQL visibility still rejects closed/draft events. Cache availability,
live occupancy, reservations, idempotency, lists, and private organizer fields are excluded.

Hold/confirm/cancel/request cleanup/worker expiration need no metadata invalidation because the
cached DTO contains no allocation. Capacity edits do invalidate because capacity is a public
metadata field. Actual admission and uncached availability always use current PostgreSQL.
Two API processes consuming the same stale capacity still allocate only the final real seat.

## Configuration, infrastructure, and commands

The [README](../README.md#redis-support-phase-6-awaiting-review) and [.env.example](../.env.example)
list all settings and bounds. Redis URLs accept redis:// or rediss:// with a numeric database
path; query/fragment parameters are rejected to prevent timeout/security-option overrides.

Defaults: namespace csrs; pool 10 connections/process; connection and socket timeouts 0.2s;
metadata cache and quotas enabled; metadata TTL 15s; shared quota window 60s; limits above.
Feature switches are explicit: isolated SQL regression fixtures disable quotas/cache so rate
limiting cannot hide races. Phase 6 tests enable them. The normal application defaults enable both.

```powershell
docker compose up --build -d --wait --wait-timeout 120
docker compose exec -T backend python -m alembic upgrade head
docker compose --profile worker up --build -d worker
docker compose --profile test run --build --rm backend-test
```

Test infrastructure uses postgres-test and redis-test, never development data. PostgreSQL
fixtures create/drop only generated csrs_phase2_*_test databases. Redis requires a dedicated
test URL ending /15, uses unique per-test namespaces, and deletes only those keys. Unit isolation
preserves both CSRS_TEST_DATABASE_URL and CSRS_TEST_REDIS_URL. Compose exposes test Redis on
127.0.0.1:6380; development Redis remains loopback 6379. Neither API nor worker requires Redis
health for startup. Compose's normal --wait includes Redis health, but backend --no-deps startup
works while Redis is stopped. Redis memory errors use the same documented failure policies.

CI now supplies real Redis to the backend job and keeps PostgreSQL/frontend/Compose jobs.
Compose runs isolated tests and a scoped available/outage/recovered smoke with the worker.
No hosted Phase 6 Actions result is claimed before approved publication.

## Verification results

Environment: Docker Desktop Linux containers on Windows; pinned Python/backend dependencies,
PostgreSQL 17, Redis 7.4, Node 24. Docker access required executor escalation. Credentials and
development volumes were preserved. Supplemental repetitions are not additional unique cases.

| Check | Actual result |
| --- | --- |
| Initial expanded full suite before final audit fixes | 530 passed in 116.59s, exit 0 |
| Focused Phase 6 unit/real Redis/PostgreSQL run after DNS/lifecycle/version fixes | 65 passed in 28.52s, exit 0; later cache-compatibility case is included in the final full run |
| Final complete backend suite | **540 passed in 99.51s**, zero failures/skips, exit 0 |
| Final breakdown | 153 unit/contract + 387 integration (344 retained PostgreSQL + 43 Redis/PostgreSQL cases); 66 cases added to baseline 474 |
| Final dedicated integration suite | **387 passed, 153 deselected in 94.88s**, exit 0 |
| Final dedicated Redis suite | **43 passed, 497 deselected in 22.82s**, exit 0 |
| Final focused API/OpenAPI contracts | **9 passed in 1.19s**, exit 0 |
| Three fresh final-image executions of seven race/failure targets | 7 passed each, 59 deselected, in 7.91s / 7.84s / 7.78s; all exits 0 |
| Ruff lint and format, host/container | All checks passed; 63 Python files already formatted, exits 0 |
| Host/container pip check | No broken requirements, exits 0 |
| Alembic upgrade/head/current/check | 0002_worker_expiry remains installed/current/head; no new upgrade operations, exits 0 |
| Frontend typecheck and production build | Passed; Vite 30 modules, build 1.89s, exits 0 |
| Compose and Redis configuration | Config validation passed; live maxmemory 67108864 bytes and noeviction |
| CI configuration | YAML parsed; backend/frontend/Compose jobs retained, real test Redis and worker/outage checks present; hosted Phase 6 CI not run |
| Live Redis available | 13 HTTP checks, one independent worker expiration, zero invariant mismatches; exit 0 |
| Live Redis stopped, cold API and worker startup | 13 HTTP checks, one independent worker expiration, zero invariant mismatches; repeated after DNS fix, exit 0 |
| Live Redis recovery without restarting API | 13 HTTP checks, cache/invalidation restored, worker expiration, zero invariant mismatches; exit 0 |
| Existing live reservation smoke | 33 HTTP checks passed; original table counts restored, exit 0 |
| Existing worker stopped/backlog/start/verify smoke | Five due holds expired, allocation zero, three HTTP checks passed; generated users/event cleaned, exit 0 |
| Final independent development SQL reconciliation | Zero counter mismatches, duplicate active pairs, or pending idempotency claims |
| Live API contract | Runtime exactly matches checked-in OpenAPI: 20 paths / 22 operations |
| Disposable resource cleanup | Zero generated PostgreSQL test databases and zero keys in dedicated Redis test database 15 |
| Markdown/references/diagrams/hygiene | Eight Markdown documents lint clean; 37 local links/anchors valid; five diagrams parsed; sensitive-pattern/manual manifest review clean |
| Final diff/staging/source check | git diff --check passed; staging empty; 32 intended files; frozen code/config fingerprint unchanged; handoff, booking/worker algorithms, models/migrations and frontend source unchanged |

Full-suite commands use the rebuilt image without a source bind mount:

```powershell
docker compose --profile test run --rm backend-test python -m pytest -q -p no:cacheprovider --tb=short
docker compose --profile test run --rm backend-test python -m pytest -m integration -q -p no:cacheprovider --tb=short
```

Earlier development targets used read-only backend/docs mounts to iterate; final image runs
are recorded separately. Integration subsets overlap with the full suite and must not be added
as extra unique tests. Redis-marked cases also use the isolated PostgreSQL fixtures.

### Concurrency and failure evidence

- Sixteen concurrent Redis quota requests: exactly five accepted and eleven rejected, one
  expiring counter. Ten requests across two API processes: exactly three new sessions and
  seven 429s, despite different forged forwarded addresses.
- Real cache values, misses, actual TTL expiry, no refresh on hit, invalidation, namespace/event
  isolation, malformed/oversized/wrong-version/private-field/wrong-type fallbacks.
  Invalid-entry tests observe the full SQL query, so returning the same-looking cached body
  cannot falsely prove fallback. Existing SQL/output details beyond cache limits remain readable.
- Independent process cache fill/update/invalidation; signal-gated old fill after commit;
  exact absolute expiry and rejection of an already expired fill.
- Redis connection refusal: holds/confirm/cancel/replay/capacity/public reads continue with SQL.
  Two API processes test final-seat, same-user/different-key, and same-key duplicate races.
- Required anonymous/auth outage returns 503 without new sessions/users; existing token
  retrieval and logout continue. Revocation during a gated Redis wait prevents any claim/mutation.
- A real Redis CLIENT PAUSE triggers socket timeout and later same-client recovery. This uses
  only the dedicated test server; live stop/start separately tests actual Redis process recovery.
- A real SQL table lock produces PostgreSQL 503 despite a cached detail. Independent SQL NOWAIT
  acquisition during invalidation proves commit/lock release preceded Redis work.
- Pool exhaustion, bounded blocked DNS, no automatic retry, sanitized logs, TLS configuration,
  lifecycle and cleanup failure have focused unit/real-pool checks.
- Existing worker, reservation/idempotency, lock-order, exact post-lock clock, crash/restart,
  schema/migration, authentication/CSRF and authorization regressions remain in the full suite.

Test synchronization uses barriers, signals, transactions, and observable Redis/SQL state.
Short polling waits observe actual expiry/recovery and never establish race order by sleeping.

## Live outage/recovery reproduction

```powershell
docker compose --profile worker up -d worker
docker compose exec -T backend python scripts/smoke_redis.py available
docker compose stop redis
docker compose --profile worker restart worker
docker compose up -d --no-deps --force-recreate --wait --wait-timeout 60 backend
docker compose exec -T backend python scripts/smoke_redis.py outage
docker compose up -d --wait --wait-timeout 60 redis
docker compose exec -T backend python scripts/smoke_redis.py recovered
```

The helper creates two generated users/sessions and one event, uses live HTTP for metadata,
hold/replay/confirm/cancel/capacity, seeds overdue work under the event lock, and observes the
independent worker. It reconciles global counters/active-user uniqueness/pending claims and
deletes only its generated IDs/digests, restoring original table counts. No tokens are printed.
Restore Redis even if a check fails. Run against a quiet local development stack.

## Separate source self-audit and corrections

The audit inspected route call order, actual service transactions, worker imports/locks,
cache scripts/schema/expiry, connection handling, error scopes, test synchronization and CI.
It was a skeptical source pass after an initial full passing run, not an external reviewer.

| Severity | Finding and correction | Verification |
| --- | --- | --- |
| MEDIUM | Live stopped-service fallback exposed unbounded OS DNS relative to configured socket timeouts. Added one shared pending bounded-wait DNS adapter with no queued growth; retained Redis protocol/TLS behavior. | Blocked-DNS unit test, real Redis integration, repeated real Docker outage/cold-start/recovery smoke |
| LOW | Cache version default allowed an entry omitting its schema version. Version is now required and explicitly written. | Real Redis missing-version fallback test |
| LOW | A Redis cleanup exception could skip PostgreSQL engine disposal. Nested finally guarantees both cleanup paths. | Lifecycle fault test proves database disposal |
| LOW | Cache input-style field rules could reject or trim valid existing SQL/output detail. Uncacheable values now bypass filling; output validation preserves existing whitespace. | Real PostgreSQL long-description/output and repeated cache-hit value regression |

No BLOCKER or HIGH was found. All identified findings are resolved. No PostgreSQL booking
algorithm, event/row lock order, counter calculation, deadline check, idempotency transaction,
worker SKIP LOCKED, or migration was changed. Additional audit tests verify post-commit
invalidation and authorization revalidation after Redis waiting. An earlier design review also
kept existing valid CSRF retrieval available without letting failed quotas create new sessions.

Other verification corrections: Mermaid interpreted a sequence-label semicolon followed by
"end" as syntax; the label was reworded and all five diagrams now parse. Test review strengthened
invalid-cache cases to observe an actual full SQL fallback, and explicitly ordered Redis time
before releasing the older-fill gate. No assertion or constraint was weakened. Images were
rebuilt and the complete/dedicated suites rerun after the final source corrections.

## Performance evidence and limitations

Observed SQL statements in the real cache test: miss executes two queries (visibility plus
full detail); hit executes one ID-only visibility query with no description load. Both also
pay Redis calls. This demonstrates reduced full-detail loading, not measured latency/throughput
improvement. No production benchmark, cache hit-rate target, or SLA is claimed.

Redis can reset quotas on restart; fixed windows can burst around boundaries. Authenticated
mutations/public reads deliberately bypass unavailable quotas, while new-session/auth flows
pause with 503. Shared proxies/NAT share peer quotas; production proxy/rate/memory tuning and
alerting belong to deployment work. No automatic security-session or idempotency retention purge.

An old fill may temporarily replace newer public metadata until its original deadline. Hits
still query SQL visibility; PG outage therefore returns 503. There is no stampede coalescing,
Redis cluster/failover, or live TLS test. OS DNS lookup work cannot itself be cancelled, although
waiters/shutdown are bounded and only one pending lookup exists per API client. That lookup's
completion can affect how soon DNS-based Redis recovery is observed. The pinned client adapter
should be reviewed when upgrading redis-py. Existing Phase 5 worker latency/lock/backlog limits
and ordinary index-migration locking remain. Phase 7/8, Redis inventory/locks/timers, payments,
analytics, and cloud infrastructure were not implemented.

## Changed-file manifest

Eight added files:

- backend/src/csrs/redis_support.py
- backend/src/csrs/redis_connection.py
- backend/src/csrs/api/redis_dependencies.py
- backend/scripts/smoke_redis.py
- backend/tests/unit/test_redis_runtime.py
- backend/tests/integration/test_redis_support.py
- docs/phase-6-validation.md
- docs/phase-explanations/phase-6-explanation.md

Modified files:

- .env.example: bounded Redis/cache/quota defaults and isolated test URL.
- .github/workflows/ci.yml: real test Redis and live outage/cold-start/recovery checks.
- compose.yaml: memory policy, dedicated test Redis, test dependency, disabled proxy-header trust.
- backend/Dockerfile: server default disables proxy-header trust.
- backend/pyproject.toml, backend/requirements-dev.lock: redis-py constraint/pin and test markers.
- backend/src/csrs/config.py: bounded support settings and safe URL validation.
- backend/src/csrs/main.py: lazy support lifecycle, safe support errors and guaranteed SQL cleanup.
- backend/src/csrs/api/auth.py: quotas and safe existing-token retrieval.
- backend/src/csrs/auth/service.py: optional existing-only bootstrap; default original behavior retained.
- backend/src/csrs/api/events.py: public detail cache, quotas, post-commit invalidation.
- backend/src/csrs/events/service.py: read-only publication gate for cache hits.
- backend/src/csrs/api/reservations.py: quota before the unchanged command service.
- backend/src/csrs/api/openapi.py: intentional 429 response declarations.
- backend/tests/conftest.py, backend/tests/integration/conftest.py: preserve test Redis URL;
  explicitly isolate previous SQL races from quotas/cache.
- backend/tests/integration/test_reservation_transactions.py: spawned server disables proxy
  headers like supported runtime commands; existing race assertions unchanged.
- docs/contracts/api.openapi.yaml: exported 429/detail-cache documentation; health snapshot unchanged.
- README.md: current scope, configuration, identity/outage policies, commands and live checks.
- docs/architecture.md, docs/concurrency.md, docs/decisions.md, docs/security.md,
  docs/contracts/api.md: implemented support boundaries and current contract/policy.

Validated total: **32 files, 8 added and 24 modified**.
No frontend source, models/migrations, handoff, historical phase report, or generated artifact.

## Acceptance and Git state

- [x] Required handoff scope implemented: atomic quotas plus public metadata only.
- [x] PostgreSQL authority, locks, counters, exact deadlines and durable replay preserved.
- [x] Explicit required/optional Redis failure policies and existing-token availability.
- [x] Scoped bounded cache, fresh publication visibility, post-commit invalidation and stale-fill bound.
- [x] Real Redis/PostgreSQL and independent process tests; no mock proves database concurrency.
- [x] Live Redis stopped/startup/recovery and independent worker compatibility verified.
- [x] Separate source self-audit completed and identified findings corrected.
- [x] Final full/dedicated/repeated suites and quality checks recorded.
- [x] Documentation/manifest/hygiene validated against actual final changes.
- [x] PROJECT_HANDOFF.md unchanged; no Phase 7 or deployment work.
- [x] No staging, commit, push, or merge; stop for external review.

Branch main, existing HEAD f8b4819414cf1cd5815b3b312e14685d41abc5cb. The 32 intended files are
uncommitted; nothing is staged. The final code/config fingerprint covers 63 Python files and
six runtime/CI configuration files and is checked unchanged after verification. No hosted
Phase 6 CI result is implied. Stop here for external review; publication needs separate approval.

Client references: [redis-py connection URLs](https://redis.io/docs/latest/develop/clients/connection-urls/),
[production usage](https://redis.io/docs/latest/develop/clients/redis-py/produsage/),
[official client source](https://github.com/redis/redis-py).
