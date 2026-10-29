# Phase 8: local production readiness, final validation and portfolio evidence

Date: 2026-10-28, Asia/Calcutta. Baseline/HEAD:
`6bf24b0203bf0c752c2edf5e668152c3945f07c2`, branch `main`.
The initial tree was clean and matched the requested baseline exactly.
Sections 1-19 preserve the implementation-stage snapshot recorded before finalization
authorization. Section 20 records the subsequent authorized pre-commit review and checks.
**Implemented locally; uncommitted and awaiting external review.** No staging, commit, push,
merge, release, cloud deployment, hosting account, paid resource or public database was created.
PROJECT_HANDOFF.md remains unchanged; its final completion update belongs to later finalization.

## 1. Revised scope and acceptance criteria

The owner replaced the older cloud roadmap with localhost startup/recovery, final testing,
security review, interview demonstrations and portfolio evidence. No cloud/backup/restore
infrastructure is part of this phase. "Local production readiness" describes local operational
discipline, not public production hardening, measured scalability or cloud operation.

Acceptance requires a working five-service Compose stack; safe migration/configuration;
PostgreSQL persistence; Redis and worker policies; real attendee/organizer/browser workflows;
bounded concurrency and replay evidence; safe scoped demos; source audit/corrections;
complete documentation and an unstaged reviewable diff. Existing reservation protocols,
constraints, API shapes and Redis failure policies must remain intact.

## 2. Implemented changes and local architecture

Compose runs React/Vite, FastAPI, PostgreSQL, Redis and an independent worker. PostgreSQL
remains authoritative for users/sessions/events/reservations/capacity/deadlines/idempotency.
Redis provides quotas and public event-detail metadata only. Vite is local serving/proxy
tooling; a public built-frontend tier is still future work.

New `migrate` is a one-shot service. PostgreSQL health gates migration; successful upgrade,
metadata drift check and commit gate API/worker. API readiness gates the frontend; a new
frontend HTTP health check makes full-stack `--wait` meaningful. API reload is disabled for
stable demonstrations. Runtime services have unless-stopped restart policies and bounded
json-file logs (10 MiB per file, three files). Restart policies act on exited processes,
not arbitrary unhealthy-but-running containers.

`csrs.migrate` holds a PostgreSQL advisory transaction lock on the same connection and outer
transaction used by Alembic upgrade/check. Competing cooperating runners wait or hit the
configured statement timeout rather than racing DDL. Failures roll back schema changes and
report only an error class. Raw administrative Alembic commands must not be raced against
this entry point. No runtime per-API migration or schema reset is introduced.

`csrs.demo` creates UUID-scoped local accounts/events with a private password prompt,
idempotent prepare, collision checks and guarded cleanup. Cleanup refuses reservations
crossing account/event boundaries and locks events before removing scoped reservation rows.
The separate-project verifier validates absent host ports and its generated volume name
before any downtime experiments. Fixture session material stays in memory/stdin.

## 3. Startup, shutdown and local URLs

From the root with Docker Desktop's Linux engine running:

```powershell
./scripts/local.ps1 start
./scripts/local.ps1 status
./scripts/local.ps1 stop
```

The start wrapper checks Docker, creates `.env` only if absent, validates Compose, then runs:

```powershell
docker compose --profile worker up --build -d --wait --wait-timeout 180
```

Stop uses `docker compose --profile worker --profile test down` without volume deletion.
An exited migrate container with code 0 is expected. The worker remains an explicit profile,
enabled by the full-stack wrapper. Existing local `.env` was preserved.

| URL | Purpose |
| --- | --- |
| <http://localhost:5173/> | Real attendee/organizer frontend |
| <http://localhost:8000/docs> | API documentation |
| <http://localhost:8000/openapi.json> | Runtime contract |
| <http://localhost:8000/api/v1/health/live> | Process liveness |
| <http://localhost:8000/api/v1/health/ready> | PostgreSQL connectivity |
| <http://localhost:5173/api/v1/health/ready> | Frontend proxy path |

Use the exact browser origin in CSRS_PUBLIC_ORIGIN. Do not substitute 127.0.0.1 without a
matching configuration change. Readiness does not claim schema currency, Redis health or
worker progress. Full startup separately gates migrations and waits for Redis/HTTP health.

## 4. Configuration and Docker reliability

