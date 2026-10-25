# Phase 2: schema and authentication verification

Date: 2026-10-25 (Asia/Calcutta). Baseline: Phase 1 commit
`cc4f3df452e2ce49ca5d496705d44d38543499e1` on `main`.

**Implemented and locally verified; uncommitted and awaiting review.** No Phase 3 event
management or Phase 4 reservation operation is implemented. Nothing was committed or pushed
for Phase 2. Hosted CI has not run for these uncommitted changes.

## Files and responsibilities

- `backend/src/csrs/models.py`: users, sessions, events, reservations, idempotency records;
  UUIDs, timestamps, named constraints, foreign keys, and partial/lookup indexes.
- `backend/migrations/versions/0001_foundation_foundation_schema_and_sessions.py`:
  explicit initial upgrade/downgrade; migration environment now uses model metadata and
  supports an explicitly supplied isolated connection for tests.
- `backend/src/csrs/auth/`: Argon2/token/email primitives, schemas, safe errors, HTTP source/
  cookie policy, transaction services, role/ownership dependencies, local admin operations.
- `backend/src/csrs/api/auth.py`, `api/openapi.py`, `main.py`: five auth routes, documented
  cookie/CSRF schemes, no-store auth responses, sanitized validation/database errors.
- `backend/src/csrs/cli.py`: explicit local organizer promotion and bounded session cleanup.
- Integration fixtures/tests: generated PostgreSQL databases, auth/CSRF/security cases,
  rollback/concurrent pre-session consumption, roles, constraints, and migration checks.
- Unit tests: crypto, validation bounds, origin parsing; existing health/config checks retained
  and route/spec assertions updated for the additional authentication endpoints.
- Settings, example environment, dependency metadata/lock, OpenAPI specifications,
  README/architecture/security/schema/API/decision docs, CI migration step, and frontend
  phase/scope text updated. The React architecture and health UI are preserved.

## Schema and reservation boundary

Five application tables are created. PostgreSQL also has Alembic's version table.
Roles/session kinds/states are constrained strings; UUIDs and creation timestamps have server
defaults. References use RESTRICT. Normalized email and session cookie digest are unique.
One partial unique index permits at most one persisted HELD/CONFIRMED reservation per user/event.
Indexes support organizer events, public event ordering, booking history, expiration lookup,
and user-scoped idempotency uniqueness. State/time checks reject inconsistent confirmation,
cancellation, and expiration timestamps. Idempotency response completeness handles SQL NULL
explicitly and restricts completed bodies to JSON objects.

The event CHECK bounds allocated_seats between zero and capacity. Equality with the sum of
held/confirmed reservation rows cannot be enforced by that CHECK. The documented event-lock
transaction protocol and reconciliation tests still belong to the later booking implementation.
No claim of overbooking prevention or reservation performance is made at this phase.

## Authentication and authorization

| Endpoint | Implemented behavior |
| --- | --- |
| GET /api/v1/auth/csrf | Valid session's stable CSRF token, or fresh 15-minute anonymous pre-session |
| POST /api/v1/auth/register | Validated email/password; ATTENDEE only; fresh anonymous session; no automatic login |
| POST /api/v1/auth/login | Generic credential failure or new authenticated cookie/token; 8-hour absolute expiry |
| POST /api/v1/auth/logout | CSRF-protected revocation, cookie clearing, empty 204 |
| GET /api/v1/auth/me | Authenticated active user's id/email/role only |

Argon2id parameters are explicit: 19,456 KiB, two iterations, one lane, fresh salts. Registration
passwords are 15-128 characters with no truncation/whitespace normalization. Old parameters
are upgraded after successful verification. Email is canonical ASCII/lowercase; no DNS lookup.

Cookie secrets and independent synchronizer tokens are 256-bit random values. Only cookie
SHA-256 digests are stored for authentication. HTTP localhost uses a host-only HttpOnly,
SameSite=Lax cookie; HTTPS uses Secure and the `__Host-` prefix. No JWT or browser token storage
was introduced. Database clock and current user active state govern session validity.

