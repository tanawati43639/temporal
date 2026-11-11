"""Shared worker for the credential pool.

Run:
    uv run python -m automation.common.credential_pool.worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config

from .activities.pool_activities import ACTIVITIES
from .configs.pool_config import CREDENTIAL_POOL_QUEUE, MAX_CONCURRENT_ACTIVITIES
from .workflows.acquire import AcquireCredentialWorkflow
from .workflows.pool_manager import CredentialPoolWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    worker = Worker(
        client,
        task_queue=CREDENTIAL_POOL_QUEUE,
        workflows=[CredentialPoolWorkflow, AcquireCredentialWorkflow],
        activities=[*ACTIVITIES],
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )
    print(f"Credential pool worker on '{CREDENTIAL_POOL_QUEUE}' ({TEMPORAL_ADDRESS}/{TEMPORAL_NAMESPACE})")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
