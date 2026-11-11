"""Worker for the credential-lock process.

Run:
    uv run python -m automation.processes.credential_lock.workers.worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config

from ..activities.credential_store import ACTIVITIES
from ..configs.queues import CREDENTIAL_LOCK_QUEUE, MAX_CONCURRENT_ACTIVITIES
from ..workflows.lock_manager import CredentialLockWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    worker = Worker(
        client,
        task_queue=CREDENTIAL_LOCK_QUEUE,
        workflows=[CredentialLockWorkflow],
        activities=[*ACTIVITIES],
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )
    print(f"Worker running on '{CREDENTIAL_LOCK_QUEUE}' ({TEMPORAL_ADDRESS}/{TEMPORAL_NAMESPACE})")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
