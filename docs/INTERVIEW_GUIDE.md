# Explaining CSRS in an SDE interview

## A short introduction

"I built an event reservation system where multiple users can compete for limited seats.
React calls FastAPI; PostgreSQL owns reservations and capacity. Each command locks the event
row and commits its reservation, counter and retry outcome in one transaction. An independent
worker expires holds. Redis supports rate limiting and public metadata, so losing Redis
does not let the system oversell. I demonstrate it locally with Compose and real database tests."

Use [the demo guide](DEMO_GUIDE.md) to show it and
[validation](validations/phase-8-validation.md) for measured evidence. Do not describe it as cloud-deployed
or quote a production throughput number.

## System overview

The browser is the front desk; PostgreSQL is the ledger. FastAPI validates input, sessions,
roles, ownership and CSRF before asking a service to perform a transaction. SQLAlchemy manages
independent database sessions through Psycopg. These are separate from the security sessions
used for login. Alembic keeps the schema versioned. Redis stores disposable quotas and public
metadata. The worker is a separate Python process that finds overdue holds in PostgreSQL;
it needs no API request, Redis connection or task broker.

PostgreSQL stores users, security sessions, events, reservations and idempotency records.
That shared durable transaction boundary is why multiple API processes can agree after
restarts. A Python dictionary or per-process mutex would not coordinate those processes.

## Concurrency and overselling

Suppose capacity is 1 and both Alice and Bob read allocation 0. Without coordination, both
could insert a hold. A transaction alone does not stop that read/check/write race under
READ COMMITTED. CSRS runs `SELECT ... FOR UPDATE` on the event before checking its counter.
Alice obtains the row lock, allocates, and commits. Bob waits, then reads the committed
allocation 1 and receives EVENT_FULL. Different events have different row locks.

The protocol is **idempotency claim → event row → reservation rows**. For confirm/cancel,
the immutable event ID is discovered without first locking the reservation. Every booking,
capacity edit and worker cleanup follows event-first ordering. The code refreshes SQLAlchemy
objects and authorization after waits, so stale session or event state cannot decide admission.

READ COMMITTED gives each SQL statement a fresh committed snapshot. The lock establishes
the serial order for one event. PostgreSQL `clock_timestamp()` is sampled after acquiring
the lock: transaction-start `now()` could be earlier than a long wait and accept an expired hold.

Named database CHECKs enforce counter bounds, schedule/timestamp/state consistency and valid
values. A partial unique index permits at most one persisted HELD/CONFIRMED row per user/event.
These are additional defenses. Cross-table equality is maintained by the service protocol
and checked with SQL; an ordinary CHECK cannot count another table's rows. Arbitrary admin
writes can violate the protocol.

The intended invariant is:

```text
allocated_seats = count(persisted HELD + CONFIRMED)
0 <= allocated_seats <= capacity
```

A stored HELD row still counts toward allocation after its deadline, until cleanup commits.
A public availability query can treat it as expired, but that query is advisory: only a
reservation command can allocate a seat.

## Reservation lifecycle

| State/action | Meaning and allocation |
| --- | --- |
| HELD | One seat allocated temporarily; deadline is min(decision time + TTL, booking close) |
| HELD → CONFIRMED | Before the deadline, preserve the allocated seat; no second increment |
| HELD → EXPIRED | At/after deadline, release only the row actually transitioned |
| HELD → CANCELLED | Voluntary release before deadline; release once |
| CONFIRMED → CANCELLED | Allowed strictly before event start; release once |
| Terminal history | CANCELLED/EXPIRED never reactivate; rebooking needs a new row/key |

The default hold lasts at most five minutes. A hold is expired at its exact deadline.
Confirmation of an already confirmed row is a no-op even after its old deadline. Closing an
event prevents new holds without invalidating existing valid holds or cancelling confirmed reservations.
Reads do not mutate reservation state; an overdue row may display EXPIRED before stored cleanup.

## Durable idempotency and lost responses

Browsers double-click, connections time out, and servers can commit just before a response
is lost. CSRS requires a user-scoped Idempotency-Key on hold/confirm/cancel. A fingerprint
binds the key to method, canonical path and validated JSON body. A PostgreSQL uniqueness
constraint decides which request can claim the key, even across API processes.

The new claim, reservation state, counter changes and completed status/body commit together:
either all are stored or all roll back. If a matching request is still running, a duplicate
waits, then replays its committed outcome. A different fingerprint returns IDEMPOTENCY_KEY_REUSED.
Business conflicts are stored too: replaying EVENT_FULL after a seat becomes free still
returns that original conflict. A new intent requires a new key.

A response lost after commit is recovered with the **same key**. A disconnect during commit
has an uncertain outcome; it does not prove rollback. There is no blind server retry or new
key generation. Transient/security/validation/quota failures do not become completed outcomes.
Replay still checks current authentication, CSRF, ownership and quotas. Because an original
HELD response can later be stale, the browser fetches current private detail after replay.

The frontend keeps retry keys only in memory. After reload it checks private history before
asking for another hold. The partial unique index still prevents multiple active allocations
for the same user and event, even when the original in-memory key is lost.

## Independent worker and recovery

Request-time cleanup handles events receiving commands, but a quiet event still needs its
expired holds cleared. The worker reads bounded pages of overdue entries from an index,
without locking reservations. For each event it opens a transaction and attempts
`FOR UPDATE SKIP LOCKED`. If another transaction holds the event lock, the worker skips it
rather than waiting, processes other events, and returns to unfinished work on later passes.
Once it acquires the lock, it samples database time and calls the same conditional expiration
transition as the API.

