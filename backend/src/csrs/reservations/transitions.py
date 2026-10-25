"""Caller must hold the event row lock in the same transaction. Never commits."""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from csrs.models import Event, Reservation


def expire_due_holds(db: Session, event: Event, decision_time: datetime) -> int:
    changed = list(
        db.scalars(
            update(Reservation)
            .where(
                Reservation.event_id == event.id,
                Reservation.status == "HELD",
                Reservation.hold_expires_at <= decision_time,
            )
            .values(status="EXPIRED", expired_at=decision_time, updated_at=decision_time)
            .returning(Reservation.id)
        )
    )
    event.allocated_seats -= len(changed)
    if changed:
        event.updated_at = decision_time
    return len(changed)
