"""Authentication transactions. Hashing occurs outside session-row lock transactions."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from csrs.auth.crypto import (
    PASSWORD_HASHER,
    dummy_password_hash,
    hash_password,
    new_token,
    token_digest,
    valid_token,
    verify_password,
)
from csrs.auth.errors import (
    AuthError,
    authentication_required,
    csrf_failed,
    invalid_credentials,
)
from csrs.auth.schemas import UserResponse
from csrs.config import Settings
from csrs.models import Role, SessionKind, SessionRecord, User


@dataclass
class SessionReply:
    cookie: str = field(repr=False)
    csrf_token: str = field(repr=False)
    max_age: int
    user: UserResponse | None = None


def database_time(db: Session) -> datetime:
    return db.scalar(select(func.clock_timestamp()))


def find_session(db: Session, cookie: str | None, *, lock: bool = False) -> SessionRecord | None:
    if not valid_token(cookie):
        return None
    statement = select(SessionRecord).where(SessionRecord.token_hash == token_digest(cookie))
    if lock:
        statement = statement.with_for_update()
    record = db.scalar(statement.execution_options(populate_existing=True))
    now = database_time(db)
    if record is None or record.revoked_at is not None or record.expires_at <= now:
        return None
    return record


def require_session(
    db: Session,
    cookie: str | None,
    csrf: str | None,
    kind: SessionKind,
    *,
    lock: bool = False,
) -> SessionRecord:
    record = find_session(db, cookie, lock=lock)
    if record is None or record.kind != kind:
        raise csrf_failed() if kind == SessionKind.ANONYMOUS else authentication_required()
    if not valid_token(csrf) or not secrets.compare_digest(record.csrf_token, csrf):
        raise csrf_failed()
    return record


def issue_session(db: Session, settings: Settings, user: User | None = None) -> SessionReply:
    cookie, csrf = new_token(), new_token()
    ttl = (
        settings.session_ttl_seconds if user is not None else settings.anonymous_session_ttl_seconds
    )
    db.add(
        SessionRecord(
            user_id=user.id if user is not None else None,
            kind=SessionKind.AUTHENTICATED if user is not None else SessionKind.ANONYMOUS,
            token_hash=token_digest(cookie),
            csrf_token=csrf,
            expires_at=database_time(db) + timedelta(seconds=ttl),
        )
    )
    return SessionReply(
        cookie=cookie,
        csrf_token=csrf,
        max_age=ttl,
        user=UserResponse.model_validate(user) if user is not None else None,
    )


def bootstrap(
    db: Session, settings: Settings, cookie: str | None, *, create: bool = True
) -> SessionReply | None:
    with db.begin():
        record = find_session(db, cookie, lock=True)
        if record is not None:
            user = db.get(User, record.user_id) if record.user_id else None
            if record.kind == SessionKind.ANONYMOUS or (user is not None and user.is_active):
                # Do not extend database or cookie expiry when retrieving an existing token.
                return SessionReply(cookie="", csrf_token=record.csrf_token, max_age=0)
        if not create:
            # Read an existing token during a Redis outage without creating durable rows.
            return None
        if record is not None:
            record.revoked_at = database_time(db)
        reply = issue_session(db, settings)
    return reply


def register(
    db: Session,
    settings: Settings,
    cookie: str | None,
    csrf: str | None,
    email: str,
    password: str,
) -> SessionReply:
    with db.begin():
        require_session(db, cookie, csrf, SessionKind.ANONYMOUS)
    password_hash = hash_password(password)
    try:
        with db.begin():
            previous = require_session(db, cookie, csrf, SessionKind.ANONYMOUS, lock=True)
            user = User(normalized_email=email, password_hash=password_hash, role=Role.ATTENDEE)
            db.add(user)
            db.flush()
            db.delete(previous)
            reply = issue_session(db, settings)
            reply.user = UserResponse.model_validate(user)
    except IntegrityError as error:
        if (
            getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            != "uq_users_normalized_email"
        ):
            raise
        raise AuthError(
            409, "REGISTRATION_UNAVAILABLE", "The account could not be created."
        ) from None
    return reply


def login(
    db: Session,
    settings: Settings,
    cookie: str | None,
    csrf: str | None,
    email: str,
    password: str,
) -> SessionReply:
    with db.begin():
        require_session(db, cookie, csrf, SessionKind.ANONYMOUS)
        user = db.scalar(select(User).where(User.normalized_email == email))
        stored_hash = user.password_hash if user is not None else None
        candidate_id = user.id if user is not None else None
    stored_hash = stored_hash or dummy_password_hash()
    verified = verify_password(stored_hash, password)
    if not verified or candidate_id is None:
        raise invalid_credentials()
    replacement_hash = (
        hash_password(password) if PASSWORD_HASHER.check_needs_rehash(stored_hash) else None
    )
    with db.begin():
        previous = require_session(db, cookie, csrf, SessionKind.ANONYMOUS, lock=True)
        user = db.scalar(
            select(User)
            .where(User.id == candidate_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None or not user.is_active or user.password_hash != stored_hash:
            raise invalid_credentials()
        if replacement_hash:
            user.password_hash = replacement_hash
        db.delete(previous)
        reply = issue_session(db, settings, user)
    return reply


def current_user(db: Session, cookie: str | None) -> User:
    with db.begin():
        record = find_session(db, cookie)
        if record is None or record.kind != SessionKind.AUTHENTICATED:
            raise authentication_required()
        user = db.get(User, record.user_id)
        if user is None or not user.is_active:
            raise authentication_required()
    return user


def logout(db: Session, cookie: str | None, csrf: str | None) -> None:
    with db.begin():
        record = require_session(db, cookie, csrf, SessionKind.AUTHENTICATED, lock=True)
        user = db.get(User, record.user_id)
        if user is None or not user.is_active:
            raise authentication_required()
        record.revoked_at = database_time(db)
