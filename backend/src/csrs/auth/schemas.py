from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from csrs.auth.crypto import normalize_email
from csrs.models import Role


class EmailPassword(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: str = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def canonical_email(cls, value: str) -> str:
        return normalize_email(value)


class RegisterRequest(EmailPassword):
    password: SecretStr = Field(min_length=15, max_length=128)


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str = Field(validation_alias="normalized_email")
    role: Role


class CsrfResponse(BaseModel):
    csrf_token: str


class AuthResponse(CsrfResponse):
    user: UserResponse


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
