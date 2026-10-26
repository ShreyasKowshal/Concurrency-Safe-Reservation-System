# Relational database foundation

**Implemented in Phase 2:** five SQLAlchemy models and Alembic revision `0001_foundation`.
Use `alembic upgrade head`; no runtime `create_all`, automatic startup migration, or database
extension is needed. PostgreSQL's built-in `gen_random_uuid()` supplies server-side IDs.

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
- CONFIRMED requires `confirmed_at`; CANCELLED requires `cancelled_at`; EXPIRED requires
`expired_at`.
- Cancelled confirmed rows retain `confirmed_at`. Expired rows cannot have been confirmed.
- A partial unique index on `(user_id, event_id)` where status is HELD or CONFIRMED prevents
  multiple active reservations, including attempts with different idempotency keys.
- Do not put `now()` in the partial-index predicate. An overdue stored HELD row is expired
  under the event lock before that user is allowed to create a replacement.
- Restrict hard deletion of referenced users/events; preserve reservation and idempotency history.

Timestamp consistency needs CHECK constraints, while transition legality and immutability are
enforced by the centralized Phase 4 reservation service. The migration contains explicit,
named CHECKs for state/timestamp combinations, strict confirmation-before-deadline and
expiration-at-or-after-deadline boundaries. It does not implement reservation transitions.

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
are optional later hardening, not part of Phase 2.

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

## Implemented schema details and migrations

String states with named CHECKs are used instead of PostgreSQL enum types, simplifying future
state migrations. All foreign keys use RESTRICT. Session cookie digests and CSRF tokens are
64 lowercase hexadecimal characters. Idempotency keys contain 1-128 visible ASCII characters;
fingerprints are 64 lowercase hexadecimal characters. A pending idempotency row has all
response fields NULL; a completed row requires a 200-499 status, object JSONB body, and
completion timestamp. SQL NULL checks are explicit, so three-valued CHECK logic cannot admit
a partially completed response. The Phase 4 command service prevents committing a pending claim
separately: claim,
mutation/counter, and completed response share one transaction.

Created timestamps default to PostgreSQL transaction time. User/event/reservation updated_at
defaults on insert and is updated by SQLAlchemy updates; no timestamp triggers are installed.
Administrative SQL must explicitly maintain updated_at. Organizer-role eligibility and
immutable reservation owner/event IDs are service rules, not cross-table CHECKs.

The initial upgrade only creates tables/indexes. Reapplying head is a no-op and is tested to
preserve existing rows. Downgrade removes these tables and is tested only on generated
disposable databases, never on the development database. Alembic metadata drift checks,
constraint failures, defaults, partial uniqueness, and FK deletion restrictions are covered
by real PostgreSQL tests. Test databases are generated with `csrs_phase2_<uuid>_test` names
on the dedicated test server and removed after the run; the configured input database is
not truncated or dropped.

Reference: [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html).

## Phase 5 bounded worker index

Revision `0002_worker_expiry` adds only
`ix_reservations_event_held_expiry (event_id,hold_expires_at,id) WHERE status='HELD'`.
The existing `(hold_expires_at,event_id)` partial index serves bounded global discovery.
The new index serves ordered, limited cleanup for one locked event, avoiding sorting all of a
large event's active rows or walking unrelated events' due entries. No columns, tables, data,
or constraints change. Upgrade/downgrade and metadata drift are tested on disposable databases.
Migration is an explicit administrator step before starting the worker. Its CREATE INDEX is
transactional, with ordinary PostgreSQL index-build locking; it is not an online deployment.
