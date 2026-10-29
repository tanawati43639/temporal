"""Worker for the continuous dispatcher slice.

Run:
    uv run python -m automation.processes.example_continued_workflow.workers.worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE

from ..activities.continued_activities import generate_items, process_item
from ..configs.queues import EXAMPLE_CONTINUED_QUEUE, MAX_CONCURRENT_ACTIVITIES
from ..workflows.continued import ExampleContinuedWorkflow
from ..workflows.item import ExampleItemWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    worker = Worker(
        client,
        task_queue=EXAMPLE_CONTINUED_QUEUE,
        workflows=[ExampleContinuedWorkflow, ExampleItemWorkflow],
        activities=[generate_items, process_item],
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )
    print(
        f"Worker running on '{EXAMPLE_CONTINUED_QUEUE}' "
        f"({TEMPORAL_ADDRESS}/{TEMPORAL_NAMESPACE})"
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