`.env.example` lists all application settings plus public local PostgreSQL examples.
Compose injects its container DNS connection strings and public same-origin VITE_API_BASE_URL.
No database credential enters frontend JavaScript. Cookie Secure/name follow origin scheme;
production requires HTTPS and now rejects the known public example database passwords.
That narrow guard is not a complete password-strength or cloud security assessment.

Defaults remain SQL pool 5 plus overflow 5/process, connect/pool timeout 3 seconds,
statement timeout 3000 ms; Redis connection/socket budgets 0.2 seconds, pool 10,
metadata TTL 15 seconds, quotas 30/10/120/60 per 60 seconds; authenticated session 8 hours,
anonymous session 15 minutes, hold TTL 300 seconds; worker poll 15 seconds, batch 100,
retry 1-30 seconds. Bounds are enforced by Settings. Worker uses no Redis connection.
No CORS middleware was added; exact origin and synchronizer-token CSRF remain mandatory.

All published app/test ports bind to loopback. PostgreSQL uses postgres_data, test PostgreSQL
uses separate tmpfs storage, and recovery projects receive distinct named volumes. Redis is
ephemeral with a verified 64 MiB/noeviction configuration. Images retain non-root runtime
users, Python constraints and npm lock installation. They still contain development/test
tools and use floating base-image tags; public runtime hardening remains future work.

## 5. PostgreSQL schema and persistence

No model, constraint, migration or business endpoint changed. Alembic heads/current both
reported **0002_worker_expiry (head)**; check reported **No new upgrade operations detected**.
New real PostgreSQL tests observe an advisory-lock wait, preserve an existing user during
reupgrade and verify complete rollback when drift verification is deliberately failed.

The isolated recovery fixture creates an authenticated session, a real HTTP-held/confirmed
reservation with durable hold/confirm outcomes, and a controlled overdue hold. Verification
after API/frontend/Redis/worker/PostgreSQL restarts and ordinary down/up observes the same
session, exact original hold response on replay, current CONFIRMED detail, one worker EXPIRED
row and allocation 1 equal to active rows. Confirmed state is preserved and expiration does
not double-release. This proves ordinary restart persistence for those generated records;
it is not backup/restore or physical database-corruption testing.

## 6. Redis verification

The full suite includes 43 real Redis/PostgreSQL integration cases. They retain all four
quotas, atomic multi-process limits, 429/Retry-After, required auth/bootstrap 503, optional
public/mutation SQL fallback, real TTL expiry, cache hit/miss, no renewal, schema validation,
post-commit invalidation, SQL publication visibility, old-fill bounds and recovery coverage.
SQL transaction races explicitly disable support quotas so throttling cannot hide admission.

The audited isolated live verifier stopped actual Redis, restarted worker, cold-recreated API,
ran outage smoke, restored Redis and ran recovery without another API restart:

| Mode | Observed result |
| --- | --- |
| available | 13 HTTP checks, one worker expiration, zero invariant mismatches |
| outage | 13 HTTP checks, one worker expiration, zero invariant mismatches |
| recovered | 13 HTTP checks, one worker expiration, zero invariant mismatches |

Public reads and authenticated booking/organizer commands continue through SQL when optional
Redis work fails. New anonymous sessions and login/register fail closed. Existing valid token
retrieval/logout remain usable. Redis does not own seat allocation or durable outcomes.

## 7. Independent worker verification

Retained unit, real PostgreSQL and independent-process tests cover due/valid/confirmed/terminal
rows, exact deadlines, post-lock time, repeated sweeps, SKIP LOCKED, duplicate workers,
API/worker races, event capacity/close, bounded catch-up, rollback, killed processes,
shutdown/restart and temporary database unavailability. The worker uses event-first locks
and the shared conditional HELD-to-EXPIRED transition, decrementing only actual changed rows.

Isolated live recovery observes worker expiration from SQL before any availability read and
preserves a confirmed row through all restarts. Redis smoke separately observes one worker
expiration in each live mode. The five-hold backlog smoke also passed live: five EXPIRED,
allocation 0, three HTTP checks
and cleanup of six users/one event; commands are in the demo guide. Worker logs/progress are
separate from generic container Running status.

## 8. Attendee and organizer browser workflows

The final Chromium run passed **eight journeys in 1.2 minutes**, retries disabled, real
FastAPI/PostgreSQL/Redis/worker responses throughout. No booking success is mocked.

1. Discovery waits for real cards, published detail, registration, login, hold, reload/countdown,
   confirmation, history and cancellation through the dialog.
