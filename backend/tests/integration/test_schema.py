from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from csrs.models import Event, IdempotencyRecord, Reservation, Role, SessionRecord, User

pytestmark = pytest.mark.integration


@pytest.fixture
def event(db, user_factory):
    organizer = user_factory("organizer@example.com", role=Role.ORGANIZER)
    now = datetime.now(UTC)
    with db.begin():
        value = Event(
            organizer_id=organizer.id,
            title="Workshop",
            location="Campus",
            capacity=10,
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
            booking_closes_at=now + timedelta(hours=23),
        )
        db.add(value)
        db.flush()
    return value


@pytest.mark.parametrize(
    "field,value,constraint",
    [
        ("role", "ADMIN", "ck_users_role"),
        ("normalized_email", "UPPER@example.com", "ck_users_normalized_email"),
        ("normalized_email", " ", "ck_users_normalized_email"),
        ("password_hash", "plaintext", "ck_users_password_hash"),
    ],
)
def test_user_constraints(db, password_hash, field, value, constraint):
    row = User(normalized_email="user@example.com", password_hash=password_hash)
    setattr(row, field, value)
    with pytest.raises(IntegrityError) as error, db.begin():
        db.add(row)
        db.flush()
    assert error.value.orig.diag.constraint_name == constraint


def test_normalized_email_uniqueness(db, user_factory, password_hash):
    user_factory()
    with pytest.raises(IntegrityError), db.begin():
        db.add(User(normalized_email="attendee@example.com", password_hash=password_hash))
        db.flush()


@pytest.mark.parametrize(
    "field,value,constraint",
    [
        ("capacity", 0, "ck_events_capacity"),
        ("allocated_seats", -1, "ck_events_allocation"),
        ("allocated_seats", 11, "ck_events_allocation"),
        ("status", "INVALID", "ck_events_status"),
        ("title", " ", "ck_events_title"),
        ("location", "", "ck_events_location"),
        ("organizer_id", uuid4(), "fk_events_organizer_id_users"),
    ],
)
def test_event_constraints(db, event, field, value, constraint):
    with pytest.raises(IntegrityError) as error, db.begin():
        setattr(event, field, value)
        db.flush()
    assert error.value.orig.diag.constraint_name == constraint


def test_event_schedule_constraint(db, event):
    with pytest.raises(IntegrityError) as error, db.begin():
        event.ends_at = event.starts_at
        db.flush()
    assert error.value.orig.diag.constraint_name == "ck_events_schedule"


@pytest.mark.parametrize(
    "kind,user_present,valid",
    [
        ("ANONYMOUS", False, True),
        ("AUTHENTICATED", True, True),
        ("ANONYMOUS", True, False),
        ("AUTHENTICATED", False, False),
        ("OTHER", False, False),
    ],
)
def test_session_kind_user_constraint(db, user_factory, kind, user_present, valid):
    user = user_factory()
    now = datetime.now(UTC)
    row = SessionRecord(
        kind=kind,
        user_id=user.id if user_present else None,
        token_hash="a" * 64,
        csrf_token="b" * 64,
        expires_at=now + timedelta(hours=1),
    )
    if valid:
        with db.begin():
            db.add(row)
    else:
        with pytest.raises(IntegrityError) as error, db.begin():
            db.add(row)
            db.flush()
        assert error.value.orig.diag.constraint_name == "ck_sessions_kind_user"


