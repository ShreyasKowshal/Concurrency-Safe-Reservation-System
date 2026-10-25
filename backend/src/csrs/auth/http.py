"""Browser boundary checks. Never infer trusted origins from client Host/forwarded headers."""

from urllib.parse import urlsplit

from fastapi import Request, Response

from csrs.auth.errors import AuthError, csrf_failed
from csrs.config import Settings


def origin_tuple(value: str, *, referer: bool = False) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            any(character.isspace() for character in value)
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.port == 0
            or parsed.username is not None
            or parsed.password is not None
            or "#" in value
            or (not referer and (parsed.path or "?" in value))
        ):
            return None
        return (
            parsed.scheme,
            parsed.hostname.lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except ValueError:
        return None


def validate_source(request: Request, settings: Settings, *, bootstrap: bool = False) -> None:
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise csrf_failed()
    expected = origin_tuple(settings.public_origin)
    if expected is None:
        raise csrf_failed()
    origins = request.headers.getlist("origin")
    referers = request.headers.getlist("referer")
    if origins:
        if len(origins) != 1 or origin_tuple(origins[0]) != expected:
            raise csrf_failed()
    elif referers:
        if len(referers) != 1 or origin_tuple(referers[0], referer=True) != expected:
            raise csrf_failed()
    elif not bootstrap:
        raise csrf_failed()


def validate_mutation_request(request: Request) -> None:
    settings = request.app.state.settings
    validate_source(request, settings)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise AuthError(415, "UNSUPPORTED_MEDIA_TYPE", "Use application/json.")


def set_session_cookie(response: Response, settings: Settings, token: str, max_age: int) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
