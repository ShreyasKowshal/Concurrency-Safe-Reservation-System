# Phase validation reports

These reports preserve the verification evidence recorded during Phases 1–8:
commands, test results, acceptance criteria, audits, limitations, and file manifests.
Some retain prepublication or awaiting-review wording from their original checkpoint.
See the [project handoff](../PROJECT_HANDOFF.md) for later publication and CI provenance.

| Phase | Phase name | Scope | Validation report |
| --- | --- | --- | --- |
| 1 | Project foundation | Monorepo, configuration, health API/UI, Docker Compose, and CI. | [Phase 1](phase-1-validation.md) |
| 2 | Database schema and secure authentication | Five-table schema, migrations, sessions, CSRF, roles, and local administration. | [Phase 2](phase-2-validation.md) |
| 3 | Organizer event management | Public discovery and owner-scoped draft, edit, capacity, publish, and close operations. | [Phase 3](phase-3-validation.md) |
| 4 | Concurrency-safe reservations | Atomic holds, confirmation/cancellation, request-time expiry, durable idempotency, and concurrency evidence. | [Phase 4](phase-4-validation.md) |
| 5 | Expiration worker and recovery | Independent bounded expiration, process coordination, restart, and recovery. | [Phase 5](phase-5-validation.md) |
| 6 | Redis support | Shared quotas, public-event metadata caching, SQL authority, and outage behavior. | [Phase 6](phase-6-validation.md) |
| 7 | Complete React frontend | Attendee/organizer workflows, owner booking dashboard, retries, responsive layouts, and accessibility checks. | [Phase 7](phase-7-validation.md) |
| 8 | Local production readiness, final validation and portfolio evidence | Safe startup/migration gates, persistence/recovery verification, demo guides, and local portfolio evidence. | [Phase 8](phase-8-validation.md) |

Reports were moved here with their complete historical evidence retained; relative links
and repository-path references were adjusted for the new directory. The
[phase explanations](../phase-explanations/) provide beginner-friendly companion guides.
CSRS runs locally; these records do not establish a public cloud deployment or production
traffic performance. Return to the [main README](../../README.md).
