"""Activities for the credential pool."""

from __future__ import annotations

from temporalio import activity
from temporalio.client import Client

from automation.integrations.secrets.client import get_secret
from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config

from ..models.pool import CredentialInfo, GrantedSignal


@activity.defn
async def fetch_credential(credential_name: str) -> CredentialInfo:
    """Retrieve a credential by name from the secret store.

    Looks up ``CRED_{NAME}_USER`` and ``CRED_{NAME}_PASS``.
    """
    key = credential_name.upper().replace("-", "_").replace(" ", "_")
    username = get_secret(f"CRED_{key}_USER") or ""
    password = get_secret(f"CRED_{key}_PASS") or ""

    if not username:
        activity.logger.warning("Credential %s: env var CRED_%s_USER not set", credential_name, key)

    return CredentialInfo(name=credential_name, username=username, password=password)


@activity.defn
async def signal_requester_granted(grant: GrantedSignal, requester_workflow_id: str) -> None:
    """Signal the requester workflow that a credential has been granted."""
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    handle = client.get_workflow_handle(requester_workflow_id)
    await handle.signal("credential_granted", grant)
    activity.logger.info(
        "Granted '%s' to %s", grant.credential_name, requester_workflow_id
    )


ACTIVITIES = [fetch_credential, signal_requester_granted]
