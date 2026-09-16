import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def _evp_bytes_to_key(password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    """Replicate CryptoJS/OpenSSL passphrase KDF used by HighLevel Custom Pages."""
    derived = b""
    previous = b""
    while len(derived) < 48:
        previous = hashlib.md5(previous + password + salt).digest()  # noqa: S324
        derived += previous
    return derived[:32], derived[32:48]


@dataclass(frozen=True, slots=True)
class GHLUserContext:
    user_id: str
    company_id: str | None
    role: str
    context_type: str
    active_location: str
    user_name: str | None
    email: str | None
    is_agency_owner: bool


def decrypt_ghl_user_context(encrypted_data: str, shared_secret: str) -> GHLUserContext:
    if not shared_secret:
        raise ValueError("GHL_APP_SHARED_SECRET is not configured")
    try:
        raw = base64.b64decode(encrypted_data, validate=True)
    except Exception as exc:
        raise ValueError("Malformed encrypted GHL context") from exc
    if len(raw) < 32 or raw[:8] != b"Salted__":
        raise ValueError("Malformed encrypted GHL context")
    salt, ciphertext = raw[8:16], raw[16:]
    if not ciphertext or len(ciphertext) % 16:
        raise ValueError("Malformed encrypted GHL context")
    key, iv = _evp_bytes_to_key(shared_secret.encode(), salt)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    try:
        unpadder = padding.PKCS7(128).unpadder()
        decoded = unpadder.update(padded) + unpadder.finalize()
        payload = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Unable to decrypt GHL context") from exc

    user_id = payload.get("userId")
    active_location = payload.get("activeLocation")
    role = payload.get("role") or "user"
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("GHL context is missing userId")
    if not isinstance(active_location, str) or not active_location:
        raise ValueError("Open Passport from inside a GoHighLevel sub-account")
    return GHLUserContext(
        user_id=user_id,
        company_id=payload.get("companyId"),
        role=str(role),
        context_type=str(payload.get("type") or "location"),
        active_location=active_location,
        user_name=payload.get("userName"),
        email=payload.get("email"),
        is_agency_owner=bool(payload.get("isAgencyOwner", False)),
    )

