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
    redis_namespace: str = Field(default="csrs", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    redis_connect_timeout_seconds: float = Field(default=0.2, ge=0.05, le=2)
    redis_socket_timeout_seconds: float = Field(default=0.2, ge=0.05, le=2)
    redis_max_connections: int = Field(default=10, ge=1, le=40)
    metadata_cache_enabled: bool = True
    metadata_cache_ttl_seconds: int = Field(default=15, ge=1, le=60)
    rate_limits_enabled: bool = True
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_bootstrap: int = Field(default=30, ge=1, le=10000)
    rate_limit_auth: int = Field(default=10, ge=1, le=10000)
    rate_limit_public: int = Field(default=120, ge=1, le=10000)
    rate_limit_mutation: int = Field(default=60, ge=1, le=10000)
    db_connect_timeout_seconds: int = Field(default=3, ge=1, le=10)
    db_statement_timeout_ms: int = Field(default=3000, ge=100, le=30000)
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    anonymous_session_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    session_ttl_seconds: int = Field(default=28800, ge=300, le=604800)
    hold_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    worker_poll_interval_seconds: float = Field(default=15, ge=0.05, le=3600)
    worker_batch_size: int = Field(default=100, ge=1, le=1000)
    worker_retry_initial_seconds: float = Field(default=1, ge=0.05, le=60)
    worker_retry_max_seconds: float = Field(default=30, ge=0.05, le=300)

    @property
    def secure_cookies(self) -> bool:
        return urlsplit(self.public_origin).scheme == "https"

    @property
    def session_cookie_name(self) -> str:
        return "__Host-csrs_session" if self.secure_cookies else "csrs_session"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except (ArgumentError, ValueError):
            raise ValueError("database_url must be a valid PostgreSQL URL") from None
        if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
            raise ValueError("database_url requires postgresql+psycopg, a host, and a database")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = urlsplit(value.get_secret_value())
            valid = (
                url.scheme in {"redis", "rediss"}
                and url.hostname
                and url.port != 0
                and not url.query
                and not url.fragment
                and (not url.path or url.path == "/" or url.path[1:].isdigit())
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("redis_url requires redis(s), a host, a database path, and no query")
        return value

    @field_validator("public_origin")
    @classmethod
    def validate_public_origin(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            valid = (
                not any(character.isspace() for character in value)
                and "?" not in value
                and "#" not in value
                and url.scheme in {"http", "https"}
                and url.hostname
                and url.port != 0
                and url.username is None
                and url.password is None
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
        if self.worker_retry_initial_seconds > self.worker_retry_max_seconds:
            raise ValueError("worker retry initial delay must not exceed maximum delay")
        if self.environment == "production" and not self.secure_cookies:
            raise ValueError("production public_origin requires HTTPS")
        return self
