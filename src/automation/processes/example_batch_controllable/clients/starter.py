"""Start a ControllableBatchParentWorkflow from the CLI.

Run:
    uv run python -m automation.processes.example_batch_controllable.clients.starter \
        --total 1000 --concurrency 5

Prints the workflow id so you can drive it with control.py.
"""

import argparse
import asyncio
import uuid

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, temporal_ui_link

from ..configs.queues import BATCH_QUEUE
from ..models.batch import ParentInput
from ..workflows.parent import ControllableBatchParentWorkflow

_CTL = "automation.processes.example_batch_controllable.clients.control"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--batches-per-run", type=int, default=4)
    parser.add_argument(
        "--wait-result", action="store_true", help="block until the workflow finishes"
    )
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)

    workflow_id = f"ctl-batch-{uuid.uuid4().hex[:8]}"
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
    print(f"UI: {temporal_ui_link(handle.id)}")
    print("Control:")
    print(f"  uv run python -m {_CTL} status {handle.id}")
    print(f"  uv run python -m {_CTL} pause  {handle.id}")
    print(f"  uv run python -m {_CTL} resume {handle.id}")
    print(f"  uv run python -m {_CTL} stop   {handle.id}")

    if args.wait_result:
        result = await handle.result()
        print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
