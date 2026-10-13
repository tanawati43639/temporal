"""Environment settings and credentials access — the Temporal equivalent of
Blue Prism Environment Variables / Credential Manager.

Never read secrets inside a workflow; only activities (objects/) may touch them.
"""

import os

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")


def get_secret(name: str, default: str | None = None) -> str | None:
    """Fetch a credential. Swap this for Vault/AWS Secrets Manager in prod."""
    return os.environ.get(name, default)
