"""Start an ExampleContinuedWorkflow from the CLI.

Run:
    uv run python -m automation.processes.example_continued_workflow.clients.starter \
        --run-seconds 60
"""

import argparse
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, temporal_ui_link

from ..configs.queues import EXAMPLE_CONTINUED_QUEUE
from ..models.continued import ContinuedInput
from ..workflows.continued import ExampleContinuedWorkflow

_CTL = "automation.processes.example_continued_workflow.clients.control"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-seconds", type=int, default=300, help="how long to keep generating"
    )
    parser.add_argument("--wait-result", action="store_true")
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)

    stop_time = (
        datetime.now(timezone.utc) + timedelta(seconds=args.run_seconds)
    ).isoformat()
    workflow_id = f"continued-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        ExampleContinuedWorkflow.run,
        ContinuedInput(stop_time=stop_time),
        id=workflow_id,
        task_queue=EXAMPLE_CONTINUED_QUEUE,
    )
    print(f"Started workflow: {handle.id}  (stop_time={stop_time})")
    print(f"UI: {temporal_ui_link(handle.id)}")
    print("Control:")
    print(f"  uv run python -m {_CTL} status {handle.id}")
    print(f"  uv run python -m {_CTL} stop   {handle.id}")

    if args.wait_result:
        print(f"Result: {await handle.result()}")


if __name__ == "__main__":
    asyncio.run(main())
