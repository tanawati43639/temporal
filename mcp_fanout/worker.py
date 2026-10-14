"""Worker — queue เดียว ไม่ต้อง pin

Run:  python worker.py
      python worker.py --identity vm-1
"""

import argparse
import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from workflows.activities import call_mcp_api, call_mcp_tool
from workflows.child_workflow import ProcessCustomerWorkflow
from workflows.department_workflow import DepartmentWorkflow
from workflows.parent_workflow import FanoutWorkflow


TASK_QUEUE = "mcp-fanout-queue"


async def run_worker(identity: str) -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect("localhost:7233", identity=identity)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[FanoutWorkflow, DepartmentWorkflow, ProcessCustomerWorkflow],
        activities=[call_mcp_tool, call_mcp_api],
    )

    logging.getLogger(__name__).info(
        "Worker '%s' listening on '%s'", identity, TASK_QUEUE
    )
    await worker.run()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", default="worker-1")
    args = parser.parse_args()
    asyncio.run(run_worker(args.identity))


if __name__ == "__main__":
    main()
