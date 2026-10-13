"""Schedules — the Temporal equivalent of Blue Prism Control Room schedules.

Create/refresh the schedules by running this module. A Schedule periodically
starts a process without anyone pressing a button.

Run:  python -m automation.schedules.definitions
"""

import asyncio
from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)

from automation.config.queues import BATCH_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.models.batch import ParentInput
from automation.processes.batch.parent import BatchParentWorkflow


async def create_batch_schedule() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS)
    schedule_id = "batch-hourly"
    try:
        await client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    BatchParentWorkflow.run,
                    ParentInput(total_items=1000),
                    id="scheduled-batch",
                    task_queue=BATCH_QUEUE,
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]
                ),
            ),
        )
        print(f"Created schedule '{schedule_id}' (every 1h)")
    except Exception as e:
        print(f"Schedule '{schedule_id}' not created (may already exist): {e}")


if __name__ == "__main__":
    asyncio.run(create_batch_schedule())
