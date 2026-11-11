"""Activities for credential storage and lock notification."""

from __future__ import annotations

import os

from temporalio import activity
from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config

from ..models.credential import CredentialInfo, GrantedSignal


@activity.defn
async def get_credential(credential_name: str) -> CredentialInfo:
    """Retrieve a credential by name.

    Looks up ``CRED_{NAME}_USER`` and ``CRED_{NAME}_PASS`` environment
    variables.  In production, replace this with a vault or secret-manager
    call.
    """
    key = credential_name.upper().replace("-", "_").replace(" ", "_")
    username = os.environ.get(f"CRED_{key}_USER", "")
    password = os.environ.get(f"CRED_{key}_PASS", "")

    if not username:
        activity.logger.warning("Credential %s not found in env vars", credential_name)

    return CredentialInfo(name=credential_name, username=username, password=password)


@activity.defn
async def notify_granted(grant: GrantedSignal, requester_workflow_id: str) -> None:
    """Signal the requester workflow that the lock has been granted."""
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    handle = client.get_workflow_handle(requester_workflow_id)
    await handle.signal("credential_granted", grant)
    activity.logger.info(
        "Notified %s: credential '%s' granted",
        requester_workflow_id,
        grant.credential_name,
    )


ACTIVITIES = [get_credential, notify_granted]
