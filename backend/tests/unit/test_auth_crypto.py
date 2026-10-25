import pytest
from argon2 import PasswordHasher, Type
from pydantic import ValidationError

from csrs.auth.crypto import (
    hash_password,
    new_token,
    normalize_email,
    token_digest,
    verify_password,
)
from csrs.auth.http import origin_tuple
from csrs.auth.schemas import RegisterRequest


def test_password_hashes_are_salted_argon2id_and_verifiable():
    password = "Long password with spaces and λ"
    first, second = hash_password(password), hash_password(password)
    assert first != second and first.startswith("$argon2id$")
    assert "m=19456,t=2,p=1" in first
    assert verify_password(first, password)
    assert not verify_password(first, password + " ")
    assert password not in first


@pytest.mark.parametrize("encoded", ["", "not-a-hash", "$argon2id$bad"])
def test_invalid_password_hash_fails_closed(encoded):
    assert not verify_password(encoded, "password")


def test_tokens_are_independent_256_bit_values_and_digests():
    first, second = new_token(), new_token()
    assert len(first) == len(second) == 64
    assert first != second and token_digest(first) != first
    assert len(token_digest(first)) == 64


@pytest.mark.parametrize("value", [" User@EXAMPLE.COM ", "user@example.com"])
def test_email_normalization(value):
    assert normalize_email(value) == "user@example.com"


@pytest.mark.parametrize("value", ["bad", "a@localhost", "a b@example.com", "λ@example.com"])
def test_invalid_or_smtputf8_email_is_rejected(value):
    with pytest.raises(ValueError):
        normalize_email(value)


@pytest.mark.parametrize("length", [0, 14, 129])
def test_registration_password_length_is_bounded(length):
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password="x" * length)


def test_password_whitespace_is_not_silently_changed():
    password = "  Long password with spaces  "
    assert (
        RegisterRequest(email="user@example.com", password=password).password.get_secret_value()
        == password
    )


@pytest.mark.parametrize("length", [15, 128])
def test_registration_accepts_password_length_boundaries(length):
    request = RegisterRequest(email="user@example.com", password="x" * length)
    assert len(request.password.get_secret_value()) == length


@pytest.mark.parametrize(
    "value",
    [
        "null",
        "https://good.com.evil.com",
        "http://u:p@good.com",
        "http://good.com:0",
        "http://go\tod.com",
        "http://@good.com",
        "http://:@good.com",
    ],
)
def test_origin_parser_does_not_accept_credentials_or_ambiguous_origins(value):
    assert origin_tuple(value) != ("http", "good.com", 80)


def test_default_origin_port_is_normalized():
    assert origin_tuple("https://good.com") == origin_tuple("https://good.com:443")


def test_old_argon2_parameters_remain_verifiable():
    older = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID)
    assert verify_password(older.hash("long example password"), "long example password")