2. Organizer login, draft create/edit, capacity update, publish, published schedule restrictions,
   owner dashboard, close and public detail rejection.
3. Two independent browser contexts compete for the last seat at a request barrier;
   one 201 and one 409 EVENT_FULL, with real feedback and SQL reconciliation.
4. Scoped controlled overdue hold projects EXPIRED and an actual late confirmation returns
   HOLD_EXPIRED. No global clock override or genuine reservation is modified.
5. A successful hold is actually forwarded/committed, its response delivery discarded,
   and recovery must reuse the same key to retrieve one reservation.
6. Responsive/axe/keyboard/deep-link/account-switch/logout/cross-account access checks.
7. Stored capacity/counter/uniqueness reconciliation, including one final-seat allocation.
8. Expiration of only the test context's own server session, followed by private-state removal
   and the login-required UI after reload.

Component/API tests separately cover structured 401/403/404/409/415/422/429/503, invalid DTOs,
network uncertainty, double submissions, retry intent, timer boundaries, session/account
cleanup, role denial and field feedback. Backend tests retain full/closed/past-deadline event,
foreign organizer ownership and exact state/time restrictions. Component stubs are UI tests,
not evidence of PostgreSQL concurrency.

## 9. Concurrency, idempotency and recovery

The retained two-process tests use independent Uvicorn apps/engines, one SQL session per
request and bounded pools of 5+5 per process. Barriers release 50/100 HTTP contenders;
they do not pre-open 100 PostgreSQL connections. Exact assertions were not weakened.

| Scenario in passing executions | Required and observed outcome |
| --- | --- |
| Capacity 1, 50 independent users | 1 created, 49 EVENT_FULL, allocated 1 |
| Capacity 20, 100 independent users | 20 created, 80 EVENT_FULL, allocated 20 |
| Same user/key, ten requests | One execution, nine exact replays, one reservation |
| Same user, ten distinct keys | One allocation, nine ACTIVE_RESERVATION_EXISTS |
| Same key on two event paths | Five matching successes, five key-reuse conflicts; one allocation |

Every passing target reconciles SQL counter bounds/equality, active-user uniqueness and
completed claims. Structured summary output is printed only after successful assertions.
These are bounded correctness workloads, not throughput/latency/production-load benchmarks.

The suite retains response loss after commit, simulated committed/uncommitted uncertain
commit outcomes, actual statement timeouts, rollback faults and competing state transitions.
Browser delivery loss is real. A physical network cut during COMMIT is not claimed.

## 10. Live restart, interruption and degraded behavior

Command: `./scripts/verify-local.ps1`. Audited run project:
`csrs-phase8-6ee2ecc3cc63`; zero host ports and its generated volume name verified first.

- API, frontend, Redis, worker and PostgreSQL each restarted successfully.
- Each verification preserved session, exact replay, current confirmed row, one expired row
  and counter equality. Ordinary down/up preserved the same application records.
- While PostgreSQL was stopped, API liveness returned 200, readiness 503 and a protected
  reservation read returned sanitized TEMPORARILY_UNAVAILABLE/503.
- After PostgreSQL returned, the same session/replay/confirmed state and counters recovered.
- Live reservation smoke passed **35 HTTP checks**, restoring original table counts.
- Live Redis available/outage/recovered modes each passed the results above.
- Scoped fixture cleanup succeeded; the generated project was stopped and its volumes retained.

The normal `csrs` database/network/services were not interrupted by this verifier. Earlier
isolated projects/volumes were also retained; no volume deletion was executed. No database
files were corrupted, and no public/shared service received stress traffic.

## 11. Security and dependency review

Source review covered password hashing/unknown-user verification, opaque session rotation and
revocation, HttpOnly/Secure/SameSite/host-only cookies, CSRF/source/content-type validation,
role/ownership and post-wait rechecks, sanitized validation/errors/logs, cache visibility and
quota boundaries, frontend memory-only secrets, escaped text/redirect allowlists, aborted/stale
responses and demo cleanup selectors. Reservation/auth/worker protocols remain unchanged.

`npm --prefix frontend audit --audit-level=low` returned **0 vulnerabilities**.
`pip-audit 2.10.1 --no-deps --disable-pip -r backend/requirements-dev.lock` returned
**No known vulnerabilities found**. The audit tool was installed only in an ignored local
tools environment. Host/container `pip check` reported no broken requirements. Project
dependency constraints/locks were not upgraded. npm ci is exercised by frontend startup.

