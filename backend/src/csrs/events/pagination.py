"""Keyset cursors are navigation data, never authorization credentials."""

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID

from csrs.events.errors import EventError


def encode_cursor(starts_at: datetime, event_id: UUID, scope: str) -> str:
    payload = {
        "v": 1,
        "scope": scope,
        "starts_at": starts_at.astimezone(UTC).isoformat(),
        "id": str(event_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def decode_cursor(value: str, scope: str) -> tuple[datetime, UUID]:
    try:
        if not 1 <= len(value) <= 512:
            raise ValueError
        payload = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "scope", "starts_at", "id"}
            or type(payload["v"]) is not int
            or payload["v"] != 1
            or payload["scope"] != scope
            or not isinstance(payload["starts_at"], str)
            or not isinstance(payload["id"], str)
        ):
            raise ValueError
        instant = datetime.fromisoformat(payload["starts_at"])
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError
        return instant.astimezone(UTC), UUID(payload["id"])
    except (ValueError, TypeError, OverflowError, binascii.Error, UnicodeError):
        raise EventError(
            422, "INVALID_CURSOR", "Use a valid cursor from this event listing."
        ) from None
