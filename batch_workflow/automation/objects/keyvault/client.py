"""Azure Key Vault access — WORKER-SIDE ONLY.

Secrets are fetched here and used to build service clients. They are NEVER
returned to a workflow: anything a workflow sees is written to Event History
(and shown in the Temporal UI) forever. So there is deliberately no
`@activity.defn get_secret` that hands a secret back to workflow code.

For local dev with no Azure configured, this falls back to environment vars.
Azure packages are imported lazily so they stay an optional dependency
(`uv sync --extra azure`).
"""

import logging
import os

logger = logging.getLogger(__name__)


async def get_secret(name: str) -> str:
    """Fetch a secret value for use inside the worker process only."""
    vault_url = os.environ.get("AZURE_VAULT_URL")

    if not vault_url:
        # Dev fallback: secret "graph-client-secret" -> env GRAPH_CLIENT_SECRET
        env_name = name.upper().replace("-", "_")
        logger.warning(
            "AZURE_VAULT_URL not set; reading secret %r from env %r (dev mode)",
            name,
            env_name,
        )
        return os.environ.get(env_name, "dev-placeholder-secret")

    # Real Azure Key Vault (requires: uv sync --extra azure)
    from azure.identity.aio import DefaultAzureCredential
    from azure.keyvault.secrets.aio import SecretClient

    async with DefaultAzureCredential() as cred, SecretClient(vault_url, cred) as kv:
        secret = await kv.get_secret(name)
    return secret.value
