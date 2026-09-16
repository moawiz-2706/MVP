import base64
import hashlib
import json
import os
import uuid

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.app_session import SessionPrincipal, create_app_session, decode_app_session
from app.core.config import Settings
from app.core.encryption import TokenCipher
from app.core.ghl_context import decrypt_ghl_user_context


def cryptojs_encrypt(payload: dict, secret: str) -> str:
    salt = os.urandom(8)
    derived = previous = b""
    while len(derived) < 48:
        previous = hashlib.md5(previous + secret.encode() + salt).digest()
        derived += previous
    padder = padding.PKCS7(128).padder()
    padded = padder.update(json.dumps(payload).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(derived[:32]), modes.CBC(derived[32:48])).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(b"Salted__" + salt + ciphertext).decode()


def test_highlevel_cryptojs_context_round_trip() -> None:
    payload = {
        "userId": "user-1",
        "companyId": "company-1",
        "role": "admin",
        "type": "agency",
        "activeLocation": "location-1",
        "userName": "Ada Lovelace",
        "email": "ada@example.com",
        "isAgencyOwner": True,
    }
    result = decrypt_ghl_user_context(cryptojs_encrypt(payload, "shared-secret"), "shared-secret")
    assert result.user_id == "user-1"
    assert result.active_location == "location-1"
    assert result.is_agency_owner is True


def test_context_requires_active_location() -> None:
    encrypted = cryptojs_encrypt({"userId": "user-1", "role": "admin"}, "secret")
    with pytest.raises(ValueError, match="sub-account"):
        decrypt_ghl_user_context(encrypted, "secret")


def test_invalid_context_is_rejected_without_details() -> None:
    with pytest.raises(ValueError, match="Malformed"):
        decrypt_ghl_user_context("not-base64", "secret")


def test_app_session_round_trip_and_wrong_secret_rejected() -> None:
    settings = Settings(app_session_secret="a" * 32)
    principal = SessionPrincipal(uuid.uuid4(), uuid.uuid4(), "loc-1", "admin", False)
    token, expires_in = create_app_session(principal, settings)
    assert expires_in == 900
    assert decode_app_session(token, settings) == principal
    with pytest.raises(Exception):
        decode_app_session(token, Settings(app_session_secret="b" * 32))


def test_oauth_token_encryption_is_authenticated() -> None:
    cipher = TokenCipher("this-is-a-dedicated-encryption-secret")
    encrypted = cipher.encrypt("oauth-token")
    assert encrypted != "oauth-token"
    assert cipher.decrypt(encrypted) == "oauth-token"
    with pytest.raises(ValueError):
        cipher.decrypt(encrypted[:-2] + "aa")


def test_spec158_49_expired_app_session_is_rejected() -> None:
    import datetime as _dt

    import jwt
    from fastapi import HTTPException

    settings = Settings(app_session_secret="a" * 32)
    past = _dt.datetime.now(_dt.UTC) - _dt.timedelta(minutes=30)
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "operator_id": str(uuid.uuid4()),
            "ghl_location_id": "loc-1",
            "role": "admin",
            "is_agency_owner": False,
            "iat": past,
            "exp": past + _dt.timedelta(minutes=15),  # expired 15 minutes ago
            "aud": "passport",
            "iss": "passport-api",
        },
        settings.app_session_secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        decode_app_session(expired, settings)
    assert exc.value.status_code == 401
