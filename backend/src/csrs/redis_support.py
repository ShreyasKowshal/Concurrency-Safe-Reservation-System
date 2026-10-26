"""Bounded Redis support operations. No reservation state or database transaction ownership."""

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from csrs.config import Settings
from csrs.events.schemas import Capacity, Description, EventDetail
from csrs.redis_connection import BoundedConnection, BoundedResolver, BoundedSSLConnection

LOGGER = logging.getLogger("csrs.redis")
MAX_CACHE_BYTES = 65536

# Fixed windows begin on the first accepted request. All arithmetic and expiry are atomic.
QUOTA = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
local ttl = redis.call('PTTL', KEYS[1])
if count > 0 and ttl < 0 then return redis.error_reply('quota missing expiry') end
if count >= tonumber(ARGV[1]) then return {0, ttl} end
count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[2]) end
return {1, redis.call('PTTL', KEYS[1])}
"""

# A ticket starts BEFORE the SQL read. A delayed old fill cannot renew its own stale lifetime.
CACHE_READ = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
local size = redis.call('STRLEN', KEYS[1])
local ttl = redis.call('PTTL', KEYS[1])
if size > tonumber(ARGV[1]) or ttl > tonumber(ARGV[2]) or ttl < 1 then
    return {now, false}
end
return {now, redis.call('GET', KEYS[1])}
"""
CACHE_FILL = """
local t = redis.call('TIME')
local now = t[1] * 1000 + math.floor(t[2] / 1000)
if tonumber(ARGV[2]) <= now then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'PXAT', ARGV[2])
return 1
"""


class CachedEvent(EventDetail):
    model_config = ConfigDict(extra="forbid")
    # Validate output bounds without applying input-only trimming to existing SQL values.
    title: Annotated[str, Field(min_length=1, max_length=200)]
    location: Annotated[str, Field(min_length=1, max_length=300)]
    description: Description
    capacity: Capacity
    status: Literal["PUBLISHED"]


class CacheValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    event: CachedEvent


@dataclass(frozen=True)
class CacheTicket:
    key: str
    deadline_ms: int


class SupportError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int):
        self.status, self.code, self.message = status, code, message
        self.retry_after = retry_after


def observe(event: str, **fields) -> None:
    # Never include connection URLs, exception text, quota identities, or cached bodies.
    LOGGER.info(json.dumps({"event": event, **fields}, sort_keys=True))


class RedisSupport:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.prefix = f"{settings.redis_namespace}:{settings.environment}:v1"
        self.resolver = BoundedResolver()
        self.client = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            max_connections=settings.redis_max_connections,
            retry=Retry(NoBackoff(), 0),
            protocol=2,
            decode_responses=False,
            connection_class=BoundedSSLConnection
            if urlsplit(settings.redis_url.get_secret_value()).scheme == "rediss"
            else BoundedConnection,
            resolver=self.resolver,
        )

    def close(self) -> None:
        try:
            self.client.close()
        finally:
            self.resolver.close()

    def event_key(self, event_id: UUID) -> str:
        return f"{self.prefix}:event:{event_id}"

    def quota(self, scope: str, identity: str, limit: int, *, required: bool = False) -> None:
        if not self.settings.rate_limits_enabled:
            return
        digest = hashlib.sha256(identity.encode()).hexdigest()
        key = f"{self.prefix}:quota:{scope}:{digest}"
        try:
            allowed, retry_ms = self.client.eval(
                QUOTA, 1, key, limit, self.settings.rate_limit_window_seconds * 1000
            )
        except RedisError as error:
            observe(
                "quota_unavailable", scope=scope, error_type=type(error).__name__, required=required
            )
            if required:
                raise SupportError(
                    503,
                    "TEMPORARILY_UNAVAILABLE",
                    "The rate limiter is temporarily unavailable.",
                    1,
                ) from None
            return
        if not allowed:
            observe("quota_rejected", scope=scope)
            raise SupportError(
                429, "RATE_LIMITED", "Request quota exceeded.", max(1, math.ceil(retry_ms / 1000))
            )

    def lookup(self, event_id: UUID) -> tuple[EventDetail | None, CacheTicket | None]:
        if not self.settings.metadata_cache_enabled:
            return None, None
        key = self.event_key(event_id)
        try:
            now, raw = self.client.eval(
                CACHE_READ, 1, key, MAX_CACHE_BYTES, self.settings.metadata_cache_ttl_seconds * 1000
            )
        except RedisError as error:
            observe("cache_unavailable", operation="read", error_type=type(error).__name__)
            return None, None
        ticket = CacheTicket(key, now + self.settings.metadata_cache_ttl_seconds * 1000)
        if raw:
            try:
                value = CacheValue.model_validate_json(raw)
                if value.event.id != event_id:
                    raise ValueError("Wrong event")
            except (ValidationError, ValueError):
                observe("cache_invalid")
            else:
                observe("cache_hit")
                return value.event, None
        observe("cache_miss")
        return None, ticket

    def fill(self, ticket: CacheTicket | None, event: EventDetail) -> None:
        if ticket is None:
            return
        try:
            payload = CacheValue(
                version=1, event=CachedEvent.model_validate(event.model_dump())
            ).model_dump_json()
        except ValidationError:
            # The API's output DTO can represent existing SQL data beyond cache limits.
            # Optional cache restrictions must not turn that successful SQL read into 500.
            observe("cache_unrepresentable")
            return
        if len(payload.encode()) > MAX_CACHE_BYTES:
            observe("cache_oversize")
            return
        try:
            written = self.client.eval(CACHE_FILL, 1, ticket.key, payload, ticket.deadline_ms)
            observe("cache_fill", written=bool(written))
        except RedisError as error:
            observe("cache_unavailable", operation="fill", error_type=type(error).__name__)

    def invalidate(self, event_id: UUID) -> None:
        if not self.settings.metadata_cache_enabled:
            return
        try:
            self.client.delete(self.event_key(event_id))
            observe("cache_invalidated")
        except RedisError as error:
            observe("cache_unavailable", operation="invalidate", error_type=type(error).__name__)
