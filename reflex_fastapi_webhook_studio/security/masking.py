"""Decide which header values the UI hides until the user clicks them."""

MASK = "••••"
_SECRET_NAMES = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie"})
_SECRET_PARTS = ("token", "secret", "signature", "api-key", "apikey", "api_key", "password", "session")


def is_secret_header(name: str) -> bool:
    """Check whether a header likely carries a secret.

    Args:
        name: The header name, in any case.

    Returns:
        Whether the UI should mask the value.
    """
    lowered = name.lower()
    return lowered in _SECRET_NAMES or any(part in lowered for part in _SECRET_PARTS)
