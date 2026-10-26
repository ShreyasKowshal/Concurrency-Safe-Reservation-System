"""Caller must hold the event row lock in the same transaction. Never commits."""

from datetime import datetime

from sqlalchemy import literal_column, select, update
from sqlalchemy.orm import Session

from csrs.models import Event, Reservation


def expire_due_holds(
    db: Session,
    event: Event,
    decision_time: datetime,
    *,
    limit: int | None = None,
) -> int:
    statement = update(Reservation).where(
        Reservation.event_id == event.id,
        Reservation.status == literal_column("'HELD'"),
        Reservation.hold_expires_at <= decision_time,
    )
    if limit is not None:
        if limit < 1:
            raise ValueError("Expiration limit must be positive")
        candidates = (
            select(Reservation.id)
            .where(
                Reservation.event_id == event.id,
                Reservation.status == literal_column("'HELD'"),
                Reservation.hold_expires_at <= decision_time,
            )
            .order_by(Reservation.hold_expires_at, Reservation.id)
            .limit(limit)
        )
        statement = statement.where(Reservation.id.in_(candidates))
    changed = list(
        db.scalars(
            statement.values(
                status="EXPIRED", expired_at=decision_time, updated_at=decision_time
            ).returning(Reservation.id)
        )
    )
    event.allocated_seats -= len(changed)
    if changed:
        event.updated_at = decision_time
    return len(changed)