Advisory scans are point-in-time known-advisory checks, not proof of all vulnerability absence.
The Python scan covers the pinned constraints; Linux installations need not install
platform-specific colorama/tzdata entries. OS image packages were not independently scanned.
No public TLS/managed service was tested. Current/history review found no tracked `.env`,
private-key bundle or matching known token pattern; example passwords/test credentials are
intentionally public local/test values. No actual credential was added to Git/evidence.

## 12. Accessibility, responsiveness and visual evidence

Chromium verifies 390/768/1440-pixel layouts, maximum-length titles/locations without horizontal
overflow, labels/heading structure, dialogs, Enter/Escape, initial/restored keyboard focus,
and axe WCAG 2 A/AA, 2.1 AA and 2.2 AA tagged scans. Zero violations were asserted on discovery,
detail, private history/active hold, organizer dashboard, dialog, login and registration.
Status names and polite messages remain present; timer seconds are not announced every tick.

Seven real PNGs were captured with account-address masks and visually inspected. An initial
discovery shot captured loading; the test was strengthened to wait for an enabled refresh
button and a real card, then all eight journeys/captures were rerun successfully.
See [evidence provenance](../evidence/README.md). This is not manual screen-reader verification,
formal WCAG certification, physical-device testing or Firefox/Safari coverage.

## 13. Regression commands and observed results

| Executed command/check | Result |
| --- | --- |
| First expanded backend image, full Pytest | 549 passed in 204.39 s |
| Post-audit full image before cookie-fixture correction | 554 passed, one setup failure in 237.00 s; accurately retained as a failed run |
| Targeted corrected production-cookie + config tests | 26 passed in 1.60 s |
| Final rebuilt image: `docker compose --profile test run --build --rm backend-test python -m pytest -q -p no:cacheprovider --tb=short` | **555 passed in 187.16 s**, no failures/skips |
| `pytest --collect-only -q -m integration` | 399/555 integration cases collected; execution is established by full run |
| `pytest --collect-only -q -m 'not integration'` | 156/555 unit/contract cases collected |
| New local-operation targets before final full run | Seven passed in 3.09 s; includes migration/fixture guards |
| Host `npm --prefix frontend test` after final frontend test edits | **71 passed**, two files; 23.54 s |
| `npm --prefix frontend run format:check` | Passed |
| `npm --prefix frontend run build` | Strict TypeScript and Vite passed; 146 modules, 5.75 s build |
| First retained Chromium suite | Seven passed before new session-expiration/capture coverage |
| Expanded and final Chromium runs | Eight passed in 1.3 m, then **eight passed in 1.2 m** after capture strengthening |
| Host/container Ruff lint and format | All checks passed; 70 Python files formatted |
| Alembic heads/current/check | 0002_worker_expiry; no new upgrade operations |
| Host/container pip check | No broken requirements |
| Full-stack wrapper startup and repeat startup | Passed; migration exit 0 and all required services running/reachable |
| Isolated audited recovery script | Passed with all outcomes in section 10 |
| Read-only reconcile.sql | 0 mismatches, 0 duplicate active pairs, 0 incomplete claims |
| Mermaid actual Chromium SVG render | Six diagrams rendered with positive dimensions |
| Initial documentation lint | Twelve Markdown files, zero errors; final expanded checks cover thirteen |

Final JS is 397.59 kB / 122.13 kB gzip and CSS 17.98 kB / 4.94 kB gzip. Two existing upstream
Zod PURE-comment warnings remain non-fatal. These build sizes/timings are local observations,
not performance guarantees. Supplemental subsets/repetitions overlap the suite and do not
increase its unique 555-case total.

## 14. Separate source self-audit, findings and fixes

This was a separate skeptical source pass after the initial 549-test/browser pass, not an
external reviewer or a restatement of green tests. It inspected actual locking/claim/time/
commit paths, worker discovery/conditional release, route quota/authorization order, session
and browser recovery, migration transaction boundaries, Compose isolation, fixture selectors,
native exit handling and future-origin configuration.