Anonymous and authenticated mutations require JSON, their session's CSRF token, and trusted
Origin or Referer fallback. Explicit invalid/null/duplicate Origin never falls back. A login
deletes the anonymous session and issues independent authenticated secrets. Registration/login
revalidate the locked pre-session after expensive password work; commits precede responses.
Failed mutations roll back account/session changes atomically.

Role guards allow organizers to retain attendee capabilities. Resource ownership mismatches
return 404. Guards are tested on test-only probe routes; no production organizer/event routes
were added. The CLI promotes an existing active user and revokes old sessions. Public
registration rejects role, IDs, active flags, and all extra fields.

## Final test evidence

Environment: Docker Desktop Linux/WSL2 on Windows; container Python 3.12.15, Pytest 9.1.1,
PostgreSQL 17.11, Node.js 24.22.1, npm 11.19.1, Vite 7.3.7. Dependencies are pinned through
the existing constraints/lock workflow, including Argon2 and email-validation dependencies.

| Command | Actual final result |
| --- | --- |
| `docker compose config --quiet` | Passed, exit 0 |
| `docker compose up --build -d --wait --wait-timeout 120` | Images built, stack started; exit 0 |
| `docker compose --profile test run --build --rm backend-test` | **170 passed in 9.86s**, no failures/skips; exit **0** |
| `docker compose exec -T backend python -m ruff check --no-cache .` | All checks passed; exit 0 |
| `docker compose exec -T backend python -m ruff format --check --no-cache .` | 33 files already formatted; exit 0 |
| `docker compose exec -T backend python -m pip check` | No broken requirements; exit 0 |
| `docker compose exec -T backend python -m alembic current` | `0001_foundation (head)`; exit 0 |
| `docker compose exec -T backend python -m alembic check` | No new upgrade operations detected; exit 0 |
| `docker compose exec -T frontend npm run build` | TypeScript and Vite build passed; exit 0 |
| `docker compose exec -T backend python -m csrs.cli --help` | Admin entrypoint available; exit 0 |

The 170 cases comprise 54 unit/contract cases and 116 PostgreSQL integration cases.
Tests cover all Phase 1 health/config checks alongside registration/login/logout, Argon2
verification and rehash, generic invalid/inactive credentials, revoked/expired/malformed sessions,
token rotation and replay, missing/foreign CSRF, Origin/Referer handling (including malformed
configured origins, whitespace, and empty user-info), wrong media type,
HTTPS/local cookie flags, role escalation, ownership, validation redaction, and session cleanup.
Deterministic tests also expire a pre-session during credential work, inject failure after
account insertion, and run competing registrations/logins sharing a pre-session.

Integration tests use new `csrs_phase2_<uuid>_test` databases on postgres-test. The provided
test connection must end in `_test` and have CREATEDB permission. Only generated databases
are truncated/downgraded/removed. Clean upgrades, metadata parity, non-destructive re-upgrade,
downgrade/re-upgrade, defaults, FK restrictions, CHECK failures, and partial uniqueness pass
against PostgreSQL. No SQLite substitution is used.

## Development migration and live HTTP verification

The initial migration was generated on a temporary PostgreSQL database, then reviewed and
cleaned up before use. The development database was inspected before its additive upgrade:
no public tables existed. Upgrade committed five new tables plus alembic_version. Existing
cluster identifier `7700589106042421282` was preserved; no development volume was deleted.
Downgrade was never executed on development data.

A cookie-aware HTTP smoke run through the running Vite `/api` proxy used one unique temporary
attendee and a random in-memory password. No credentials were printed. Actual results:

| Check | HTTP result |
| --- | --- |
| Direct liveness/readiness, frontend, proxied readiness | 200 |
| Current user before login | 401 |
| CSRF bootstrap | 200 |
| Registration with untrusted Origin | 403 |
| Valid registration | 201 |
| Current user after registration (no automatic login) | 401 |
| Login and authenticated current user | 200 |
| Logout with pre-rotation CSRF | 403 |
| Valid logout | 204 |
| Replay revoked cookie | 401 |
| Unimplemented event/reservation routes | 404 |

