# Planned relational database

**Design only in Phase 1.** There are no ORM domain models or schema revisions yet.
Alembic has a configured runner and an empty versions directory. Do not use `create_all`.

Use UUID primary keys, `timestamptz` for instants, UTC API timestamps, explicit foreign keys,
and NOT NULL for required data. Normalize email with one documented case-insensitive policy;
do not apply provider-specific transformations such as removing dots.

| Table | Main columns | Constraints |
| --- | --- | --- |
| users | id, normalized_email, password_hash, role, is_active, created_at | Unique normalized email; role ATTENDEE or ORGANIZER |
| sessions | id, user_id, kind, token_hash, csrf_token, created_at, expires_at, revoked_at | Unique token hash; expiry after creation; ANONYMOUS has null user, AUTHENTICATED requires user |
| events | id, organizer_id, title, description, location, starts_at, ends_at, booking_closes_at, status, capacity, allocated_seats, created_at, updated_at | Capacity >= 1; 0 <= allocated_seats <= capacity; booking_closes_at <= starts_at < ends_at; status DRAFT/PUBLISHED/CLOSED |
| reservations | id, event_id, user_id, status, hold_expires_at, confirmed_at, cancelled_at, expired_at, created_at, updated_at | Status HELD/CONFIRMED/CANCELLED/EXPIRED; required state timestamps; valid foreign keys |
| idempotency_records | id, user_id, key, request_fingerprint, response_status, response_body, created_at, completed_at | Unique (user_id, key); completed response fields present together |

The anonymous session variant refines the approved schema to cover login/registration CSRF.
It adds no separate service or table. Session secrets are high-entropy opaque random values;
only hashes of cookie authentication secrets are stored. `csrf_token` is an independent random
synchronizer value, stored server-side so a page reload can fetch the same token. A CSRF token
alone cannot authenticate a user. Both values are redacted from logs. See [security](security.md).

## Reservation constraints

- Each row represents exactly one seat; no quantity field in the MVP.
- Every row originates as HELD with a non-null deadline after creation.
- Event/user IDs are immutable. Terminal rows remain for history.
- CONFIRMED requires `confirmed_at`; CANCELLED requires `cancelled_at`; EXPIRED requires `expired_at`.
- Cancelled confirmed rows retain `confirmed_at`. Expired rows cannot have been confirmed.
- A partial unique index on `(user_id, event_id)` where status is HELD or CONFIRMED prevents
  multiple active reservations, including attempts with different idempotency keys.
- Do not put `now()` in the partial-index predicate. An overdue stored HELD row is expired
  under the event lock before that user is allowed to create a replacement.
- Restrict hard deletion of referenced users/events; preserve reservation and idempotency history.

Timestamp consistency needs CHECK constraints, while transition legality and immutability are
initially enforced by the centralized service. Exact DDL is a Phase 2 review deliverable.

## Counter invariant

For each event, at every committed state:

`allocated_seats = count(persisted HELD) + count(CONFIRMED)`

`0 <= allocated_seats <= capacity`

Persisted HELD includes overdue holds waiting for cleanup. This is conservative allocation.
Effective occupancy excludes overdue holds, but the stored counter changes only in a transaction
that also changes reservation rows. A normal PostgreSQL CHECK cannot enforce the cross-table
equality. It is preserved by the locking protocol and independently checked in tests.

No claim is made that arbitrary administrator writes or future code bypassing the protocol
remain safe. All API and worker writes must use the same service. Stored procedures/triggers
are optional later hardening, not Phase 1 scaffolding.

## Index plan

- Unique normalized email and session token hash.
- Session expiry for maintenance.
- Published events by start time; events by organizer.
- Reservations by `(user_id, created_at, id)` for stable paginated history.
- Reservations by `(event_id, status)` for event views and reconciliation.
- Partial held-reservation index on `(hold_expires_at, event_id)` for sweep discovery.
- Partial unique active-reservation index described above.
- Unique idempotency `(user_id, key)`.

Retain idempotency records for the MVP. A retention/key-reuse contract is a separate future
decision. Claim insertion and completed response occur in the same transaction; incomplete
claims are not independently committed.

Reference: [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html).
