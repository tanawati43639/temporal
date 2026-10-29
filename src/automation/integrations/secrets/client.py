"""Secret / config store integration — env-backed by default.

This is the credential-manager equivalent. Swap the body of ``get_secret`` for
Vault / AWS Secrets Manager / Azure Key Vault in production; callers don't change.
"""

import os


def get_secret(name: str, default: str | None = None) -> str | None:
    """Fetch a credential or config value. Only call this from activities."""
    return os.environ.get(name, default)