| Severity | Finding and resolution | Evidence |
| --- | --- | --- |
| MEDIUM | Baseline full-stack startup required manual migrations/worker and lacked frontend readiness. Added transaction-locked migration gate, full-stack wrapper and HTTP frontend health. | Actual startup, fresh isolated DB, lock-wait/persistence and rollback tests |
| MEDIUM | A future HTTPS/production origin could silently retain known public database example passwords. Reject those values in production without exposing them in errors. | Three new configuration cases and preserved real production-cookie test |
| MEDIUM | Recovery helper initially accessed an expired/detached ORM user after commit. Preserve fixture scalar state; clean committed fixtures if subsequent preparation fails. | Initial isolated run failed honestly; corrected isolated run and fault-cleanup test pass |
| MEDIUM | A successful shutdown in finally could overwrite the recovery verifier's native failure exit. Explicit failure state now survives operation/cleanup/down errors. | Source review, nonzero failed runs, successful audited verifier; no assertion disabled |
| LOW | Default runtime logs could grow unbounded locally. Cap log size/count. | Compose config/source and live runtime configuration |
| LOW | Capture could precede public data loading. Require a real discovery card before screenshot. | Visual inspection detected it; final eight-journey rerun and populated capture |

The production-cookie setup failure was caused by the new guard doing its intended work.
The test now provisions a temporary generated LOGIN role with table DML/usage grants only
inside its disposable test database, then removes its grants/role. All original Secure,
HttpOnly, SameSite, Path, prefix, Domain absence, TTL and real-login assertions remain.

No BLOCKER/HIGH finding remains and all actionable MEDIUM findings above are resolved.
No event/reservation/auth transaction algorithm, worker lock order, database constraint,
idempotency semantics or Redis failure policy was weakened. Non-Chromium/manual accessibility,
public hardening and production scalability are explicit limitations rather than passed gates.

## 15. Documentation, future hosting and CI

Created DEMO_GUIDE.md, INTERVIEW_GUIDE.md, FUTURE_DEPLOYMENT.md, this validation,
the twelve-section Phase 8 explanation and organized evidence. README now explains the
engineering problem, accurate local status, startup/shutdown, URLs, verification and limits.
Architecture/database/security/decisions/phases/infrastructure notes reflect actual local
behavior; historical phase evidence and PROJECT_HANDOFF.md are preserved.

The future-hosting plan separates implemented configuration/transactions from missing static
serving/proxy, private managed PostgreSQL/Redis, independent worker hosting, HTTPS/cookies,
proxy identity/CORS review, secrets, backups/observed restore, monitoring and cost checks.
No current hosting price or free-plan availability is assumed.

CI retains backend lint/format/unit/contract/PostgreSQL/Redis/migration, frontend formatting/
tests/typecheck/build, Compose, reservation smoke, Chromium, failure evidence, worker and
Redis available/outage/recovery. It adds migration-gated full startup and the isolated
PowerShell recovery verifier. **Hosted Phase 8 CI has not run** because nothing is committed
or pushed. Historical Phase 7 Actions links are identified as historical, not new evidence.

Final hygiene checked 70 local Markdown links/anchors, all 39 intended paths and zero staged
files. A known-token/private-key-pattern scan covered 279 historical blobs plus 137 current
tracked files, with zero matches; changed/new text also passed the bounded scan. Historical
filename review found no tracked .env/private-key bundles. This does not prove absence of
every possible credential format. Critical auth/reservation/worker/model/migration/contract
source, dependency locks and PROJECT_HANDOFF.md have zero diff. `git diff --check` passed.

