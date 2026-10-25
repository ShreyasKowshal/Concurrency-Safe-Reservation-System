"""Validated environment configuration; importing this module performs no I/O."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CSRS_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["local", "test", "production"] = "local"
    app_name: str = Field(default="CSRS", min_length=1, max_length=80)
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    public_origin: str = "http://localhost:5173"
    database_url: SecretStr
    redis_url: SecretStr
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=10)
    db_statement_timeout_ms: int = Field(default=3000, ge=100, le=30000)
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("database_url must be a valid PostgreSQL URL") from None
        if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
            raise ValueError("database_url requires postgresql+psycopg, a host, and a database")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = urlsplit(value.get_secret_value())
            valid = url.scheme in {"redis", "rediss"} and url.hostname and url.port != 0
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("redis_url must be a valid redis:// or rediss:// URL with a host")
        return value

    @field_validator("public_origin")
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            valid = (
                url.scheme in {"http", "https"}
                and url.hostname
                and url.port != 0
                and not url.username
                and not url.password
                and not url.path
                and not url.query
                and not url.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "public_origin must be an HTTP(S) origin without a path or credentials"
            )
        return value

    @model_validator(mode="after")
    def require_https_in_production(self) -> "Settings":
        if self.environment == "production" and not self.public_origin.startswith("https://"):
            raise ValueError("production public_origin requires HTTPS")
        return self
