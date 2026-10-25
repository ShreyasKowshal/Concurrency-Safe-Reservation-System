# Architecture decisions

| ID | Decision | Reason and cost |
| --- | --- | --- |
| ADR-001 | One modular backend, not microservices | One transaction boundary and manageable operations; modules can still have clear responsibilities |
| ADR-002 | PostgreSQL is authoritative | Durable transactions and constraints; Redis loss cannot grant capacity |
| ADR-003 | READ COMMITTED plus event row lock | Easy-to-explain ordering across API processes; one hot event is deliberately serialized |
| ADR-004 | Stored allocated-seat counter | Constant-size admission check and bounded CHECK constraint; must reconcile with reservation rows |
| ADR-005 | One seat, one active booking per user/event | Avoid quantities, seat maps, and partial cancellation while retaining meaningful races |
| ADR-006 | Request-time expiration plus sweeper | Worker lag cannot authorize stale holds; stored cleanup may lag the effective state |
| ADR-007 | Durable idempotency in the business transaction | Recovers from retries and lost responses; records retained in MVP |
| ADR-008 | Opaque database-backed sessions | Immediate logout/revocation; extra database lookup compared with self-contained tokens |
| ADR-009 | Anonymous pre-session + synchronizer CSRF token | Protects login/registration as well as authenticated operations; requires short-lived anonymous session cleanup |
| ADR-010 | Same-origin browser API | Simpler cookies and explicit origin validation; Vite proxy locally, same-origin serving later |
| ADR-011 | Synchronous SQLAlchemy and FastAPI handlers | Fewer moving parts while learning transactions; async can be evaluated if measured needs justify it |
| ADR-012 | Standalone polling worker, no Celery initially | No broker/task delivery problem for one database sweep; revisit for independent notification jobs |
| ADR-013 | Real PostgreSQL integration tests | SQLite cannot stand in for PostgreSQL locking; requires Docker or a dedicated server |
| ADR-014 | No domain implementation in Phase 1 | Establish reviewable contracts before schema/auth/reservation work |
| ADR-015 | Five-table foundation in Phase 2, no booking commands | Establish constraints and auth without prematurely implementing event/hold services |
| ADR-016 | String states with named CHECKs | Avoid PostgreSQL enum lifecycle complexity; retain explicit database validation |
| ADR-017 | ASCII canonical email and 15-128 character registration passwords | Deterministic unique emails and bounded Argon2 work; SMTPUTF8 local parts deferred |
| ADR-018 | Disposable database per integration run | Exercise real commits/migrations without truncating the configured or development database |
| ADR-019 | Owner-only event detail and scoped keyset pagination | Read drafts without changing public visibility or implementing a booking dashboard early; cursors never confer permission |
| ADR-020 | Drafts can become stale; publication requires future database time | Allow draft repair, then recheck under the event lock; published start/deadline stay immutable and closed events are read-only |
| ADR-021 | Phase 3 capacity uses stored allocation conservatively | Preserve bounds without implementing Phase 4 expiration; later shared cleanup must run under the same event lock |

Scope gates and acceptance criteria are in [phases](phases.md). Decisions are reviewed when
requirements change, not silently bypassed by a new endpoint or worker.