Compose design was cross-checked against Docker's official
[startup-order documentation](https://docs.docker.com/compose/how-tos/startup-order/) and
[merge/reset specification](https://docs.docker.com/reference/compose-file/merge/).
Local execution used Docker/Compose 29.9.2/5.6.1, Python 3.12.16 container runtime, PostgreSQL 17,
Redis 7.4 and Node.js 24.22.1. Docker/socket/advisory access required executor escalation; no
security control was bypassed. Initial restricted npm networking/Chromium cache access failed;
authorized reruns succeeded. Audit/render tools remain ignored under .local.

## 16. Remaining limitations

- Local Vite and development/test images are not hardened public production packaging.
- No cloud deployment, public HTTPS, managed TLS/failover, backup/restore, production alerting,
  production benchmark or operating SLA is claimed.
- Hot-event writes serialize; quotas/cache reset on Redis restart; proxy users share peer limits.
- Metadata may remain stale within absolute TTL; SQL always controls visibility/admission.
- Worker latency depends on backlog/locks/outages; readiness does not prove worker progress.
- Session/idempotency retention scheduling, account recovery/verification/MFA and unrelated
  product features remain absent. Cookie protection does not substitute for them.
- Correctness tests can surface controlled transient 503s when local request budgets are
  exhausted. A failed supplemental race is recorded below; do not present it as a clean pass.
- Isolated verifier volumes are intentionally retained, including an initial failed fixture
  project; no automatic broad/destructive volume cleanup is supplied.

## 17. Final follow-up evidence

Three fresh quiet-stack executions of the unchanged five race targets passed in **17.34,
17.44 and 17.43 seconds**. Every run observed the exact 1/49 and 20/80 final-seat outcomes,
nine same-key replays, one different-key allocation and the documented path-fingerprint
conflicts. Counters/uniqueness/completed outcomes reconciled after each target.

One earlier supplemental run failed its strict capacity-20 assertion: 20 created, 74
EVENT_FULL, with unexpected responses including controlled TEMPORARILY_UNAVAILABLE/503.
The six remaining outcomes' full histogram was truncated by pytest; it was not independently
retained. That run is not counted as passing or SQL-reconciled. Concurrent collection/quality
commands were active, but the exact pool/statement/connection timeout source was not
instrumented. The result demonstrates that local resource conditions can affect availability;
it does not establish a capacity defect or a performance limit. Assertions/timeouts were
unchanged for the three subsequent passes. Keep demonstrations on a quiet stack.

The actual normal-project wrappers were then tested: scoped demo prepare twice, local stop,
full start, status and cleanup. PostgreSQL cluster identity and the three generated users/
three events survived; cleanup restored the original five-table counts (0 users, 14 existing
sessions, 0 events/reservations/idempotency records). No existing sessions were deleted.
The demo CLI entry point was exercised with getpass supplied an in-memory random test password;
no credential was printed or stored. Interactive terminal entry itself was not manually tested.

Final main-stack worker smoke expired five holds, released exactly five seats to allocation 0,
passed three HTTP checks and cleaned six generated users/one event. Reservation smoke passed
35 checks and restored counts. Read-only reconciliation again returned zero in all three
categories. All six documented localhost URLs returned 200, and runtime OpenAPI exactly
matched the 21-path/23-operation snapshot.

A mocked-Docker negative control returned failure on config and success on final down;
the recovery verifier's caller still observed exit 1. This verifies the failure-propagation
fix without stopping real services. Six Mermaid diagrams rendered as SVG in actual Chromium.
All seven PNGs were inspected; the populated discovery recapture replaced the loading shot.
Sanitized output and image hashes are in [phase-8-results.txt](../evidence/phase-8-results.txt).

## 18. Complete changed-file manifest

The final generated manifest below includes modified text, new scripts/docs and seven intended
PNG artifacts. Ignored logs/tools/build caches are excluded. No file was staged.

**39 files: 17 modified, 22 added, 0 deleted; 0 staged.**

| State | Path | Purpose |
| --- | --- | --- |
| Modified | `.env.example` | Public browser path and explicit local/production configuration notes. |
| Modified | `.github/workflows/ci.yml` | Migration-gated full stack, preserved browser failure artifacts, isolated recovery gate. |
| Modified | `README.md` | Portfolio overview, tested setup/shutdown, verification, guides and honest limits. |
| Modified | `backend/Dockerfile` | Include local verification scripts in built images. |
| Modified | `backend/scripts/frontend_fixture.py` | Expire only a scoped browser session using stdin-supplied cookie hashes. |
| Added | `backend/scripts/reconcile.sql` | Read-only repeatable-read counter/bounds/uniqueness/completion reconciliation. |
| Added | `backend/scripts/smoke_recovery.py` | Generated durable session/replay/worker and database-outage assertions. |
| Modified | `backend/src/csrs/config.py` | Reject known public example database passwords in production settings. |
| Added | `backend/src/csrs/demo.py` | Explicit local UUID-scoped demo setup/status and guarded cleanup. |
| Added | `backend/src/csrs/migrate.py` | Advisory-locked transactional upgrade/drift entry point. |
| Modified | `backend/tests/integration/test_authorization.py` | Real generated test database role preserves all HTTPS-cookie assertions. |
| Added | `backend/tests/integration/test_local_operations.py` | Seven real PostgreSQL migration/fixture safety and fault-cleanup cases. |
| Modified | `backend/tests/integration/test_reservation_transactions.py` | Sanitized scenario summaries after unchanged race assertions. |
| Modified | `backend/tests/unit/test_config.py` | Three production public-example-password rejection cases. |
| Added | `compose.validation.yaml` | Remove host ports for generated-project recovery verification. |
| Modified | `compose.yaml` | Startup gates, frontend health, restarts, stable API and bounded logs. |
| Added | `docs/DEMO_GUIDE.md` | Preparation, safe fixtures, five-minute/deep walkthrough and troubleshooting. |
| Added | `docs/FUTURE_DEPLOYMENT.md` | Bounded future hosting/security/operations planning, no resources. |
| Added | `docs/INTERVIEW_GUIDE.md` | Simple technical explanations, tradeoffs and interview questions. |
| Modified | `docs/architecture.md` | Accurate local boundary, diagrams and migration/recovery architecture. |
| Modified | `docs/database.md` | Separate startup migration gate and unchanged schema/authority. |
| Modified | `docs/decisions.md` | Local-first, serialized migration and isolated fixture decisions. |
| Added | `docs/evidence/README.md` | Capture provenance, reproduction, privacy and historical CI boundaries. |
| Added | `docs/evidence/confirmed-reservation.png` | Real Chromium screenshot; account identity masked; source documented. |
| Added | `docs/evidence/discovery.png` | Real Chromium screenshot; account identity masked; source documented. |
| Added | `docs/evidence/event-creation.png` | Real Chromium screenshot; account identity masked; source documented. |
| Added | `docs/evidence/event-detail.png` | Real Chromium screenshot; account identity masked; source documented. |
| Added | `docs/evidence/held-countdown.png` | Real Chromium screenshot; account identity masked; source documented. |
| Added | `docs/evidence/organizer-dashboard.png` | Real Chromium screenshot; account identity masked; source documented. |
| Added | `docs/evidence/phase-8-results.txt` | Sanitized observed outcomes, failures, commands and image hashes. |
| Added | `docs/evidence/reservation-history.png` | Real Chromium screenshot; account identity masked; source documented. |
| Added | `docs/validations/phase-8-validation.md` | Complete implementation, verification, audit, limitations and review manifest. |
| Added | `docs/phase-explanations/phase-8-explanation.md` | Twelve-section beginner explanation. |
| Modified | `docs/phases.md` | Owner-revised localhost-only Phase 8 acceptance scope. |
| Modified | `docs/security.md` | Local fixture/isolation guards and future configuration boundary. |
| Modified | `frontend/e2e/journeys.spec.ts` | Opt-in masked screenshots, real discovery wait and session-expiration journey. |
| Modified | `infra/README.md` | Current service/startup/persistence/isolation operations. |
| Added | `scripts/local.ps1` | Check prerequisites, preserve .env, start/stop/status the full stack. |
| Added | `scripts/verify-local.ps1` | Generated project isolation checks, real recovery and reliable failure exit. |

## 19. Final local acceptance and review gate

- [x] Localhost-only scope; no provider/resource/public deployment.
- [x] Complete stack startup with migration sequencing, frontend health and worker enabled.
- [x] Safe configuration, persistent PostgreSQL and unchanged migration head/schema.
- [x] Attendee/organizer real-browser workflows, retry/reload and session expiration.
- [x] Real PostgreSQL concurrency, durable replay, worker recovery and Redis policies.
- [x] Controlled isolated service restart/down-up/dependency-outage verification.
- [x] Security/dependency/source audit, corrections and final full regression.
- [x] Responsive/keyboard/axe checks and sanitized reproducible portfolio evidence.
- [x] Demo/interview/future-hosting/validation/twelve-section explanation documentation.
- [x] Original constraints/protocols/assertions and CI coverage preserved.
- [x] Handoff completion unchanged; hosted Phase 8 CI awaits approved publication.
- [x] Nothing staged, committed, pushed, merged, released or cloud-deployed.

Stop for external review. This document does not authorize publication or mark the handoff
complete; the owner's finalization gate remains in force.

## 20. Authorized finalization review and 503 investigation

The owner approved finalization on 2026-10-28, subject to fresh gates and hosted CI. Starting
state matched exactly: main at 6bf24b0203bf0c752c2edf5e668152c3945f07c2, 39 intended files
(17 modified, 22 added), zero staged. Remote main matched that SHA. Its exact baseline
[Actions run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40507068848)
was independently read as completed/success. Handoff completion remains gated on hosted
implementation CI, followed by a separately committed and verified handoff update.

### Bounded investigation of the supplemental 503

Two fresh, sequential executions of the unchanged five two-process race targets passed:
5 passed/35 deselected in 17.94 seconds and 17.64 seconds. Both retained 50/100 contenders,
the original 3-second connection/pool and 3000-ms statement budgets, pools of 5+5 per API,
and all strict HTTP/state/counter assertions. Outcomes were again 1/49 and 20/80, one
same-key execution plus nine replays, and one same-user/different-key allocation.

A temporary ignored import observer preserved the original application error handlers and
recorded sanitized exception class/SQLSTATE/pool counts if a database 503 occurred. It
recorded no database-503 event. Status observations contain only 201/409; assertions provide
the complete response checks. Shared-file diagnostic writes did not capture every response,
so the diagnostic file itself is not presented as a complete response histogram. No
credentials, SQL strings, resource IDs or request bodies were collected. An initial observer
imported anyio before pytest assertion rewriting and failed collection; delaying that import
fixed the observer without disabling warnings or changing application/tests.

PostgreSQL logs over the instrumented interval showed zero statement-timeout, connection-limit
or unexpected-shutdown messages. Test PostgreSQL and Redis remained healthy with zero
container restarts. Redis quotas/cache are disabled in these SQL correctness fixtures, so
Redis is not on their command path. Current Alembic remained at 0002_worker_expiry without
drift. These observations correlate the new passing runs; they cannot reconstruct the
original failed run, whose detailed exception/SQLSTATE and full response histogram were not
retained. The precise original cause remains unproven. No reproducible BLOCKER/HIGH
correctness or reliability defect was found, no assertion or timeout was relaxed, and no
production performance level is claimed. The original failed run remains in sections 13/17
and the sanitized evidence file.

### Fresh finalization regression gates

All following commands ran again after the external review and bounded investigation, before
staging the implementation. No production source or test assertion changed during the
investigation. Eighteen changed code/configuration files were fingerprinted and checked
unchanged through these gates; publication wording and observed results were updated only
in the existing Phase 8 documents. The implementation still contains 39 intended files.

| Gate | Fresh observed result |
| --- | --- |
| Documented local.ps1 stop/start | Passed; same PostgreSQL cluster and five-table counts; .env hash unchanged |
| Complete rebuilt-image backend suite | 555 passed, no failures/skips, in 108.46 seconds |
| Frontend tests | 71 passed in 8.59 seconds |
| TypeScript/Vite build | Passed; 146 modules, 2.32 seconds; unchanged artifact sizes |
| Prettier | Passed |
| Chromium real-backend journeys | Eight passed in 42.7 seconds; captures deliberately not overwritten |
| Ruff lint/format | Passed; 70 Python files already formatted |
| Alembic heads/current/check | 0002_worker_expiry; no new upgrade operations |
| pip check | No broken requirements |
| npm audit / pip-audit pinned lock | Zero npm vulnerabilities; no known Python vulnerabilities |
| Worker backlog smoke | Five EXPIRED, allocated 0, three HTTP checks; six users/one event cleaned |
| Reservation smoke | 35 HTTP checks, original counts restored |
| Read-only reconciliation | Zero counter/bounds mismatches, duplicate active pairs and incomplete claims |
| Isolated full recovery verifier | Passed, including actual dependency outages, sessions/replay, confirmed preservation, ordinary down/up and scoped cleanup |
| Redis available/outage/recovered | Each passed 13 checks, one worker expiration and zero invariant mismatches |
| Disposable test resources | Zero generated databases, zero generated cookie-test roles, zero keys in dedicated Redis database 15 |
| Compose config | Passed |
| Mermaid | Six diagrams rendered again in actual Chromium |
| Documentation | Thirteen Markdown files lint clean; local links/anchors checked |
| Evidence review | Seven PNG hashes match the reviewed manifest; account identities masked; no traces/videos proposed |
| Critical source preservation | No diff in auth/reservation/worker algorithms, models/migrations, contracts or dependency locks |

The isolated finalization verifier used generated project csrs-phase8-fda960e518c8 and
verified its volume scope and zero host ports before interruption. Its containers were
stopped and volume retained. The normal application remained local and its data was not
deleted. Hosted implementation CI is the next gate; its actual SHA/run and subsequent
handoff publication are recorded in PROJECT_HANDOFF.md after that gate passes.
