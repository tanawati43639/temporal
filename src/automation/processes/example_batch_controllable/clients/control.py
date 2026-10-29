"""Drive a running ControllableBatchParentWorkflow: pause / resume / stop /
status / pause-wait.

Run:
    uv run python -m automation.processes.example_batch_controllable.clients.control \
        <command> <workflow_id>
"""

import argparse
import asyncio

from temporalio.client import Client

from config.settings import TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE

from ..workflows.parent import ControllableBatchParentWorkflow


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["pause", "resume", "stop", "status", "pause-wait"],
    )
    parser.add_argument("workflow_id")
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    handle = client.get_workflow_handle(args.workflow_id)

    if args.command == "pause":
        await handle.signal(ControllableBatchParentWorkflow.request_pause)
        print("pause signal sent")
    elif args.command == "resume":
        await handle.signal(ControllableBatchParentWorkflow.request_resume)
        print("resume signal sent")
    elif args.command == "stop":
        await handle.signal(ControllableBatchParentWorkflow.request_stop)
        print("stop signal sent")
    elif args.command == "status":
        print("state:", await handle.query(ControllableBatchParentWorkflow.state))
        print("progress:", await handle.query(ControllableBatchParentWorkflow.progress))
    elif args.command == "pause-wait":
        snapshot = await handle.execute_update(
            ControllableBatchParentWorkflow.pause_and_wait
        )
        print("paused at:", snapshot)


if __name__ == "__main__":
    asyncio.run(main())
