"""Worker for the audit-log process.

Run:
    uv run python -m automation.processes.audit_log.workers.worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, get_tls_config

from ..activities.audit_activities import ACTIVITIES
from ..configs.queues import AUDIT_LOG_QUEUE, MAX_CONCURRENT_ACTIVITIES
from ..workflows.audit_log import AuditLogWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(
        TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE, tls=get_tls_config()
    )
    worker = Worker(
        client,
        task_queue=AUDIT_LOG_QUEUE,
        workflows=[AuditLogWorkflow],
        activities=[*ACTIVITIES],
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )
    print(f"Worker running on '{AUDIT_LOG_QUEUE}' ({TEMPORAL_ADDRESS}/{TEMPORAL_NAMESPACE})")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
