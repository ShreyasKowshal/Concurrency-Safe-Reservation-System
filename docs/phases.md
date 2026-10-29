# Delivery phases and evidence

| Phase | Deliverables | Acceptance gate |
| --- | --- | --- |
| 1 | Contracts, monorepo, configuration, health API/UI, Compose, Pytest, CI | Fresh setup works; config fails early; liveness independent of DB; readiness uses PostgreSQL; no secrets |
| 2 | Schema revisions, sessions, CSRF, registration/login/logout, roles | Empty-database migrations pass; invalid CSRF rejected including anonymous forms; revocation/ownership tested |
| 3 | Organizer event management | Ownership enforced; publication and schedule rules tested; capacity edits use event lock |
| 4 | Holds, confirm/cancel, request-time expiry, idempotency | Final-seat and duplicate-command races pass; invariant holds; response-loss retry tested |
| 5 | Sweeper and failure recovery | Worker restart drains backlog; no expired confirmation or double release; timeouts handled |
| 6 | Redis rate limits and metadata cache | Atomic quota checks; multi-process limits; outage policy tested; capacity independent of cache |
| 7 | Booking and organizer UI | Browser flows, current-state refresh, retry-key behavior, and accessible errors |
| 8 | Local production readiness, final validation, portfolio evidence | Reproducible localhost startup, persistence/recovery, concurrency/worker/Redis evidence, safe demo and interview guides; cloud/backup infrastructure deferred |

The owner explicitly revised Phase 8 to localhost-only on 2026-10-28. Public cloud deployment,
paid services and managed backup/restore infrastructure are not part of its acceptance gate.
See [Phase 8 validation](validations/phase-8-validation.md) and [future deployment](FUTURE_DEPLOYMENT.md).
The historical handoff is preserved until external review and approved hosted CI finalization.

Stop for review at each phase. Phase 1 must not create users/events/reservations or provision
paid infrastructure. Review evidence and exceptions in [phase-1-validation](validations/phase-1-validation.md).

## Later correctness evidence

Use independent connections and real commits. Coordinate race tests with barriers/explicit
transaction control, not arbitrary sleeps. Verify both operation orderings around each state
transition and equality at expiration. Exercise multiple API processes.

Check capacity bounds, counter equality to persisted HELD + CONFIRMED, and active-user
uniqueness from a consistent database snapshot. Mixed-load tests must record the environment,
commit, pool size, process count, random seed, workload, failures, and reproduction commands.
Test rate limiting separately so throttling cannot hide booking races.

Inject faults between reservation/counter/idempotency writes, before commit, after commit
before response, during lock waits, and during sweeps. Redis/worker outages must follow the
documented degraded behavior. No throughput, latency, or correctness metric is an achieved
result until the reproducible test has actually run.
