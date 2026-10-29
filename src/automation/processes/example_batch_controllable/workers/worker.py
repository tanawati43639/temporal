"""Worker for the batch process — registers this process's workflows and
activities, then polls its own task queue.

Each process owns its worker entrypoint (full vertical slice). The worker must
have the workflow/activity code locally; the server only stores history.

Run:
    uv run python -m automation.processes.example_batch_controllable.workers.worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE

from ..activities.batch_activities import process_item
from ..configs.queues import BATCH_QUEUE, MAX_CONCURRENT_ACTIVITIES
from ..workflows.parent import ControllableBatchParentWorkflow
from ..workflows.process_batch import ProcessBatchWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    worker = Worker(
        client,
        task_queue=BATCH_QUEUE,
        workflows=[ControllableBatchParentWorkflow, ProcessBatchWorkflow],
        activities=[process_item],
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )
    print(f"Worker running on '{BATCH_QUEUE}' ({TEMPORAL_ADDRESS}/{TEMPORAL_NAMESPACE})")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