Only rows changed from HELD to EXPIRED decrement allocation. Confirmed and already terminal
rows are preserved. Multiple workers can discover the same candidate but cannot release twice.
The worker's scan cursor is navigation, not durable ownership. A crash before commit rolls
back; a crash after commit leaves terminal rows. Restart discovers remaining stored work.

The default idle poll is 15 seconds, with bounded productive catch-up and failure backoff.
There is no expiration-latency SLA: backlog, lock contention and database outages add delay.
Request-time cleanup can still reclaim due capacity while the worker is stopped.

## Redis supporting roles

Redis uses atomic Lua operations to check and increment shared fixed-window quotas. Each
quota limits requests within its window; a TTL removes the key when the window ends.
Public event detail metadata is cached briefly (default 15 seconds),
with SQL publication visibility checked on every hit. Successful organizer edits invalidate
after commit. An older in-flight fill can be stale only until its original absolute expiry.
Lists, live availability, sessions, reservations and durable retry outcomes are not cached.

Fail-open means a request continues to PostgreSQL when its optional limiter is unavailable;
the reservation rules still decide whether a booking succeeds. Public reads and authenticated
commands use that policy. New anonymous sessions and login/register fail closed with controlled 503
when Redis cannot enforce their quotas. Actual quota exhaustion returns 429/Retry-After.
Existing valid CSRF retrieval and logout remain usable.

Redis is not the authoritative seat lock because separate cache/lock and SQL commits would
introduce another failure boundary. PostgreSQL already provides the lock and atomic ledger.
Restarting Redis loses quotas/cache but not reservations. Local proxy users share peer quotas;
public hosting needs a separately verified trusted-proxy identity design.

## Full-stack and operations

React uses a same-origin API client that includes cookies, JSON, trusted Origin and the
session-bound synchronizer CSRF token. The HttpOnly cookie contains an opaque random secret;
only its hash is stored in PostgreSQL. Passwords use Argon2id. Login rotates session secrets;
logout revokes the session. Public registration cannot choose organizer privileges.
Authentication establishes who is signed in; authorization checks what that user may do.
Role guards help navigation, while the server enforces role and resource ownership.

Session/booking secrets are not stored in localStorage or URLs. Logout/session loss/account
switches discard private state and ignore old responses. Runtime Zod validation checks API
JSON. Countdown uses server time plus elapsed monotonic browser time and remains approximate.

Compose runs frontend, API, PostgreSQL, Redis and worker. A one-shot migration service gates
API/worker startup under a database advisory lock and verifies metadata drift. PostgreSQL
uses a named persistent volume; ordinary down/up retains it. Redis data is disposable.
Liveness checks the API; readiness checks PostgreSQL connectivity. Worker progress is checked
separately through logs/committed transitions.

GitHub Actions runs unit, contract, real PostgreSQL/Redis, frontend and Compose/browser smoke
checks. Real independent-process races prove their stated correctness workloads. Vitest mocks
are appropriate for UI errors/timers but do not prove database locking. Browser tests exercise
actual backend outcomes, including dropping delivery of an already successful response.
The handoff records published commit hashes and verified hosted CI runs. Local and hosted CI
checks do not establish public-cloud operation or production performance.

## Tradeoffs and limitations

Writes to one popular event are serialized by its row lock. This makes the correctness
protocol easier to reason about, but contenders must wait. Optimize only after measuring
contention. Pool sizes must be budgeted across API/worker instances. Sharding events or an
inventory redesign would require a new reviewed protocol; adding Redis as inventory is not a
drop-in scale fix.

The project currently runs locally; cloud deployment is deferred by the owner. Future hosting
needs a built frontend/proxy, HTTPS, secure cookies, private managed services, secrets,
migration coordination, backup/restore, monitoring, trusted proxy review and observed cloud
recovery tests. No current provider pricing/free-tier claim is made.

Automated retention, account recovery/MFA, payments, notifications, waitlists and seat maps
are absent. Chromium/axe/keyboard checks are not full WCAG certification or physical-device
testing. Correctness races are not production throughput or latency measurements.

## Practice questions

| Question | Short answer |
| --- | --- |
| Why is a transaction alone insufficient? | Two READ COMMITTED transactions can both see a free seat before either writes; the event lock makes them take turns |
| Why lock the event instead of only a reservation? | Before admission there is no reservation row, and capacity is shared across users |
| Why sample time after the lock? | A wait may cross the deadline; transaction-start time can be stale |
| Can the browser promise a seat? | No; availability is a snapshot, and the next locked transaction decides |
| What if the response disappears? | Retry the same key and read current state after replay |
| Can different keys bypass uniqueness? | No; the service and partial unique index allow one active user/event row |
| What if the worker runs twice? | Conditional transitions under the event lock release each row at most once |
| What if Redis is down? | SQL still decides reservations; new-session/auth operations pause according to their fail-closed policy |
| Does down remove bookings? | Ordinary Compose down retains bookings in the named PostgreSQL volume; deleting that volume would remove its data |
| What is not proven by 100 contenders? | Production scalability, throughput, arbitrary partitions or all future lock orders |
| How do you know tests exercise contention? | Independent API/SQL sessions, barriers and observed PostgreSQL blocking, followed by SQL reconciliation |
