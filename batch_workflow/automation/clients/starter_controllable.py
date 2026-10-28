"""Starter for ControllableBatchParentWorkflow.

Run:  python -m automation.clients.starter_controllable --total 1000 --concurrency 5

Prints the workflow id so you can drive it with batch_control:
    python -m automation.clients.batch_control pause  <id>
    python -m automation.clients.batch_control resume <id>
    python -m automation.clients.batch_control stop   <id>
    python -m automation.clients.batch_control status <id>
"""

import argparse
import asyncio
import uuid

from temporalio.client import Client

from automation.config.queues import BATCH_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.models.batch import ParentInput
from automation.processes.batch_controllable.parent import (
    ControllableBatchParentWorkflow,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--batches-per-run", type=int, default=4)
    parser.add_argument("--wait-result", action="store_true", help="block until workflow finishes")
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS)

    workflow_id = f"ctl-batch-parent-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        ControllableBatchParentWorkflow.run,
        ParentInput(
            total_items=args.total,
            batch_size=args.batch_size,
            max_concurrent_children=args.concurrency,
            batches_per_run=args.batches_per_run,
        ),
        id=workflow_id,
        task_queue=BATCH_QUEUE,
    )
    print(f"Started workflow: {handle.id}")
    print(f"UI: http://localhost:8080/namespaces/default/workflows/{handle.id}")
    print("Control:")
    print(f"  python -m automation.clients.batch_control status {handle.id}")
    print(f"  python -m automation.clients.batch_control pause  {handle.id}")
    print(f"  python -m automation.clients.batch_control resume {handle.id}")
    print(f"  python -m automation.clients.batch_control stop   {handle.id}")

    if args.wait_result:
        result = await handle.result()
        print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
