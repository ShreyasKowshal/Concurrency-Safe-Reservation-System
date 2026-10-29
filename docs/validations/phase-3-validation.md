# Phase 3: organizer event management verification

Baseline: `9dc8f86f21546499dc10572c65938acff8df68a5` on `main`.
Date: 2026-10-25 (Asia/Calcutta).

**Implemented and locally verified; uncommitted and awaiting review.** No commit, push,
merge, Phase 4 work, or Phase 4 handoff was performed.

## Implemented scope and contracts

Phase 3 adds nine event API operations: public published-event list/detail, organizer own
list/detail, draft creation, permitted metadata editing, capacity changes, publication, and
closing. Authentication is reused; no second auth system or new dependency was introduced.
The React health screen only changes phase/scope wording. No event form was added.

The earlier human contract had no owner-only single-event retrieval route. The added
`GET /api/v1/organizer/events/{event_id}` allows private draft/closed retrieval without changing
public PUBLISHED-only visibility or implementing a reservation dashboard. API/OpenAPI now
document exact fields, UTC input, capacity bounds, pagination, errors, and lifecycle policies.

Drafts may have past but structurally valid schedules; publication requires strictly future
start/deadline using PostgreSQL time after the event lock. Published start/deadline fields
cannot be patched, even with unchanged values. Closed events are read-only, repeated
publish/close returns 409, and no reopening/cancellation/delete operation was added.
Public discovery is status-based, including full/past PUBLISHED events until explicitly closed.

## API and authorization

| Method/path | Success | Protection |
| --- | --- | --- |
| GET /api/v1/events | 200 public summaries/page cursor | PUBLISHED filter |
| GET /api/v1/events/{event_id} | 200 public detail | PUBLISHED filter; otherwise 404 |
| GET /api/v1/organizer/events | 200 own summaries/page cursor | Active authenticated organizer |
| GET /api/v1/organizer/events/{event_id} | 200 own detail/allocation | Organizer + stored ownership |
| POST /api/v1/organizer/events | 201 draft | Organizer + session/CSRF/source/JSON |
| PATCH /api/v1/organizer/events/{event_id} | 200 event | Owner + same mutation protections |
| PATCH /api/v1/organizer/events/{event_id}/capacity | 200 event | Owner + event lock + allocation bound |
| POST /api/v1/organizer/events/{event_id}/publish | 200 published event | Owner + event lock + publication checks |
| POST /api/v1/organizer/events/{event_id}/close | 200 closed event | Owner + event lock + forward transition |

All event responses use no-store. Invalid/foreign private IDs produce controlled 404 responses.
Mutation services check the current session, active user, organizer role, and CSRF in their
transaction, and repeat after waiting for an event lock. The existing HTTP guard validates
Origin/Referer and JSON media type. Inputs never permit owner/status/counter assignment.
Validation removes submitted values; controlled 409/422 errors and safe database 503s share
the established error format. OpenAPI documents cookie + CSRF together and retains URL/query
parameters. Event 422 schemas cover both sanitized detail and controlled event-error bodies.

## Database and transaction boundary

No SQLAlchemy model, constraint, index, or Alembic migration changed. Revision remains
`0001_foundation`. Every existing-event write uses an owned event `SELECT ... FOR UPDATE`
inside an explicit READ COMMITTED transaction. Authorization/state are refreshed after waits.
Create assigns its owner from the session; metadata/capacity/lifecycle commands never change
the owner or allocation counter. Flush is followed by commit before success returns.

Capacity edits compare against the stored count, including overdue persisted HELD rows.
They do not expire holds. Phase 4 must integrate shared due-hold cleanup under this same
event lock before capacity edits/admission, without an independent commit or reversed lock
order. Closing leaves allocations/reservations untouched. No booking correctness or
performance claim is made by these event-only tests.

## Verification results

Environment: Docker Desktop Linux engine on Windows, container Python 3.12.15, Pytest 9.1.1,
PostgreSQL 17, Node.js 24.22.1, and Vite 7.3.7. Existing dependency constraints/lockfiles are
unchanged; only backend package/API version and description advance to 0.3.0.

Docker was installed per user at
`C:\Users\ASUS\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`.
That directory was added to the verification command's PATH so Docker could find its desktop
credential helper. The table uses `docker` as shorthand for that executable; no credentials
were extracted, printed, or added to files.

