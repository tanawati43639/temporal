"""Starter — ยิง workflow เข้า Temporal

Run:  python starter.py
"""

import asyncio
import json
import logging

from temporalio.client import Client

from workflows.models import DepartmentInput, FanoutInput
from workflows.parent_workflow import FanoutWorkflow

TASK_QUEUE = "mcp-fanout-queue"

SAMPLE_DEPARTMENTS = [
    DepartmentInput(department_id="dept-A", customer_ids=["C001", "C002"]),
    DepartmentInput(department_id="dept-B", customer_ids=["C003"]),
    DepartmentInput(department_id="dept-C", customer_ids=["C004", "C005", "C006"]),
]


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect("localhost:7233")

    result = await client.execute_workflow(
        FanoutWorkflow.run,
        FanoutInput(departments=SAMPLE_DEPARTMENTS),
        id="fanout-departments",
        task_queue=TASK_QUEUE,
    )

    print("\n=== Results ===")
    for dept in result:
        if dept.error:
            print(f"  {dept.department_id}: FAILED — {dept.error}")
            continue
        print(f"  {dept.department_id}: {len(dept.customers)} customers")
        for c in dept.customers:
            if c.error:
                print(f"    {c.customer_id}: FAILED — {c.error}")
            else:
                print(f"    {c.customer_id}: OK — {json.dumps(c.profile, indent=2)}")


if __name__ == "__main__":
    asyncio.run(run())
