import secrets


_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def public_reference(prefix: str = "RM", length: int = 15) -> str:
    """Return a readable reference with more than 72 bits of entropy."""
    if length < 15:
        raise ValueError("Public references must contain at least 15 random symbols")
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(length))

