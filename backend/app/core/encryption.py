import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    """Authenticated encryption for persisted OAuth credentials."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("GHL_TOKEN_ENCRYPTION_KEY is required")
        try:
            decoded = base64.urlsafe_b64decode(secret.encode())
            key = secret.encode() if len(decoded) == 32 else self._derive_key(secret)
        except Exception:
            key = self._derive_key(secret)
        self._fernet = Fernet(key)

    @staticmethod
    def _derive_key(secret: str) -> bytes:
        return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt stored credential") from exc

