"""Public operational probes; never expose connection strings or exception details."""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: dict[Literal["postgresql"], Literal["up", "down"]]


@router.get("/live", response_model=LivenessResponse)
def liveness(response: Response) -> LivenessResponse:
    response.headers["Cache-Control"] = "no-store"
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "PostgreSQL unavailable"}},
)
def readiness(request: Request, response: Response) -> ReadinessResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        with request.app.state.database_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = 503
        return ReadinessResponse(status="not_ready", dependencies={"postgresql": "down"})
    return ReadinessResponse(status="ready", dependencies={"postgresql": "up"})
