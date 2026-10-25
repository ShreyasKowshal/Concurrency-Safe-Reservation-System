"""Application factory with explicit configuration and engine ownership."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from csrs.api.health import router as health_router
from csrs.config import Settings
from csrs.database import create_database_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(configuration)
        app.state.database_engine = engine
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=configuration.app_name,
        version="0.1.0",
        description="Phase 1 foundation. Only health endpoints are implemented.",
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api/v1")
    return app
