"""Starter — ยิง workflow เข้า Temporal

Run:  python starter.py
      python starter.py --customers C001 C002 C003 C004 C005
"""

import argparse
import asyncio
import json
import logging

from temporalio.client import Client

from workflows.models import FanoutInput
from workflows.parent_workflow import FanoutWorkflow

TASK_QUEUE = "mcp-fanout-queue"


async def run(customer_ids: list[str]) -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect("localhost:7233")

    result = await client.execute_workflow(
        FanoutWorkflow.run,
        FanoutInput(customer_ids=customer_ids),
        id="fanout-customers",
        task_queue=TASK_QUEUE,
    )

    print("\n=== Results ===")
    for r in result:
        if r.error:
            print(f"  {r.customer_id}: FAILED — {r.error}")
        else:
            print(f"  {r.customer_id}: OK — {json.dumps(r.profile, indent=2)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--customers",
        nargs="+",
        default=["C001", "C002", "C003", "C004", "C005"],
    )
    args = parser.parse_args()
    asyncio.run(run(args.customers))


if __name__ == "__main__":
    main()
