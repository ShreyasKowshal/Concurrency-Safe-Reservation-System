"""Application factory with explicit configuration and engine ownership."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError

from csrs.api.auth import router as auth_router
from csrs.api.events import organizer_router, public_router
from csrs.api.health import router as health_router
from csrs.api.openapi import install_auth_schema
from csrs.api.reservations import router as reservation_router
from csrs.auth.errors import AuthError
from csrs.config import Settings
from csrs.database import create_database_engine
from csrs.events.errors import EventError
from csrs.redis_support import RedisSupport, SupportError


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    logging.basicConfig(level=configuration.log_level.upper(), format="%(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(configuration)
        app.state.database_engine = engine
        support = RedisSupport(configuration)
        app.state.redis_support = support
        try:
            yield
        finally:
            try:
                support.close()
            finally:
                engine.dispose()

    app = FastAPI(
        title=configuration.app_name,
        version="0.4.0",
        description="CSRS health, authentication, events, and concurrency-safe reservations.",
        lifespan=lifespan,
    )
    app.state.settings = configuration

    @app.exception_handler(SupportError)
    async def support_error(request: Request, error: SupportError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message}},
            headers={"Cache-Control": "no-store", "Retry-After": str(error.retry_after)},
        )

    @app.middleware("http")
    async def prevent_sensitive_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(
            (
                "/api/v1/auth/",
                "/api/v1/organizer/events",
                "/api/v1/events",
                "/api/v1/reservations",
                "/api/v1/me/reservations",
            )
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AuthError)
    @app.exception_handler(EventError)
    async def controlled_error(request: Request, error: AuthError | EventError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={"error": {"code": error.code, "message": error.message}},
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # Pydantic normally echoes invalid inputs. Never return passwords or token values.
        detail = [{key: item[key] for key in ("type", "loc", "msg")} for item in error.errors()]
        return JSONResponse(
            status_code=422, content={"detail": detail}, headers={"Cache-Control": "no-store"}
        )

    async def unavailable(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "TEMPORARILY_UNAVAILABLE",
                    "message": "The database is temporarily unavailable.",
                }
            },
            headers={"Cache-Control": "no-store"},
        )

    app.add_exception_handler(OperationalError, unavailable)
    app.add_exception_handler(DatabaseTimeoutError, unavailable)
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(public_router, prefix="/api/v1")
    app.include_router(organizer_router, prefix="/api/v1")
    app.include_router(reservation_router, prefix="/api/v1")
    install_auth_schema(app, configuration)
    return app
