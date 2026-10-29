# Future cloud deployment: planning only

CSRS currently runs on localhost using Docker Compose. The owner deferred cloud hosting;
Phase 8 covers the local demonstration and verification. No cloud provider account, service,
domain, subscription, deployment manifest, public database or other cloud resource has been
created. Cloud deployment has not been validated. This local-first Phase 8 decision supersedes
the older cloud requirements.
[PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) records phase history and publication/CI provenance.

## Portable components already implemented

- FastAPI's modular backend and independent `python -m csrs.worker` process.
- PostgreSQL transactions, event-row locks, constraints, durable idempotency and deadlines.
- Alembic migrations and a serialized migration entry point (`python -m csrs.migrate`).
- Redis connection settings, bounded failure handling, cache TTL/namespace and shared quotas.
- Explicit database/Redis URLs, public trusted origin, SQL pool/timeouts, sessions and worker
  poll/batch/backoff configuration.
- A relative same-origin browser API path. The default is `/api/v1`; secrets never enter
  `VITE_*` variables. Current browser code intentionally rejects cross-origin API bases.
- HTTPS origin validation for production; scheme-derived Secure `__Host-csrs_session` cookies,
  HttpOnly, SameSite=Lax, Path=/ and no Domain attribute.
- Rejection of the repository's known public example database passwords in production settings.
  This guard is not a general assessment of password strength or infrastructure security.

Using a hosted PostgreSQL connection does not require redesigning the reservation protocol.
Its configuration is portable, but the provider's networking and TLS behavior still need verification.

## Infrastructure that does not exist yet

| Component | Work required before public hosting |
| --- | --- |
| Frontend | Build static files using the pinned Node/npm lock; serve them through a reviewed static/reverse-proxy tier, or explicitly implement backend static serving |
| Same-origin routing | Route `/api/v1` to FastAPI and browser deep links to the React entry without shadowing API 404s; Vite is not the public server |
| API service | Use an appropriate runtime image/process, no reload, least privilege, resource sizing, graceful shutdown and a documented rollback |
| PostgreSQL | Private managed service or durable storage, non-example credentials, least-privilege runtime/migration roles, verified TLS, backups/retention and an observed restore |
| Redis | Private managed Redis-compatible service with reviewed client/TLS support, bounded memory, shared quotas, namespace isolation and failure policy |
| Worker | Independently supervised persistent process with the same PostgreSQL/schema; progress/backlog monitoring and restart policy, no public port |
| Migration runner | One controlled pre-traffic invocation using the same database advisory lock; verify head/current/drift and review lock/statement budgets |
| HTTPS/edge | Certificate and HTTPS termination, safe redirects, security headers, request limits and explicit proxy trust |
| Secrets | Provider secret injection, rotation and restricted access; no values in Git, image layers, frontend artifacts, logs or screenshots |
| Operations | Logs without PII/tokens, alerts, ownership, backup/restore, rollback, incident response, retention decisions and cost controls |

The current backend image includes development/test tools. A public runtime image still needs
hardening and container dependency scanning. Floating base image tags need a reviewed
update/digest policy. Current readiness probes SQL connectivity, not schema currency, Redis,
backups or worker progress. Each needs an independent operational check.

## Security and configuration to verify later

Set `CSRS_ENVIRONMENT=production` and an exact HTTPS `CSRS_PUBLIC_ORIGIN`. Supply PostgreSQL
and Redis URLs through the host's secret manager, including provider-required TLS options.
Database TLS can be configured in the SQLAlchemy URL; Redis TLS uses `rediss://` and retains
hostname verification. Redis query parameters are rejected by the settings model. A provider
requiring unsupported trust/auth options needs an explicit reviewed implementation and tests.

Use the same HTTPS origin for browser/API if possible. This preserves the current cookie and
CSRF design. There is no CORS middleware today. Separate-origin hosting requires deliberate
credentialed CORS/cookie/CSRF design and browser tests, not a wildcard header. Secure cookies
must survive proxying correctly. Verify no Domain, correct Path, __Host prefix, logout deletion
and token rotation with the real hosted browser.

Proxy headers are disabled today. Peer quotas currently see the Vite/proxy connection address,
so multiple local clients share a quota. Determine trusted proxy addresses/hops and real peer
identity with tests against spoofed forwarded headers before changing Uvicorn trust. Do not
silently enable arbitrary proxy trust. An application quota is not a full DDoS defense.

Size all API/worker database pools against managed connection limits. Review SQL statement,
pool and Redis connection/socket timeouts, stop grace periods, worker batch/poll/backoff,
cache TTL/namespace, quota windows and session/hold TTLs. An ordinary transactional index
migration may block writes; this repository has not established online schema migration or
zero-downtime deployment. Do not blindly downgrade production data for application rollback.

## Provider evaluation at the time of deployment

Render or a similar platform may be evaluated later. Prices, free-tier terms, sleep policies
and plan availability have not been verified here. Recheck official provider
documentation and pricing when the owner chooses to host. Record the check date and plan.

Verify persistent PostgreSQL storage, backups/restore access, Redis version/TLS/eviction,
worker process support, outbound/private networking, connection limits, region, CPU/memory,
build/start/release commands, health checks, graceful termination, logging retention, ingress
limits, database inactivity/expiry policies, cost ceilings and billing alerts. Do not assume
a sleeping web process can host the independently running worker or durable database.

## Deployment acceptance steps for a later assignment

1. Select/approve topology, costs and secret handling; implement and review runtime/proxy
   packaging. No resources should be created from this planning document alone.
2. Provision private PostgreSQL/Redis and an independent worker; establish backups and prove
   restore using isolated safe data.
3. Run serialized migrations once before traffic, verify revision/metadata and record the
   application artifact/commit plus schema revision.
4. Verify HTTPS, deep links, same-origin API, cookie attributes, exact CSRF trust, ownership,
   proxy identity and secrets hygiene in the actual hosted environment.
5. Run attendee/organizer flows, scoped final-seat contention, replay/lost response, worker
   backlog and read-only SQL reconciliation. Keep correctness and performance claims separate.
6. Exercise controlled dependency outages/restarts, worker interruption, Redis policies and
   compatible rollback in staging. Never stop a shared production dependency just for a demo.
7. Capture sanitized evidence and hosted CI results for the exact published artifact. Verify
   logs, alerts, costs and operating instructions before claiming public production readiness.

Local results in [Phase 8 validation](validations/phase-8-validation.md) do not establish any of these
cloud-specific results. The current project is deliberately a locally demonstrated system.
