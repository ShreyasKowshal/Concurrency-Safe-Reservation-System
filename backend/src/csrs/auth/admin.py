"""Local administrator operations. Never exposed through public HTTP routes."""

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from csrs.auth.crypto import normalize_email
from csrs.auth.service import database_time
from csrs.models import Role, SessionRecord, User


def promote_organizer(db: Session, email: str) -> User:
    email = normalize_email(email)
    with db.begin():
        user = db.scalar(select(User).where(User.normalized_email == email).with_for_update())
        if user is None or not user.is_active:
            raise ValueError("An active registered user is required")
        user.role = Role.ORGANIZER
        now = database_time(db)
        db.execute(
            update(SessionRecord)
            .where(SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    return user


def purge_sessions(db: Session, batch_size: int = 1000) -> int:
    if not 1 <= batch_size <= 10000:
        raise ValueError("batch_size must be between 1 and 10000")
    with db.begin():
        now = database_time(db)
        ids = (
            select(SessionRecord.id)
            .where(or_(SessionRecord.expires_at <= now, SessionRecord.revoked_at.is_not(None)))
            .order_by(SessionRecord.expires_at, SessionRecord.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        return db.execute(delete(SessionRecord).where(SessionRecord.id.in_(ids))).rowcount