| Check/command | Actual final result |
| --- | --- |
| `docker compose config --quiet` | Passed; exit 0 |
| `docker compose up --build -d --wait --wait-timeout 120` | Images built and development services ready; exit 0 |
| `docker compose --profile test run --build --rm backend-test` | **323 passed in 26.81s**, no failures/skips; exit **0** |
| `python -m pytest backend/tests --collect-only -q -m integration` | 216/323 collected; 107 deselected; exit 0 |
| `python -m pytest backend/tests --collect-only -q -m 'not integration'` | 107/323 collected; 216 deselected; exit 0 |
| `docker compose exec -T backend python -m ruff check --no-cache .` | All checks passed; exit 0 |
| `docker compose exec -T backend python -m ruff format --check --no-cache .` | 42 files already formatted; exit 0 |
| Host `python -m ruff check --no-cache backend` and `ruff format --check --no-cache backend` | Passed; 42 formatted files; exits 0 |
| `docker compose exec -T backend python -m pip check` | No broken requirements; exit 0 |
| `docker compose exec -T backend python -m alembic heads` | `0001_foundation (head)`; exit 0 |
| `docker compose exec -T backend python -m alembic current` | `0001_foundation (head)`; exit 0 |
| `docker compose exec -T backend python -m alembic check` | No new upgrade operations detected; exit 0 |
| `docker compose exec -T frontend npm run build` | `tsc --noEmit` and Vite build passed (30 modules); exit 0 |
| `docker compose exec -T redis redis-cli ping` | PONG; exit 0 |
| Runtime OpenAPI versus `docs/contracts/api.openapi.yaml` | Exact equality; version 0.3.0, 14 paths / 16 operations; exit 0 |
| Markdown lint on README and seven changed/new Markdown documents | 8 files, zero errors; exit 0 |
| Mermaid parser on architecture and Phase 3 explanation | All 4 diagrams parsed; exit 0 |
| `git diff --check`, local-reference and secret-pattern review | Passed; no sensitive/generated files in the change manifest |

The Python collection commands used the existing `.venv\Scripts\python.exe`; collection
only counts cases. The decisive complete container run actually executed **107 unit/contract
and 216 PostgreSQL integration cases**, including all retained Phase 1/2 behaviors. The 323
cases are not all new tests: Phase 3 adds 153 cases to the earlier 170-case suite. Test duration
is Pytest's elapsed time, not a reservation throughput/latency measurement.

The existing migration tests still exercise clean upgrade, metadata parity, non-destructive
re-upgrade, and downgrade/re-upgrade on generated disposable databases only. Development
schema verification used current/check, without downgrade, data removal, or volume deletion.
The test database factory's existing `csrs_phase2_<uuid>_test` prefix was retained; final
inspection found **zero** leftover generated databases on postgres-test.

### Concurrency, rollback, and security evidence

- Every mutation checks cookie/session, active user/organizer role, CSRF, and source/JSON.
  Thirty parameterized cases exercise missing/foreign token, missing cookie, wrong/missing
  origin, and wrong media type across the five mutation operations.
- Visibility tests distinguish public PUBLISHED rows from private DRAFT/CLOSED rows. Own
  lists/details never grant another organizer access. Unknown and foreign private IDs use 404.
- Partial-update tests verify combined schedule validation and atomic rollback. Input cases
  include forged ownership/status/counter, explicit nulls, empty PATCH, numeric/boolean/overflow
  capacity, naive/epoch timestamps, UTC-boundary overflow, whitespace, and field lengths.
- Four real PostgreSQL lock-wait cases observe `pg_blocking_pids()` before the holder commits:
  capacity sees a newly committed allocation count, edit/close see a competing CLOSED state,
  and publication sees a newly stale deadline. Independent connections and actual commits
  are used; no mocked database is presented as lock evidence.
- Four further waits expire/revoke the security session or deactivate/demote the user while
  the command is blocked. All are rejected after the lock without modifying the event.
- A real 100ms statement timeout while waiting returns a sanitized 503 and permits a later
  valid retry. Five injected post-flush failures verify rollback before success for each
  mutation operation.
- Seeded overdue holds remain untouched by Phase 3. Reductions below their stored allocation
  are refused, while equal/increased capacity is accepted. Seeded booking rows are test data,
  not reservation API functionality or evidence of a completed no-overbooking service.

An early host-only test attempt encountered duplicate module basenames; the new unit file
was renamed to `test_event_inputs.py`. The next host run stalled in TestClient health checks
and was interrupted (exit 1), so it is not counted as successful. The complete Linux-container
run above executes those same cases and passes. An initial Docker build could not locate its
credential helper until the per-command PATH was corrected; the final builds passed.
These were resolved verification attempts; no failing/skipped case is concealed in the final
323-test summary and no assertion was weakened to obtain it.

### Live HTTP verification and cleanup

A cookie-aware one-off smoke ran through the real frontend service's Vite `/api` proxy,
with Host/Origin matching `localhost:5173`. It used a unique temporary account and random
in-memory password, promoted only that account using the existing administration service,
and logged in again. Only response statuses were printed, never credentials/token bodies.
Command: `Get-Content -Raw .local/phase-3-http-smoke.py | docker compose exec -T backend python -`.
The ignored local helper is a verification aid, not a new production endpoint or dependency.

All **31** expected status checks passed:

