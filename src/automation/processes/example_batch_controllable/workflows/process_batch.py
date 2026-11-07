"""ProcessBatchWorkflow — child workflow that handles one batch of items.

A workflow is deterministic orchestration only: it calls activities, never
does I/O itself.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from automation.processes.example_batch_controllable.activities.batch_activities import (
        PIPELINE,
    )
    from automation.processes.example_batch_controllable.models.batch import (
        BatchInput,
        BatchResult,
    )


@workflow.defn
class ProcessBatchWorkflow:
    """Child workflow: process every item in one batch."""

    @workflow.run
    async def run(self, input: BatchInput) -> BatchResult:
        async def run_one(item_id: int) -> bool:
            # Each item flows through the pipeline steps in order. A permanent
            # failure (non-retryable) stops this item's pipeline and marks it
            # failed; the remaining items are unaffected.
            for step_no, step in enumerate(PIPELINE, start=1):
                try:
                    await workflow.execute_activity(
                        step,
                        item_id,
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=1),
                            maximum_attempts=3,
                            non_retryable_error_types=["ValueError"],
                        ),
                    )
                except ActivityError:
                    workflow.logger.warning(
                        "Item %s failed at step %s", item_id, step_no
                    )
                    return False
            return True

        item_ids = list(range(input.start, input.end))
        results = await asyncio.gather(*(run_one(i) for i in item_ids))

        failed_items = [i for i, ok in zip(item_ids, results) if not ok]
        return BatchResult(
            batch_id=input.batch_id,
            processed=len(item_ids) - len(failed_items),
            failed=len(failed_items),
            failed_items=failed_items,
        )
