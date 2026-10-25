"""Reusable authentication/role/ownership guards for later event and reservation routes."""

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from csrs.auth.errors import AuthError
from csrs.auth.service import current_user
from csrs.config import Settings
from csrs.models import Role, User


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    with Session(request.app.state.database_engine, expire_on_commit=False) as db:
        yield db


Database = Annotated[Session, Depends(get_db)]
Configuration = Annotated[Settings, Depends(get_settings)]


def get_current_user(request: Request, db: Database, settings: Configuration) -> User:
    return current_user(db, request.cookies.get(settings.session_cookie_name))


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    if not roles:
        raise ValueError("At least one permitted role is required")

    def guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AuthError(403, "FORBIDDEN", "This role cannot perform the requested operation.")
        return user

    return guard


require_organizer = require_roles(Role.ORGANIZER)
require_attendee = require_roles(Role.ATTENDEE, Role.ORGANIZER)


def require_owner(owner_id: UUID, user: User) -> None:
    if owner_id != user.id:
        raise AuthError(404, "NOT_FOUND", "Resource not found.")
