import re
import secrets
import string


ALIAS_ALPHABET = string.ascii_letters + string.digits


def generate_alias(length: int = 6) -> str:
    return "".join(secrets.choice(ALIAS_ALPHABET) for _ in range(length))


def clean_alias(value: str | None) -> str | None:
    if value is None:
        return None
    alias = value.strip()
    if not alias:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,255}", alias):
        raise ValueError("Alias must contain only letters, numbers, underscores or hyphens")
    return alias

