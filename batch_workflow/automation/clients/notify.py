"""Trigger the notify process.

Run:  python -m automation.clients.notify --to someone@example.com
"""

import argparse
import asyncio
import uuid

from temporalio.client import Client

from automation.config.queues import BATCH_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.models.notify import NotifyInput
from automation.processes.notify.notify_workflow import NotifyWorkflow


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default="user@example.com")
    parser.add_argument("--report", default="monthly-summary.pdf")
    parser.add_argument("--ref", default="s3://reports/monthly-summary.pdf")
    args = parser.parse_args()

    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = await client.start_workflow(
        NotifyWorkflow.run,
        NotifyInput(recipient=args.to, report_name=args.report, report_ref=args.ref),
        id=f"notify-{uuid.uuid4().hex[:8]}",
        task_queue=BATCH_QUEUE,
    )
    print(f"Started: {handle.id}")
    print(f"Result (uploaded path): {await handle.result()}")


if __name__ == "__main__":
    asyncio.run(main())