The smoke account and only its sessions were removed afterward. Before/after counts matched:
users=0, sessions=0, events=0, reservations=0, idempotency_records=0. No pre-existing data changed.
This was a cookie-aware HTTP proxy test, not a claim that an authentication UI was built or
that a browser end-to-end test framework was added.

Final direct checks of `/api/v1/health/ready`, `/docs`, `/openapi.json`, and the frontend all
returned 200. Runtime OpenAPI reports version 0.2.0 and seven implemented paths. Backend,
PostgreSQL, Redis, and test PostgreSQL are running/healthy; the frontend is running and
HTTP-verified (it has no configured Docker health probe).

## Review, limitations, and next gate

- Changes remain unstaged/uncommitted on main for user review; no commit or push was authorized.
- No Phase 3/4 endpoints, holds, expiration worker, reservation idempotency service, Redis
  rate limiter/cache, OAuth, payment processing, or cloud infrastructure were added.
- Session cleanup is an explicit bounded CLI command; automatic scheduling and anonymous
  bootstrap/login rate limiting remain deferred. The current authentication surface is for
  local development; public deployment hardening includes those later controls.
- Email verification, password recovery, MFA, SMTPUTF8 local parts, and authentication screens
  remain out of scope. Duplicate registration's 409 can disclose account availability.
- Readiness checks PostgreSQL connectivity, not migration currency; apply/check migrations
  explicitly. Administrator SQL must maintain updated_at; no timestamp triggers exist.
- Swagger on port 8000 documents routes; browser mutations must satisfy the configured frontend
  origin policy. There is no bypass for Swagger or a purported non-browser client.
- A host-port migration-generation attempt stalled and was stopped. Migration generation and
  all decisive PostgreSQL checks completed over Docker's internal network instead. Its one
  leftover generated database was inspected (empty public schema, default namespaces,
  csrs_test owner, zero active connections) and explicitly removed. Final generated-test-
  database count is zero; no development database or volume was removed.
- Hosted Phase 2 CI awaits an approved commit/push. Its local equivalents passed; no hosted
  result is claimed for the uncommitted work.

No known Phase 2 implementation blocker remains. Stop here for review before committing or
starting Phase 3.

## File manifest for review

22 added files:

```text
backend/migrations/versions/0001_foundation_foundation_schema_and_sessions.py
backend/src/csrs/api/auth.py
backend/src/csrs/api/openapi.py
backend/src/csrs/auth/__init__.py
backend/src/csrs/auth/admin.py
backend/src/csrs/auth/crypto.py
backend/src/csrs/auth/dependencies.py
backend/src/csrs/auth/errors.py
backend/src/csrs/auth/http.py
backend/src/csrs/auth/schemas.py
backend/src/csrs/auth/service.py
backend/src/csrs/cli.py
backend/src/csrs/models.py
backend/tests/integration/conftest.py
backend/tests/integration/test_auth.py
backend/tests/integration/test_auth_edges.py
backend/tests/integration/test_authorization.py
backend/tests/integration/test_migrations.py
backend/tests/integration/test_schema.py
backend/tests/unit/test_auth_crypto.py
docs/contracts/api.openapi.yaml
docs/phase-2-validation.md
```

22 modified files:

```text
.env.example
.github/workflows/ci.yml
README.md
backend/migrations/env.py
backend/pyproject.toml
backend/requirements-dev.lock
backend/scripts/export_health_contract.py
backend/src/csrs/config.py
backend/src/csrs/database.py
backend/src/csrs/main.py
backend/tests/integration/test_postgres_health.py
backend/tests/unit/test_config.py
backend/tests/unit/test_contracts.py
backend/tests/unit/test_health.py
docs/architecture.md
docs/contracts/api.md
docs/contracts/health.openapi.yaml
docs/database.md
docs/decisions.md
docs/security.md
frontend/src/App.tsx
infra/README.md
```