| Flow/check | Observed HTTP |
| --- | --- |
| Frontend, direct/proxied liveness/readiness, docs, OpenAPI | 200 |
| Anonymous organizer list | 401 |
| CSRF bootstrap, registration, attendee login | 200, 201, 200 |
| Attendee event creation | 403 |
| Current user after administrative promotion revoked its session | 401 |
| Fresh bootstrap and organizer login | 200, 200 |
| Draft creation, owner detail/list | 201, 200, 200 |
| Public access to draft | 404 |
| Missing CSRF or untrusted Origin on edit | 403, 403 |
| Draft edit, capacity edit, publication | 200, 200, 200 |
| Published public detail/list | 200, 200 |
| Published start edit or repeated publication | 409, 409 |
| Close, public access after closing, logout | 200, 404, 204 |

The temporary organizer's events, that user's sessions, any tracked anonymous cookie-digest
rows from the smoke, and that user were removed in a finally block using scoped SQL filters.
Before and after counts were identical: users=0, sessions=0, events=0, reservations=0,
idempotency_records=0. Existing records and volumes were not deleted or reset.

An independent Windows-host urllib check also returned **HTTP 200** for all six published
localhost URLs: frontend `/`, frontend `/api/v1/health/ready`, backend liveness/readiness,
backend `/docs`, and backend `/openapi.json`. Health responses had no-store headers.
The account/event smoke is an HTTP test, not a browser UI or browser-testing-framework claim.

Final Compose state: backend, PostgreSQL, Redis, and postgres-test running/healthy. Frontend
running and HTTP-verified; it has no configured Docker health probe. No paid service was used.

## Files changed

**25 intended files: 11 added and 14 modified.**

Added:

```text
backend/src/csrs/api/events.py
backend/src/csrs/events/__init__.py
backend/src/csrs/events/errors.py
backend/src/csrs/events/pagination.py
backend/src/csrs/events/schemas.py
backend/src/csrs/events/service.py
backend/tests/integration/test_event_transactions.py
backend/tests/integration/test_events.py
backend/tests/unit/test_event_inputs.py
docs/validations/phase-3-validation.md
docs/phase-explanations/phase-3-explanation.md
```

Modified:

```text
README.md
backend/pyproject.toml
backend/src/csrs/api/openapi.py
backend/src/csrs/main.py
backend/tests/integration/conftest.py
backend/tests/unit/test_health.py
docs/architecture.md
docs/concurrency.md
docs/contracts/api.md
docs/contracts/api.openapi.yaml
docs/contracts/health.openapi.yaml
docs/decisions.md
docs/security.md
frontend/src/App.tsx
```

The health OpenAPI change is version/description metadata only; health paths/response schemas
remain unchanged. CI/Compose configuration, migrations, model constraints, dependencies, and
all Phase 1/2 validation/explanation reports remain unchanged. Existing CI discovers the added
tests automatically; its workflow does not need a Phase 3-specific job.

Review covers input boundaries, private visibility, owner/role checks, lifecycle changes,
post-lock authorization, transaction rollback/timeouts, pagination filters, schema parity,
and API/documentation agreement. No hardcoded production secret or debug endpoint was added.
The existing ignore rules exclude `.env`, virtual environments, caches, local verification
helpers, and frontend build output. No such files are tracked or staged.

## Acceptance gate and Git status

- [x] Organizer creates a validated server-owned draft; attendees/anonymous users are denied.
- [x] Public/owner listing and details enforce visibility with bounded scoped pagination.
- [x] Metadata and capacity edits enforce lifecycle, schedule, ownership, and allocation bounds.
- [x] Only DRAFT -> PUBLISHED -> CLOSED is accepted, with post-lock publication time checks.
- [x] Existing-event writes use PostgreSQL event-row locks and recheck authorization after waits.
- [x] Unit/real-PostgreSQL/regression/contract/migration tests and other checks pass as recorded.
- [x] Documentation and the beginner guide match the implemented scope and deferred work.
- [x] No Phase 4+ implementation, commit, push, or merge was performed.

Branch remains main at the baseline commit, with the 25 files above unstaged for review.
The index is empty. The working tree is intentionally not clean because this phase has not
been committed. No known Phase 3 implementation blocker remains; ready for user review.

## Limitations and deferred work

No holds, confirmation/cancellation, reservation idempotency execution, expiration process,
Redis client/cache/limiter, availability/dashboard endpoint, event-management frontend,
payments, or cloud provisioning was implemented. Existing manual session maintenance remains.
Event commands have no idempotency replay guarantee. Public lists filter publication state,
not booking eligibility; pagination is not a frozen snapshot across concurrent edits.
Capacity reductions may be conservatively refused until Phase 4 adds due-hold cleanup.
Hosted Phase 3 CI cannot run before an authorized commit/push; no hosted result is claimed.
