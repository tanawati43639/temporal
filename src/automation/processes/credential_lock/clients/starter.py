"""Start a CredentialLockWorkflow for a named credential.

Run:
    uv run python -m automation.processes.credential_lock.clients.starter \
        --credential SAP_01
    uv run python -m automation.processes.credential_lock.clients.starter \
        --credential SAP_01 --timeout 600
"""

import argparse
import asyncio

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config, temporal_ui_link

from ..configs.queues import CREDENTIAL_LOCK_QUEUE, LOCK_TIMEOUT_SECONDS
from ..models.credential import LockManagerInput
from ..workflows.lock_manager import CredentialLockWorkflow


async def main() -> None:
    parser = argparse.ArgumentParser(description="Start a credential lock manager")
    parser.add_argument("--credential", required=True, help="Credential name to manage")
    parser.add_argument(
        "--timeout",
        type=int,
        default=LOCK_TIMEOUT_SECONDS,
        help=f"Auto-release timeout in seconds (default {LOCK_TIMEOUT_SECONDS})",
    )
    args = parser.parse_args()

    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )

    workflow_id = f"cred-lock-{args.credential}"
    handle = await client.start_workflow(
        CredentialLockWorkflow.run,
        LockManagerInput(
            credential_name=args.credential,
            lock_timeout_seconds=args.timeout,
        ),
        id=workflow_id,
        task_queue=CREDENTIAL_LOCK_QUEUE,
    )
    print(f"Lock manager started: {handle.id}")
    print(f"UI: {temporal_ui_link(handle.id)}")


if __name__ == "__main__":
    asyncio.run(main())