@pytest.mark.parametrize(
    "field,value,constraint",
    [
        ("token_hash", "raw-cookie", "ck_sessions_token_hash"),
        ("csrf_token", "bad", "ck_sessions_csrf_token"),
        ("expires_at", datetime(2000, 1, 1, tzinfo=UTC), "ck_sessions_expiry"),
        ("revoked_at", datetime(2000, 1, 1, tzinfo=UTC), "ck_sessions_revocation"),
    ],
)
def test_session_secret_and_time_constraints(db, field, value, constraint):
    row = SessionRecord(
        kind="ANONYMOUS",
        token_hash="a" * 64,
        csrf_token="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    setattr(row, field, value)
    with pytest.raises(IntegrityError) as error, db.begin():
        db.add(row)
        db.flush()
    assert error.value.orig.diag.constraint_name == constraint


def reservation(event, user, **overrides):
    now = datetime.now(UTC)
    fields = dict(
        event_id=event.id,
        user_id=user.id,
        created_at=now,
        hold_expires_at=now + timedelta(minutes=5),
    )
    fields.update(overrides)
    return Reservation(**fields)


@pytest.mark.parametrize(
    "status,timestamp",
    [
        ("CONFIRMED", None),
        ("CANCELLED", None),
        ("EXPIRED", None),
        ("UNKNOWN", None),
        ("HELD", "confirmed_at"),
        ("HELD", "cancelled_at"),
        ("HELD", "expired_at"),
    ],
)
def test_reservation_state_constraints(db, event, user_factory, status, timestamp):
    user = user_factory()
    row = reservation(event, user, status=status)
    if timestamp:
        setattr(row, timestamp, row.created_at + timedelta(minutes=1))
    with pytest.raises(IntegrityError), db.begin():
        db.add(row)
        db.flush()


@pytest.mark.parametrize("terminal", ["CANCELLED", "EXPIRED"])
def test_terminal_history_does_not_block_new_active_reservation(db, event, user_factory, terminal):
    user = user_factory()
    first = reservation(event, user, status=terminal)
    if terminal == "CANCELLED":
        first.cancelled_at = first.created_at + timedelta(seconds=1)
    else:
        first.expired_at = first.hold_expires_at
    with db.begin():
        db.add_all([first, reservation(event, user)])


def test_active_partial_uniqueness_across_held_and_confirmed(db, event, user_factory):
    user = user_factory()
    row = reservation(event, user, status="CONFIRMED")
    row.confirmed_at = row.created_at + timedelta(seconds=1)
    with db.begin():
        db.add(row)
    with pytest.raises(IntegrityError) as error, db.begin():
        db.add(reservation(event, user))
        db.flush()
    assert error.value.orig.diag.constraint_name == "uq_reservations_active_user_event"


@pytest.mark.parametrize("state", ["CONFIRMED", "EXPIRED"])
def test_confirm_at_deadline_and_early_expiration_are_invalid(db, event, user_factory, state):
    user = user_factory()
    row = reservation(event, user, status=state)
    if state == "CONFIRMED":
        row.confirmed_at = row.hold_expires_at
    else:
        row.expired_at = row.hold_expires_at - timedelta(seconds=1)
    with pytest.raises(IntegrityError), db.begin():
        db.add(row)
        db.flush()


@pytest.mark.parametrize(
    "values",
    [
        {"key": "with space"},
        {"request_fingerprint": "bad"},
        {"response_status": 200},
        {"response_body": {}},
        {"response_status": 200, "response_body": {}, "completed_at": None},
        {"response_status": None, "response_body": {}, "completed_at": datetime.now(UTC)},
        {"response_status": 503, "response_body": {}, "completed_at": datetime.now(UTC)},
    ],
)
def test_idempotency_claim_and_response_constraints(db, user_factory, values):
    user = user_factory()
    fields = dict(user_id=user.id, key="example-key", request_fingerprint="a" * 64)
    fields.update(values)
    with pytest.raises(IntegrityError), db.begin():
        db.add(IdempotencyRecord(**fields))
        db.flush()


def test_idempotency_keys_are_unique_per_user(db, user_factory):
    first, second = user_factory(), user_factory("other@example.com")
    with db.begin():
        db.add_all(
            [
                IdempotencyRecord(user_id=user.id, key="same", request_fingerprint="a" * 64)
                for user in [first, second]
            ]
        )
    with pytest.raises(IntegrityError), db.begin():
        db.add(IdempotencyRecord(user_id=first.id, key="same", request_fingerprint="a" * 64))
        db.flush()


def test_foreign_key_restricts_deleting_referenced_user(db, event):
    with pytest.raises(IntegrityError), db.begin():
        db.execute(delete(User).where(User.id == event.organizer_id))


def test_server_side_uuid_and_defaults(db, password_hash):
    from sqlalchemy import text

    with db.begin():
        result = db.execute(
            text(
                "INSERT INTO users(normalized_email,password_hash) VALUES (:email,:hash) "
                "RETURNING id,role,is_active,created_at"
            ),
            {"email": "defaults@example.com", "hash": password_hash},
        ).one()
    assert result.id and result.role == "ATTENDEE" and result.is_active and result.created_at.tzinfo
