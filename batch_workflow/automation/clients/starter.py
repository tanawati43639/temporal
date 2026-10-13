"""Starter — triggers a batch process (puts work on the queue).

Run:  python -m automation.clients.starter --total 1000 --concurrency 20
"""

import argparse
import asyncio
import uuid

from temporalio.client import Client

from automation.config.queues import BATCH_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.models.batch import ParentInput
from automation.processes.batch.parent import BatchParentWorkflow


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--batches-per-run", type=int, default=4)
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS)

    handle = await client.start_workflow(
        BatchParentWorkflow.run,
        ParentInput(
            total_items=args.total,
            batch_size=args.batch_size,
            max_concurrent_children=args.concurrency,
            batches_per_run=args.batches_per_run,
        ),
        id=f"batch-parent-{uuid.uuid4().hex[:8]}",
        task_queue=BATCH_QUEUE,
    )
    print(f"Started workflow: {handle.id}")
    print(f"UI: http://localhost:8080/namespaces/default/workflows/{handle.id}")

    result = await handle.result()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
