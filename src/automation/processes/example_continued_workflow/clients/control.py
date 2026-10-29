"""Drive a running ExampleContinuedWorkflow: stop / status.

Run:
    uv run python -m automation.processes.example_continued_workflow.clients.control \
        <command> <workflow_id>
"""

import argparse
import asyncio

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE

from ..workflows.continued import ExampleContinuedWorkflow


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["stop", "status"])
    parser.add_argument("workflow_id")
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    handle = client.get_workflow_handle(args.workflow_id)

    if args.command == "stop":
        await handle.signal(ExampleContinuedWorkflow.request_stop)
        print("stop signal sent")
    else:
        print("state:", await handle.query(ExampleContinuedWorkflow.state))
        print("progress:", await handle.query(ExampleContinuedWorkflow.progress))


if __name__ == "__main__":
    asyncio.run(main())
