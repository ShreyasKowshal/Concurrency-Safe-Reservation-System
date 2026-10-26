# Reservation protocol and state machine

**Implemented through Phase 4:** event-row locking, reservation commands, durable idempotency,
and request-time expiration. Capacity edits and reservation commands share due-hold cleanup
under the event lock. The standalone worker is implemented in Phase 5 and awaits review;
see [its validation](phase-5-validation.md).

## Product rules

One seat per reservation and one active reservation per user/event. Attendees may rebook
after cancellation/expiration. Hold TTL defaults to five minutes; `CSRS_HOLD_TTL_SECONDS` accepts
1-3600 seconds.
Deadline = earlier of decision time + TTL and event booking deadline. Never create a hold
with no remaining validity. Booking deadline must be no later than event start.

Event transitions: DRAFT -> PUBLISHED -> CLOSED. Draft metadata is editable; after publication,
start time and booking deadline remain immutable in the MVP. Closing stops new holds but
valid existing holds can still confirm. Confirmation after the booking deadline is impossible
because hold deadlines are capped by it. Confirmed cancellation is allowed before event start.
No event-wide cancellation, reopening, seat assignment, quantities, or payment state.

## Lock and transaction boundary

Use READ COMMITTED and an explicit `SELECT ... FOR UPDATE` of the event row. Every hold,
confirmation, cancellation, expiration, capacity edit, and publish/close operation participates.
Read allocated capacity only after obtaining this lock. Each event has its own serialization
point; a Python mutex or Redis lock is neither necessary nor sufficient across processes.

Lock order: idempotency claim (user command only), event row, reservation rows.
For a reservation-addressed command, discover its immutable event ID without a reservation
lock, then lock the event and reread the reservation and ownership. Never lock a reservation
first. Background jobs discover candidate event IDs without holding reservation locks.

1. Authenticate, validate JSON/CSRF/ownership context, and rate-limit outside the transaction.
2. Begin transaction and claim the user's idempotency key if required.
3. Lock the event and revalidate authorization and current state.
4. Sample PostgreSQL actual current time after acquiring the lock.
5. Transition due HELD rows to EXPIRED; decrement by the number actually changed.
6. Apply the requested transition and matching counter change, or determine a business error.
7. Persist the response in the idempotency record and commit.
8. Send success only after commit has succeeded.

No remote I/O, Redis calls, slow hashing, or nested independent commits while holding the lock.
Transactions cover one event. Future multi-event work requires a separately reviewed ordering.

## State transitions

| Starting state | Action/condition | End state | Allocated change | Result |
| --- | --- | --- | --- | --- |
| none | Create hold, admission allowed | HELD | +1 | 201 |
| HELD | Confirm before deadline | CONFIRMED | 0 | 200 |
| HELD | Confirm at/after deadline | EXPIRED | -1 | 409 HOLD_EXPIRED |
| HELD | Cancel before deadline | CANCELLED | -1 | 200 |
| HELD | Cancel at/after deadline or sweep | EXPIRED | -1 | 200 for cancellation |
| CONFIRMED | Confirm again | CONFIRMED | 0 | 200 |
| CONFIRMED | Cancel before event start | CANCELLED | -1 | 200 |
| CONFIRMED | Cancel at/after event start | CONFIRMED | 0 | 409 CANCELLATION_CLOSED |
| CANCELLED | Cancel again | CANCELLED | 0 | 200 |
| EXPIRED | Cancel | EXPIRED | 0 | 200 |
| CANCELLED/EXPIRED | Confirm | unchanged | 0 | 409 INVALID_RESERVATION_STATE or HOLD_EXPIRED |

Terminal reservations never reactivate. Rebooking uses a new row and a new idempotency key.
Repeated confirmation of a currently CONFIRMED reservation is a no-op even after its original
hold deadline; confirmed reservations do not expire.

## Time and expiration

Validity is `decision_time < hold_expires_at`; equality means expired. Sample `clock_timestamp()`
after the event lock, rather than transaction-start `now()`, which may predate a lock wait.
All steps use that decision instant. A confirmation accepted just before expiry may commit
afterward; a request that arrived earlier but acquires the lock after expiry fails. Keep
transactions short. Application/browser clocks never determine booking eligibility.

Request-time cleanup reclaims an event's due holds before admission. The standalone
worker polls every 15 seconds while idle by default and discovers bounded candidate pages.
It locks and rechecks one event per transaction using event-row FOR UPDATE SKIP LOCKED.
Busy events are deferred.
A fixed-cutoff keyset pass advances past busy groups and wraps; cleanup is bounded per event
with the same shared transition. The worker position is navigation, never durable work state.
It decrements only for rows actually transitioned.
Productive pages and productive cursor wraps use a delay capped at 0.25 seconds. Full busy or
stale pages scan ahead after at most one second; idle passes retain the configured poll delay.
Repeated sweeps and multiple discoverers do not double-release. Begin operationally with one worker.

Worker outages may delay persisted cleanup; they cannot authorize expired confirmations.
Requests can reclaim capacity without waiting for the worker. Reads project overdue HELD as
effective EXPIRED without mutating rows. Admission still uses the locked transaction.

Business failures can coexist with useful cleanup. For example, confirming an expired hold
must commit expiration and the stored 409 response; do not raise a rollback-triggering HTTP
exception before this transaction commits.

## Capacity edits and correctness argument

Capacity updates take the event lock, clean due holds, and reject capacity below allocated
seats. Admission adds one held row and one counter unit only below capacity. Confirmation
preserves the sum. Cancellation/expiration remove one counted row and decrement once.
Atomic commits plus per-event serialization preserve the invariant from its zero-allocation
initial state. CHECK constraints bound the stored counter. Independent tests check the
cross-table equality. Redis data never appears in this argument.

## Idempotency

Require a user-scoped key on hold/confirm/cancel. Fingerprint method, canonical path, and
validated body. A PostgreSQL unique constraint arbitrates competing insert claims; the
winner records the final response in the same transaction as the business mutation.
Concurrent duplicates wait and replay after commit. A rolled-back claim can be retried.
Fingerprint mismatch returns 409. Stored business errors replay too; new intent needs a new key.

Replay returns the original status/body, with `Idempotency-Replayed: true`; clients fetch
current resource state afterward. Authentication, CSRF, ownership, and throttling still apply
before a replay. Replay must not re-execute a formerly successful transition.

Connection loss during commit has an uncertain outcome. Retry with the same key. Never
create a fresh key automatically for an uncertain mutation. Transient database errors and
429s are not completed reservation outcomes. Apply bounded retries only to known safe
transaction-abort cases; lock timeout returns retryable 503 after rollback.

## Required race/failure coverage

Final-seat contention; same user with different keys; duplicate key with same/different
payload; confirm/expire; cancel/expire; confirm/cancel; capacity edit/admission; stale sweep
candidate; duplicate sweeps; crash between row and counter writes; response loss after
commit; unknown commit outcome; Redis outage; worker restart; lock timeout; cross-user access.

References: [PostgreSQL locks](https://www.postgresql.org/docs/current/explicit-locking.html),
[isolation](https://www.postgresql.org/docs/current/transaction-iso.html),
[database time](https://www.postgresql.org/docs/current/functions-datetime.html).
