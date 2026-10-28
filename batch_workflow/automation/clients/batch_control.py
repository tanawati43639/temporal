"""Batch control — send pause/resume/stop signals and read live status.

Usage:
    python -m automation.clients.batch_control status <workflow-id>
    python -m automation.clients.batch_control pause  <workflow-id>
    python -m automation.clients.batch_control resume <workflow-id>
    python -m automation.clients.batch_control stop   <workflow-id>

Target workflow must be a ControllableBatchParentWorkflow instance.
"""

import argparse
import asyncio
import json

from temporalio.client import Client

from automation.config.settings import TEMPORAL_ADDRESS
from automation.processes.batch_controllable.parent import (
    ControllableBatchParentWorkflow,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Control a controllable batch workflow")
    parser.add_argument(
        "command",
        choices=["status", "pause", "pause-wait", "resume", "stop"],
        help="pause-wait blocks until the workflow actually reaches the pause boundary",
    )
    parser.add_argument("workflow_id", help="target workflow id")
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle_for(
        ControllableBatchParentWorkflow.run, args.workflow_id
    )

    if args.command == "status":
        state = await handle.query(ControllableBatchParentWorkflow.state)
        progress = await handle.query(ControllableBatchParentWorkflow.progress)
        print(json.dumps({"state": state, "progress": progress}, indent=2))
        return

    if args.command == "pause-wait":
        snapshot = await handle.execute_update(
            ControllableBatchParentWorkflow.pause_and_wait
        )
        print(json.dumps({"paused_at": snapshot}, indent=2))
        return

    signal = {
        "pause": ControllableBatchParentWorkflow.request_pause,
        "resume": ControllableBatchParentWorkflow.request_resume,
        "stop": ControllableBatchParentWorkflow.request_stop,
    }[args.command]
    await handle.signal(signal)
    print(f"Sent {args.command} to {args.workflow_id}")


if __name__ == "__main__":
    asyncio.run(main())
