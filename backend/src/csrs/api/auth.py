from fastapi import APIRouter, Depends, Request, Response

from csrs.auth import service
from csrs.auth.dependencies import Configuration, CurrentUser, Database
from csrs.auth.http import (
    clear_session_cookie,
    set_session_cookie,
    validate_mutation_request,
    validate_source,
)
from csrs.auth.schemas import (
    AuthResponse,
    CsrfResponse,
    EmailPassword,
    EmptyRequest,
    ErrorResponse,
    RegisterRequest,
    UserResponse,
)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={
        401: {"model": ErrorResponse, "description": "Authentication failed"},
        403: {"model": ErrorResponse, "description": "CSRF or authorization rejected"},
        503: {"model": ErrorResponse, "description": "Database temporarily unavailable"},
    },
)
mutation = [Depends(validate_mutation_request)]


@router.get("/csrf", response_model=CsrfResponse)
def csrf(
    request: Request, response: Response, db: Database, settings: Configuration
) -> CsrfResponse:
    validate_source(request, settings, bootstrap=True)
    reply = service.bootstrap(db, settings, request.cookies.get(settings.session_cookie_name))
    if reply.cookie:
        set_session_cookie(response, settings, reply.cookie, reply.max_age)
    return CsrfResponse(csrf_token=reply.csrf_token)


@router.post(
    "/register",
    status_code=201,
    response_model=AuthResponse,
    dependencies=mutation,
    responses={409: {"model": ErrorResponse}, 415: {"model": ErrorResponse}},
)
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Database,
    settings: Configuration,
) -> AuthResponse:
    reply = service.register(
        db,
        settings,
        request.cookies.get(settings.session_cookie_name),
        request.headers.get("x-csrf-token"),
        body.email,
        body.password.get_secret_value(),
    )
    set_session_cookie(response, settings, reply.cookie, reply.max_age)
    return AuthResponse(user=reply.user, csrf_token=reply.csrf_token)


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=mutation,
    responses={415: {"model": ErrorResponse}},
)
def login(
    body: EmailPassword,
    request: Request,
    response: Response,
    db: Database,
    settings: Configuration,
) -> AuthResponse:
    reply = service.login(
        db,
        settings,
        request.cookies.get(settings.session_cookie_name),
        request.headers.get("x-csrf-token"),
        body.email,
        body.password.get_secret_value(),
    )
    set_session_cookie(response, settings, reply.cookie, reply.max_age)
    return AuthResponse(user=reply.user, csrf_token=reply.csrf_token)


@router.post(
    "/logout", status_code=204, dependencies=mutation, responses={415: {"model": ErrorResponse}}
)
def logout(
    body: EmptyRequest,
    request: Request,
    db: Database,
    settings: Configuration,
) -> Response:
    service.logout(
        db, request.cookies.get(settings.session_cookie_name), request.headers.get("x-csrf-token")
    )
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
