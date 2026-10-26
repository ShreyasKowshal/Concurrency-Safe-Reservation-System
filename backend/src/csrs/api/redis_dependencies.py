"""Transport-level quotas. SQL preflight ends before Redis; mutation services reauthorize."""

from fastapi import Request
from sqlalchemy.orm import Session

from csrs.auth.dependencies import require_attendee, require_organizer
from csrs.auth.errors import authentication_required
from csrs.auth.service import require_session
from csrs.models import SessionKind, User


def peer(request: Request) -> str:
    # Ignore forwarded headers. Deploy with proxy headers disabled until a trusted proxy exists.
    return request.client.host if request.client else "unknown"


def anonymous_quota(request: Request, scope: str) -> None:
    settings = request.app.state.settings
    limit = settings.rate_limit_bootstrap if scope == "bootstrap" else settings.rate_limit_auth
    request.app.state.redis_support.quota(scope, peer(request), limit, required=True)


def public_quota(request: Request) -> None:
    request.app.state.redis_support.quota(
        "public", peer(request), request.app.state.settings.rate_limit_public
    )


def mutation_quota(request: Request, db: Session, *, organizer: bool = False) -> None:
    settings = request.app.state.settings
    if not settings.rate_limits_enabled:
        return
    with db.begin():
        record = require_session(
            db,
            request.cookies.get(settings.session_cookie_name),
            request.headers.get("x-csrf-token"),
            SessionKind.AUTHENTICATED,
        )
        user = db.get(User, record.user_id, populate_existing=True)
        if user is None or not user.is_active:
            raise authentication_required()
        (require_organizer if organizer else require_attendee)(user)
        identity = str(user.id)
    request.app.state.redis_support.quota("mutation", identity, settings.rate_limit_mutation)
