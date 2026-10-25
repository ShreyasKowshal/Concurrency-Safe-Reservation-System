"""Password and token primitives; never log their inputs or outputs."""

import hashlib
import re
import secrets
from functools import lru_cache

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from email_validator import EmailNotValidError, validate_email

PASSWORD_HASHER = PasswordHasher(
    time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
)


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Unknown accounts still perform a real verification against a process-local dummy."""
    return hash_password(secrets.token_urlsafe(32))


def new_token() -> str:
    return secrets.token_hex(32)


def valid_token(value: str | None) -> bool:
    return value is not None and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def normalize_email(value: str) -> str:
    try:
        address = validate_email(value.strip(), check_deliverability=False, allow_smtputf8=False)
    except EmailNotValidError:
        raise ValueError("Enter a valid email address") from None
    return address.ascii_email.lower()
